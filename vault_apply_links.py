#!/usr/bin/env python3
"""
Apply LLM-enriched manifest back into the vault.

Pass 3 of the pipeline:

- Ensure concept notes exist for all `concept_nodes`.
- For each note:
    - Merge `extra_tags` into frontmatter tags.
    - Append a '## Related' section with wiki-links for `link_to_titles`.

Assumes:
- vault_tag_link_bootstrap.py has created vault_manifest.json with basic metadata.
- vault_enrich_with_llm.py has added extra_tags, link_to_titles, concept_nodes.

This script is conservative:
- It only adds content (tags and sections), it does not delete or rewrite main bodies.
"""

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

# ----------------- CONFIG -----------------

# Default vault path; you can override this at runtime when prompted.
DEFAULT_VAULT_PATH = Path("/path/to/your/vault")

# Manifest filename
MANIFEST_FILENAME = "vault_manifest.json"

# Folder under vault root where concept/hub notes are created
CONCEPT_NOTE_DIR = "00-Concepts"

# File extensions to process
VALID_EXTENSIONS = {".md", ".txt"}

# Directories to skip entirely
SKIP_DIRS = {".obsidian", ".git", ".venv"}


# ----------------- UTILITIES -----------------

def prompt_vault_path() -> Path:
    default_str = str(DEFAULT_VAULT_PATH)
    entered = input(f"Vault path? [default: {default_str}] ").strip()
    path_str = entered or default_str
    path = Path(path_str).expanduser()
    if not path.exists() or not path.is_dir():
        print(f"ERROR: invalid vault path: {path}", file=sys.stderr)
        sys.exit(1)
    return path


def load_manifest(vault_root: Path) -> Dict[str, Dict]:
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


def merge_tags(existing: List[str], new: List[str]) -> List[str]:
    """
    Merge tags with hygiene:
    - lowercase
    - drop empty
    - drop single letters and pure numbers
    Preserve original order for existing tags, then append new.
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

    existing = [str(t).lower() for t in existing if ok(t)]
    new = [str(t).lower() for t in new if ok(t)]

    seen = set(existing)
    merged = list(existing)
    for t in new:
        if t not in seen:
            seen.add(t)
            merged.append(t)
    return merged


def should_skip(path: Path, vault_root: Path) -> bool:
    """
    Skip files in SKIP_DIRS and internal files like manifest.
    """
    try:
        rel = path.relative_to(vault_root)
    except ValueError:
        return True
    for part in rel.parts:
        if part in SKIP_DIRS:
            return True
    if rel.name == MANIFEST_FILENAME:
        return True
    return False


# ----------------- CONCEPT NOTES -----------------

def ensure_concept_notes(vault_root: Path, manifest: Dict[str, Dict]) -> None:
    """
    Create concept/hub notes for all titles listed in `concept_nodes`.
    Notes are created under CONCEPT_NOTE_DIR if they do not already exist.
    """
    concept_dir = vault_root / CONCEPT_NOTE_DIR
    concept_dir.mkdir(exist_ok=True)

    # Collect all concept node titles from manifest
    titles: List[str] = []
    for meta in manifest.values():
        lst = meta.get("concept_nodes") or []
        if isinstance(lst, list):
            for t in lst:
                if isinstance(t, str) and t.strip():
                    titles.append(t.strip())

    titles = sorted(set(titles))
    if not titles:
        print("No concept_nodes found in manifest.")
        return

    print(f"Concept nodes to ensure: {len(titles)}")

    for title in titles:
        # Derive filename from title (minimal slugify)
        slug = re.sub(r"[^\w\s-]", "", title)
        slug = re.sub(r"\s+", "_", slug.strip())
        if not slug:
            continue
        path = concept_dir / f"{slug}.md"
        if path.exists():
            continue

        fm = {
            "title": title,
            "tags": ["concept"],
            "generated_meta": True,
        }
        yaml_str = yaml.safe_dump(fm, sort_keys=False).strip()
        content = f"---\n{yaml_str}\n---\n\nPlaceholder concept note for {title}.\n"
        path.write_text(content, encoding="utf-8")
        print(f"Created concept note: {path.relative_to(vault_root)}")


# ----------------- APPLY TAGS & LINKS -----------------

def apply_links_and_tags(vault_root: Path, manifest: Dict[str, Dict]) -> None:
    """
    For each manifest entry:
    - Merge extra_tags into frontmatter tags.
    - Append a '## Related' section with wiki-links for link_to_titles.
    """
    updated_files = 0

    for rel_path, meta in manifest.items():
        link_titles = meta.get("link_to_titles") or []
        extra_tags = meta.get("extra_tags") or []

        if not link_titles and not extra_tags:
            continue  # nothing to do for this file

        path = vault_root / rel_path
        if not path.exists() or not path.is_file():
            continue
        if path.suffix.lower() not in VALID_EXTENSIONS:
            continue
        if should_skip(path, vault_root):
            continue

        raw = path.read_text(encoding="utf-8")
        yaml_str, body = split_frontmatter(raw)

        if yaml_str is not None:
            try:
                fm = yaml.safe_load(yaml_str) or {}
            except yaml.YAMLError:
                fm = {}
        else:
            fm = {}

        existing_tags = fm.get("tags", [])
        if isinstance(existing_tags, str):
            existing_tags = [existing_tags]
        elif not isinstance(existing_tags, list):
            existing_tags = []

        fm["tags"] = merge_tags(existing_tags, extra_tags)
        fm["generated_meta"] = True

        # Build '## Related' section
        related_links = [t for t in link_titles if isinstance(t, str) and t.strip()]
        related_md = ""
        if related_links:
            related_md_lines = ["", "## Related", ""]
            for t in sorted(set(related_links)):
                related_md_lines.append(f"- [[{t}]]")
            related_md_lines.append("")  # trailing newline
            related_md = "\n".join(related_md_lines)

        # Avoid duplicating Related sections if already present
        if "## Related" in body:
            new_body = body
        else:
            new_body = body.rstrip() + related_md

        new_yaml = yaml.safe_dump(fm, sort_keys=False).strip()
        new_content = f"---\n{new_yaml}\n---\n\n{new_body}\n"
        path.write_text(new_content, encoding="utf-8")
        updated_files += 1

    print(f"Applied extra_tags and related links to {updated_files} files.")


# ----------------- MAIN -----------------

def main() -> None:
    vault_root = prompt_vault_path()
    manifest = load_manifest(vault_root)
    ensure_concept_notes(vault_root, manifest)
    apply_links_and_tags(vault_root, manifest)


if __name__ == "__main__":
    main()
