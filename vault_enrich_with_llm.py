#!/usr/bin/env python3
"""
Enrich vault_manifest.json using an LLM via Ollama.

Pass 2 of the pipeline:

- For each note in vault_manifest.json:
    - Read a short snippet from the note body.
    - Send title, existing tags, snippet, and the list of all other note titles
      to an LLM exposed via Ollama /api/chat.
    - Ask the model to return:
        extra_tags:      additional tags (short tokens)
        link_to_titles:  titles of existing notes this note should link to
        concept_nodes:   titles of "hub" notes that should exist

- Store these fields back into vault_manifest.json.

Model-agnostic: any Ollama model that can return JSON through /api/chat will work.
See https://github.com/ollama/ollama/blob/main/docs/api.md for API details. [web:107]
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional

import requests
import yaml

# ----------------- CONFIG -----------------

# Default vault path; you can override this at runtime when prompted.
DEFAULT_VAULT_PATH = Path("/path/to/your/vault")

# Manifest filename produced by vault_tag_link_bootstrap.py
MANIFEST_FILENAME = "vault_manifest.json"

# Ollama API configuration
OLLAMA_URL = "http://localhost:11434/api/chat"   # /api/chat endpoint [web:107][web:119]
OLLAMA_MODEL = "llama3.1:latest"                # e.g. "llama3.1:latest", "qwen3.5:latest", "minimax-m2.5:cloud"

# Max number of files to enrich in one run; set to None to process all
MAX_FILES: Optional[int] = None

# How many characters of the note body to send as context
SNIPPET_CHARS = 800


# ----------------- UTILITIES -----------------

def prompt_vault_path() -> Path:
    """Ask user for vault path, with default."""
    default_str = str(DEFAULT_VAULT_PATH)
    entered = input(f"Vault path? [default: {default_str}] ").strip()
    path_str = entered or default_str
    path = Path(path_str).expanduser()
    if not path.exists() or not path.is_dir():
        print(f"ERROR: invalid vault path: {path}", file=sys.stderr)
        sys.exit(1)
    return path


def load_manifest(vault_root: Path) -> Dict[str, Dict]:
    """Load existing manifest as dict[path_str] -> metadata."""
    manifest_path = vault_root / MANIFEST_FILENAME
    if not manifest_path.exists():
        print(f"ERROR: manifest not found at {manifest_path}", file=sys.stderr)
        sys.exit(1)
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"ERROR: cannot decode manifest JSON: {e}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(data, dict):
        print("ERROR: manifest JSON root must be an object (dict[path] -> meta).", file=sys.stderr)
        sys.exit(1)
    print(f"Loaded manifest with {len(data)} entries from {manifest_path}")
    return data


def save_manifest(vault_root: Path, manifest: Dict[str, Dict]) -> None:
    """Write manifest back to disk."""
    manifest_path = vault_root / MANIFEST_FILENAME
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(f"Updated manifest written to: {manifest_path}")


def split_frontmatter(raw: str) -> Tuple[Optional[str], str]:
    """
    Split YAML frontmatter from body.
    Returns (yaml_str_or_None, body_str).
    """
    if not raw.startswith("---\n"):
        return None, raw
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return None, raw
    yaml_str = parts[1]
    body = parts[2]
    if body.startswith("\n"):
        body = body[1:]
    return yaml_str, body


def read_snippet(vault_root: Path, rel_path: str, max_chars: int = SNIPPET_CHARS) -> str:
    """
    Read a short snippet from the note body (without frontmatter) for model context.
    """
    path = vault_root / rel_path
    try:
        raw = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"WARNING: cannot read {rel_path}: {e}", file=sys.stderr)
        return ""
    _, body = split_frontmatter(raw)
    body = body.strip()
    if len(body) > max_chars:
        body = body[:max_chars]
    return body


# ----------------- LLM CALL -----------------

def build_llm_payload(
    title: str,
    tags: List[str],
    snippet: str,
    all_titles: List[str],
) -> Dict:
    """
    Build Ollama /api/chat payload for a generic vault enrichment task.

    The model is asked to:
    - propose extra_tags (short tokens),
    - suggest link_to_titles (existing note titles),
    - propose concept_nodes (hub notes that should exist).
    """
    system_msg = (
        "You help structure an Obsidian-like note vault by enriching note metadata.\n"
        "\n"
        "Given a note title, its existing tags, a short text snippet, and the list "
        "of all other note titles in the vault, you must propose:\n"
        "- extra_tags: 3-10 short tags that summarise the topic "
        "  (single words, lowercase, no spaces or special characters).\n"
        "- link_to_titles: titles of EXISTING notes that this note should link to, "
        "  based on obvious relationships (empty list if none).\n"
        "- concept_nodes: titles of hub/concept notes that SHOULD exist if missing "
        "  (e.g. 'LinkedIn strategy', 'Product launch plan', 'Architecture overview').\n"
        "\n"
        "Be pragmatic and domain-agnostic: infer structure only from the inputs.\n"
        "Do NOT add explanations, comments, or prose. Return JSON only.\n"
    )

    user_instructions = {
        "note_title": title,
        "existing_tags": tags,
        "snippet": snippet,
        "all_other_titles": [t for t in all_titles if t != title],
        "output_format": {
            "extra_tags": "list of short tokens (lowercase, no spaces, no special characters)",
            "link_to_titles": "list of exact note titles from all_other_titles (empty list if none)",
            "concept_nodes": "list of new hub note titles, each 2-5 words, Title Case",
        },
        "constraints": [
            "Do NOT invent links to notes that do not exist. link_to_titles must come from all_other_titles.",
            "Do NOT return explanations or prose, only JSON.",
            "Do NOT wrap the JSON in markdown fences.",
            "extra_tags should NOT contain single letters or pure numbers.",
        ],
    }

    return {
        "model": OLLAMA_MODEL,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": json.dumps(user_instructions, ensure_ascii=False)},
        ],
        "stream": False,
        "format": "json",  # ask Ollama to return JSON in message.content [web:107][web:119]
    }


def call_llm(payload: Dict) -> Optional[Dict]:
    """
    Call Ollama /api/chat and return parsed JSON dict, handling markdown fences.
    """
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=600)
        resp.raise_for_status()
    except Exception as e:
        print(f"WARNING: Ollama/LLM call failed: {e}", file=sys.stderr)
        return None

    try:
        data = resp.json()
    except Exception as e:
        print(f"WARNING: cannot parse Ollama JSON response: {e}", file=sys.stderr)
        return None

    # Native /api/chat returns:
    # { "model": "...", "message": { "role": "assistant", "content": "..." }, ... } [web:107][web:119]
    msg = data.get("message") or {}
    content = msg.get("content", "")
    if not isinstance(content, str):
        print("WARNING: assistant content is not a string", file=sys.stderr)
        return None
    content = content.strip()
    if not content:
        print("WARNING: empty content from model", file=sys.stderr)
        return None

    # --- Clean up Markdown fences or extra text around JSON ---
    # 1) Remove ```json ... ``` or ``` ... ``` fences if present
    if content.startswith("```"):
        lines = content.splitlines()
        # drop opening fence
        lines = lines[1:]
        # drop closing fence if present
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        content = "\n".join(lines).strip()

    # 2) If there is still extra text, try to isolate the JSON object by braces
    if not content.startswith("{") or not content.endswith("}"):
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            content = content[start : end + 1].strip()

    # Finally, try to parse JSON
    try:
        result = json.loads(content)
    except json.JSONDecodeError as e:
        print(
            f"WARNING: assistant content is not valid JSON: {e} | content={content[:200]}",
            file=sys.stderr,
        )
        return None

    if not isinstance(result, dict):
        print("WARNING: parsed JSON is not an object", file=sys.stderr)
        return None
    return result


def sanitize_tags(tags: List[str]) -> List[str]:
    """
    Apply same hygiene rules as bootstrap script:
    - lowercase
    - drop empty
    - drop single letters and pure numbers
    """
    def ok(t: str) -> bool:
        t = str(t).strip()
        if not t:
            return False
        if len(t) == 1:
            return False
        if t.isdigit():
            return False
        return True

    return [str(t).lower() for t in tags if ok(t)]


# ----------------- ENRICHMENT LOGIC -----------------

def enrich_manifest_with_llm(vault_root: Path, manifest: Dict[str, Dict]) -> Dict[str, Dict]:
    """
    For each manifest entry, call the LLM and enrich with:
      - extra_tags
      - link_to_titles
      - concept_nodes
    """
    # Build title index
    all_titles: List[str] = []
    for meta in manifest.values():
        title = meta.get("title")
        if isinstance(title, str):
            all_titles.append(title)

    updated = 0
    total = len(manifest)
    print(f"Starting enrichment over {total} notes...")

    for i, (rel_path, meta) in enumerate(manifest.items(), start=1):
        title = meta.get("title")
        if not isinstance(title, str) or not title.strip():
            continue

        tags = meta.get("tags", [])
        if not isinstance(tags, list):
            tags = []

        snippet = read_snippet(vault_root, rel_path)        

        print(f"[{i}/{total}] Enriching: {rel_path} (title='{title}')...")
        payload = build_llm_payload(title, tags, snippet, all_titles)
        result = call_llm(payload)
        if result is None:
            print(f"    -> Skipped (LLM call failed or invalid JSON).")
            continue

        extra_tags = sanitize_tags(result.get("extra_tags", []))
        link_to_titles = result.get("link_to_titles", [])
        concept_nodes = result.get("concept_nodes", [])

        if extra_tags:
            meta["extra_tags"] = extra_tags
        if isinstance(link_to_titles, list):
            meta["link_to_titles"] = link_to_titles
        if isinstance(concept_nodes, list):
            meta["concept_nodes"] = concept_nodes

        manifest[rel_path] = meta
        updated += 1
        print(
            f"    -> Updated "
            f"extra_tags={len(extra_tags)}, "
            f"links={len(link_to_titles)}, "
            f"concept_nodes={len(concept_nodes)}"
        )

        if i % 20 == 0:
            print(f"Processed {i}/{total} files (updated {updated})...")

        if MAX_FILES is not None and updated >= MAX_FILES:
            print(f"MAX_FILES={MAX_FILES} limit reached, stopping.")
            break

    print(f"LLM enrichment complete. Updated entries: {updated}")
    return manifest


# ----------------- MAIN -----------------

def main() -> None:
    vault_root = prompt_vault_path()
    manifest = load_manifest(vault_root)
    manifest = enrich_manifest_with_llm(vault_root, manifest)
    save_manifest(vault_root, manifest)


if __name__ == "__main__":
    main()
