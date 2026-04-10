#!/usr/bin/env python3
"""
Bootstrap tags and manifest for an Obsidian vault.

Pass 1:
- Walk all *.md and *.txt files under a vault path.
- Ensure YAML frontmatter exists.
- Derive basic tags from filename and folders (incl. immediate parent folder).
- Update/append to vault_manifest.json with per-file metadata.

Run from WSL2:
  source .venv/bin/activate
  python vault_tag_link_bootstrap.py
"""

import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

# ---------- CONFIGURABLE DEFAULTS ----------

DEFAULT_VAULT_PATH = Path("/path/to/your/vault")  # can be overridden at runtime
MANIFEST_FILENAME = "vault_manifest.json"

# Folders -> base tags
# Keys are LOWERCASE folder names; values are lists of tags to add for any note inside.
# Customize this mapping to fit your vault structure.
FOLDER_TAG_HINTS = {
    "inbox": ["inbox"],
    "ideas": ["ideas"],
    "notes": ["notes"],
    "docs": ["docs"],
    "guides": ["guides"],
    "research": ["research"],
    "decisions": ["decisions"],
    "concepts": ["concepts"],
    "journal": ["journal"],
    "projects": ["projects"],
}

# File extensions to process
VALID_EXTENSIONS = {".md", ".txt"}

# Directories to skip entirely
SKIP_DIRS = {".obsidian", ".git", ".venv"}


# ---------- HELPERS ----------

def prompt_vault_path() -> Path:
    """Ask user for vault path, with default."""
    default_str = str(DEFAULT_VAULT_PATH)
    entered = input(f"Vault path? [default: {default_str}] ").strip()
    path_str = entered or default_str
    path = Path(path_str).expanduser()
    if not path.exists():
        print(f"ERROR: Path does not exist: {path}", file=sys.stderr)
        sys.exit(1)
    if not path.is_dir():
        print(f"ERROR: Path is not a directory: {path}", file=sys.stderr)
        sys.exit(1)
    return path


def simple_slug_split(token: str) -> List[str]:
    """
    Helper: split a single token into words by camelCase.
    Assumes separators have already been handled.
    """
    # Insert spaces before capitals (camelCase/snakeMixed)
    token = re.sub(r"(?<!^)(?=[A-Z])", " ", token)
    return [w.lower() for w in token.split() if w]


def slug_to_words(slug: str) -> List[str]:
    """
    Convert filename slug into tag-ish words.

    Handles:
    - post_linkedin_launch -> ["post", "linkedin", "launch"]
    - PostLinkedInLaunch   -> ["post", "linkedin", "launch"]
    - ENV_SETUP            -> ["env", "setup"]  (fix for single-letter tags)
    """
    # Strip extension if present
    slug = re.sub(r"\.[^.]+$", "", slug)

    # Replace separators with spaces first
    slug = slug.replace("-", " ").replace("_", " ")

    tokens = [t for t in slug.split() if t]
    words: List[str] = []

    for tok in tokens:
        if tok.isupper() and len(tok) > 1:
            # ALL CAPS token, treat it as one word, downcased
            words.append(tok.lower())
        else:
            # Normal case or mixed -> camelCase split
            words.extend(simple_slug_split(tok))

    return words


def title_from_filename(path: Path) -> str:
    """Derive a human-readable title from filename."""
    name = path.stem  # no extension
    words = slug_to_words(name)
    return " ".join(w.capitalize() for w in words) or name


def infer_folder_tags(path: Path, vault_root: Path) -> List[str]:
    """
    Infer tags from folder names based on FOLDER_TAG_HINTS
    AND always include immediate parent folder name as tags.
    """
    tags: List[str] = []

    try:
        rel = path.relative_to(vault_root)
    except ValueError:
        return tags

    # Immediate parent folder
    if rel.parent != Path("."):
        parent_name = rel.parent.name
        # parent folder name as tags (slugged)
        tags.extend(slug_to_words(parent_name))

    # Walk all parent folders for semantic hints
    for part in rel.parents:
        folder_name = part.name
        key = folder_name.lower()
        if key in FOLDER_TAG_HINTS:
            tags.extend(FOLDER_TAG_HINTS[key])

    return tags


