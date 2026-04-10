# Obsidian Vault Auto-Tag & Link Enricher

Turn a messy Obsidian vault into a structured, tag‑rich, interlinked **knowledge graph** using Python + a local (or cloud) LLM (via Ollama).

This repo contains a small toolchain that:

1. Normalizes frontmatter across all your `.md` / `.txt` notes.
2. Auto‑generates sensible tags from filenames and folder structure.
3. Calls an LLM (e.g. Qwen / Llama / Minimax via Ollama) to:
   - propose **extra tags**,
   - suggest **links to other notes**,
   - propose **hub “concept notes”**.
4. Injects those tags and `[[wiki-links]]` back into your vault in a safe, non‑destructive way.

The goal: give Obsidian, Claude Code, and other agents a **smarter graph** to work with, without manually linking hundreds of notes.

---

## Why this exists

When you have dozens or hundreds of project notes (product, marketing, architecture, research), Obsidian’s graph stays mostly empty unless you manually add `[[links]]`. Plugins like Note Linker help, but are mostly keyword‑based rather than truly semantic.

This setup:

- Bootstraps frontmatter and base tags from **filenames + folder names** (e.g. `03-AEGIS-Product/docs/guides/ENV_SETUP.md` → tags like `env`, `setup`, `docs`, `guides`, `aegis`, `product`).
- Lets an LLM look at title + snippet + existing note titles and propose:
  - extra tags,
  - related note titles,
  - hub concepts that should exist.
- Then writes everything back into your vault, ready for:
  - Obsidian’s graph view,
  - Claude Code’s local context,
  - future RAG indexing.

You can use it for personal PKM, but it’s especially nice for **SaaS/agentic projects** where the vault effectively becomes a modular, agent‑readable “company brain”.

---

## Overview

The toolchain is three Python scripts:

1. `vault_tag_link_bootstrap.py`  
   Pass 1: ensure frontmatter, derive baseline tags, and build `vault_manifest.json`.

2. `vault_enrich_with_qwen.py`  
   Pass 2: call a model (via Ollama) per note to enrich:
   - `extra_tags`
   - `link_to_titles`
   - `concept_nodes`

3. `vault_apply_links.py`  
   Pass 3: write enriched data back into the vault:
   - create concept notes,
   - merge `extra_tags` into frontmatter tags,
   - append `## Related` sections with `[[links]]`.

Everything is designed to be:

- **Idempotent**: you can re‑run passes safely as your notes evolve.
- **Model‑agnostic**: any Ollama model that returns JSON works (local or cloud). [web:107][web:119]
- **Non‑destructive**: the scripts add frontmatter and sections; they don’t rewrite your prose.

---

## Requirements

- WSL2 Ubuntu (or any Linux/Mac terminal with Python 3.x).
- Python 3.10+ with `venv` support. [web:105]
- Obsidian vault on a filesystem path (e.g. `/home/you/my-vault/my-vault`).
- **Ollama** running locally (or available on your machine), with at least one model pulled: [web:107][web:119]
  - Good starting options:
    - `llama3.1:latest` (general purpose),
    - `qwen3.5:latest` (bigger, better, needs stronger hardware),
    - or a cloud‑backed model from Ollama (e.g. minimax / qwen‑cloud).

> You can also adapt `vault_enrich_with_llm.py` to talk directly to Claude or another provider instead of Ollama; the rest of the pipeline stays the same.

---

## Setup

### 1. Clone this repo

```bash
cd /home/you
git clone https://github.com/bencarkaxhia/obsidian-llm-vault-enricher.git
cd obsidian-llm-vault-enricher
```

(Adjust repo name/URL to whatever you choose.)

### 2. Create a Python virtualenv in your vault (or alongside)

The safest pattern is to keep the Python environment **inside the vault** or next to it, under Linux (`/home`), not under `/mnt/c`. [web:95][web:101]

From inside your vault root:

```bash
cd /home/you/my-vault/my-vault
python3 -m venv .venv
source .venv/bin/activate

pip install pyyaml requests
```

Copy the three scripts into the vault root (or symlink them):

- `vault_tag_link_bootstrap.py`
- `vault_enrich_with_llm.py`
- `vault_apply_links.py`

> The scripts already skip `.venv`, `.git`, and `.obsidian` directories so your environment and Obsidian config won’t be processed.

---

## Configuration

Each script has a `DEFAULT_VAULT_PATH` constant:

```python
DEFAULT_VAULT_PATH = Path("/home/you/my-vault/my-vault")
```

You can either:

- Edit it once to match your vault, or  
- Leave it as is and type the path when prompted.

### Choosing a model (Ollama)

In `vault_enrich_with_qwen.py`, set:

```python
OLLAMA_MODEL = "llama3.1:latest"       # or "qwen3.5:latest", "minimax-m2.5:cloud", etc.
OLLAMA_URL   = "http://localhost:11434/api/chat"
```

Make sure:

- `ollama list` shows your chosen model. [web:107][web:119]
- `ollama run MODEL_NAME` returns answers interactively (to “pre‑warm” the model) before running the script.

You can also limit how many notes to process per run:

```python
MAX_FILES = 20    # first test run
# later: MAX_FILES = None
```

---

## Usage

### Step 0 – Git snapshot (strongly recommended)

Before any bulk edits, initialize Git in your vault:

```bash
cd /home/you/my-vault/my-vault
git init
echo ".obsidian/workspace*" >> .gitignore
echo ".venv" >> .gitignore
git add .
git commit -m "Initial vault snapshot before auto-tag/link"
```

This gives you easy rollback if needed. [web:57]

---

### Step 1 – Bootstrap frontmatter & baseline tags

```bash
source .venv/bin/activate
python3 vault_tag_link_bootstrap.py
```

What this does:

- Walks all `*.md` / `*.txt` under the vault (skipping `.obsidian`, `.venv`, `.git`).
- Ensures each file has YAML frontmatter with:
  - `title`: derived from filename if missing (`ENV_SETUP` → `Env Setup`),
  - `tags`: merged from:
    - filename words (`env`, `setup`),
    - parent folder (`guides`),
    - semantic folder hints (`03-aegis-product` → `aegis`, `product`).
- Writes or updates `vault_manifest.json` with metadata per file.

You can inspect `vault_manifest.json` to see the result:

```json
"03-AEGIS-Product/docs/guides/ENV_SETUP.md": {
  "path": "03-AEGIS-Product/docs/guides/ENV_SETUP.md",
  "title": "Env Setup",
  "tags": [
    "env",
    "setup",
    "guides",
    "docs",
    "aegis",
    "product"
  ],
  "generated_title": true,
  "had_frontmatter": false
}
```

---

### Step 2 – Enrich manifest with model (tags + links)

```bash
python3 vault_enrich_with_llm.py
```

On first run:

- Set `MAX_FILES = 20` in the script to test with a small batch.
- Make sure Ollama is running and the model responds quickly:
  ```bash
  ollama run llama3.1:latest
  ```
- Then run the enrichment script.

What the script does:

- Loads `vault_manifest.json`.
- For each file:
  - Reads a short snippet (first `SNIPPET_CHARS` characters) from the note body.
  - Sends `title`, `tags`, `snippet`, and the list of **other note titles** to the model via Ollama.
  - Asks it to return strict JSON:
    - `extra_tags`: additional tags (single words, no single letters or pure numbers),
    - `link_to_titles`: titles of **existing** notes that should be linked,
    - `concept_nodes`: “hub” notes that should exist (e.g. “LinkedIn Strategy”, “Outbound Playbook”).

- Safely parses the JSON, even if the model wraps it in ```json fences (the script strips those).
- Stores results into the manifest for each note.

After a successful small run, set:

```python
MAX_FILES = None
```

and re‑run to process the whole vault.

---

### Step 3 – Apply concept notes, extra tags, and links

```bash
python3 vault_apply_links.py
```

What this does:

1. **Concept notes**
   - Gathers all `concept_nodes` titles from the manifest.
   - Creates a `00-Concepts/` folder in your vault.
   - For each concept title, creates a note if it doesn’t exist yet, e.g.:

     `00-Concepts/LinkedIn_Strategy.md`:

     ```markdown
     ---
     title: LinkedIn Strategy
     tags: [concept, aegis]
     generated_meta: true
     ---

     Placeholder concept note for LinkedIn Strategy.
     ```

2. **Tags**
   - For each file, merges `extra_tags` into existing frontmatter `tags`, using the same filtering rule (no single letters or pure numbers).

3. **Wiki-links**
   - For each file with `link_to_titles`, appends a `## Related` section at the bottom:

     ```markdown
     ## Related

     - [[Post LinkedIn Launch]]
     - [[ProductHunt Launch Plan]]
     - [[Outbound Playbook]]
     ```

   - The script doesn’t duplicate `## Related` if it already exists; it’s intentionally conservative.

Open Obsidian afterwards and check:

- `00-Concepts` folder with new hub notes.
- Notes now have richer tags and `## Related` link blocks.
- The graph view should show a significantly more connected structure.

---

## Safety and design choices

- **Non‑destructive edits**  
  - We never delete content, only add/update frontmatter and append sections.
  - Raw note bodies remain intact.  

- **Tag hygiene**  
  - Single letters and pure numbers are filtered out (no `a`, `x`, `01` as tags).  

- **Model‑agnostic**  
  - Any Ollama model that can return JSON at `/api/chat` works.[1][2]
  - You can also swap Ollama for Claude or another API by replacing the HTTP call in `vault_enrich_with_llm.py`.

- **Idempotent**  
  - You can re‑run bootstrap and apply scripts as your vault grows; frontmatter merge logic is careful with existing tags.

---

## Customization ideas

- Upgrade the LLM call to Claude if you want richer semantics and can afford the tokens.
- Add a “dry run” mode that prints planned changes before writing files.
- Extend `FOLDER_TAG_HINTS` to map your own folder names → semantic tags.
- Add a second pass that upgrades some `## Related` links into contextual inline `[[links]]` in the body (with regex + manual review).
- Wrap all of this into an Obsidian plugin that talks to your local model or a model API.

---

## Credits & ethos

This project was born from a real need: using Obsidian and local agents (Claude Code, Qwen, etc.) as a **serious knowledge backbone** for a multi‑agent SaaS (AEGIS OS), not just a personal notes toy.

If this helps you:

- Structure your vault,
- Give your local LLMs a better graph to think over,
- Or just saves you from manually linking hundreds of notes,

then it’s already done its job.

Feel free to fork, adapt, improve, and share back with the community.