def read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def split_frontmatter(raw: str) -> Tuple[Optional[str], str]:
    """
    Split YAML frontmatter from body.
    Returns (yaml_str_or_None, body_str).
    """
    if not raw.startswith("---\n"):
        return None, raw

    parts = raw.split("---", 2)
    if len(parts) < 3:
        # malformed frontmatter
        return None, raw
    # parts: ["", "\nYAML...\n", "\nrest of file"]
    yaml_str = parts[1]
    body = parts[2]
    # Strip leading/trailing newlines
    if body.startswith("\n"):
        body = body[1:]
    return yaml_str, body


def merge_tags(existing: List[str], new: List[str]) -> List[str]:
    """Merge tag lists, deduplicated, preserve order; drop 1-char and all-digit tokens."""
    def ok(t: str) -> bool:
        t = t.strip()
        if not t:
            return False
        if len(t) == 1:        # drop single letters like 'a', 'x'
            return False
        if t.isdigit():        # drop pure numbers like '01', '2024'
            return False
        return True

    # Normalize to strings and filter
    existing = [str(t) for t in existing if ok(str(t))]
    new = [str(t) for t in new if ok(str(t))]

    seen = set(existing)
    merged = list(existing)
    for t in new:
        if t not in seen:
            seen.add(t)
            merged.append(t)
    return merged


def ensure_frontmatter(
    path: Path,
    vault_root: Path,
) -> Dict:
    """
    Ensure file has YAML frontmatter.
    Return metadata dict for manifest, including:
    - path (relative)
    - title
    - tags
    - generated_title (bool)
    """
    raw = read_file(path)
    yaml_str, body = split_frontmatter(raw)

    meta: Dict = {}
    existed = yaml_str is not None

    if existed:
        try:
            fm = yaml.safe_load(yaml_str) or {}
        except yaml.YAMLError:
            fm = {}
    else:
        fm = {}

    # Title
    if "title" in fm and isinstance(fm["title"], str):
        title = fm["title"].strip()
        generated_title = False
    else:
        title = title_from_filename(path)
        fm["title"] = title
        generated_title = True

    # Tags
    existing_tags = fm.get("tags", [])
    if isinstance(existing_tags, str):
        existing_tags = [existing_tags]
    elif not isinstance(existing_tags, list):
        existing_tags = []

    filename_tags = slug_to_words(path.stem)
    folder_tags = infer_folder_tags(path, vault_root)
    base_tags = filename_tags + folder_tags

    fm["tags"] = merge_tags(existing_tags, base_tags)

    # Mark that this metadata was at least touched by the script
    fm["generated_meta"] = True

    # Compose new file content
    new_yaml = yaml.safe_dump(fm, sort_keys=False).strip()
    new_content = f"---\n{new_yaml}\n---\n\n{body}"

    path.write_text(new_content, encoding="utf-8")

    rel_path = str(path.relative_to(vault_root))

    meta["path"] = rel_path
    meta["title"] = title
    meta["tags"] = fm["tags"]
    meta["generated_title"] = generated_title
    meta["had_frontmatter"] = existed

    return meta


def load_manifest(manifest_path: Path) -> Dict[str, Dict]:
    if not manifest_path.exists():
        return {}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        # Expecting dict[path] -> meta
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    return {}


def save_manifest(manifest_path: Path, manifest: Dict[str, Dict]) -> None:
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def should_skip(path: Path, vault_root: Path) -> bool:
    """
    Skip files in SKIP_DIRS and some internal files.
    """
    try:
        rel = path.relative_to(vault_root)
    except ValueError:
        return True

    # Skip internal dirs
    for part in rel.parts:
        if part in SKIP_DIRS:
            return True

    # Skip manifest itself
    if rel.name == MANIFEST_FILENAME:
        return True

    return False


# ---------- MAIN ----------

def main() -> None:
    vault_root = prompt_vault_path()

    print(f"Using vault root: {vault_root}")

    manifest_path = vault_root / MANIFEST_FILENAME
    manifest = load_manifest(manifest_path)

    count_processed = 0

    for path in vault_root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in VALID_EXTENSIONS:
            continue
        if should_skip(path, vault_root):
            continue

        meta = ensure_frontmatter(path, vault_root)
        manifest[meta["path"]] = meta
        count_processed += 1

        if count_processed % 50 == 0:
            print(f"Processed {count_processed} files...")

    save_manifest(manifest_path, manifest)

    print(f"Done. Processed {count_processed} files.")
    print(f"Manifest written to: {manifest_path}")


if __name__ == "__main__":
    main()
