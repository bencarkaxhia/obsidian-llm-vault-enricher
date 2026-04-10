# Contributing to Obsidian LLM Vault Enricher

Thanks for your interest in improving this project! ❤️  
The goal is to keep the toolchain **small, understandable, and safe** for people who want to enrich their Obsidian vaults with tags and links using local or cloud LLMs.

## Code of conduct

- Be respectful and constructive.
- Assume good intent.
- No harassment, hate speech, or personal attacks.

If something makes you uncomfortable, open an issue or reach out via GitHub.

---

## How the project is structured

- `scripts/vault_tag_link_bootstrap.py`  
  Pass 1: normalize YAML frontmatter and derive baseline tags from filenames + folder names, then write `vault_manifest.json`.

- `scripts/vault_enrich_with_llm.py`  
  Pass 2: call an LLM via Ollama to enrich each note with:
  - `extra_tags`
  - `link_to_titles`
  - `concept_nodes`  
  and store them in the manifest.

- `scripts/vault_apply_links.py`  
  Pass 3: apply the manifest back into the vault:
  - create concept notes,
  - merge `extra_tags` into frontmatter,
  - append a `## Related` block with `[[links]]`.

- `README.md`  
  Explains setup, configuration, and usage.

---

## Development setup

1. Clone the repo:

   ```bash
   git clone https://github.com/bencarkaxhia/obsidian-llm-vault-enricher.git
   cd obsidian-llm-vault-enricher
   ```

2. Create a virtualenv:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install pyyaml requests
   ```

3. Point the scripts to a **test vault**, not your main one (or use Git snapshots on your real vault).

4. Configure Ollama:

   - Install Ollama and pull a model:
     ```bash
     ollama pull llama3.1:latest
     ```
   - Test:
     ```bash
     ollama run llama3.1:latest
     ```

5. Run scripts in order on the test vault:

   ```bash
   python3 scripts/vault_tag_link_bootstrap.py
   python3 scripts/vault_enrich_with_llm.py
   python3 scripts/vault_apply_links.py
   ```

---

## Types of contributions welcome

- **Prompts & model support**
  - Better system prompts for enrichment.
  - Config presets for different models (Qwen, Llama, Minimax, Claude API, etc.).
  - Provider adapters (Anthropic, OpenAI, others) in addition to Ollama.

- **Safety & UX**
  - Dry‑run / diff mode that prints planned changes instead of writing files.
  - More granular include/exclude filters (by folder, glob, tag).
  - Better error messages around timeouts, invalid JSON, or missing models.

- **Features**
  - Inline link injection (turn keywords in body into `[[links]]` safely).
  - Reverse index views or reports from `vault_manifest.json`.
  - Optional Obsidian plugin wrapper that calls these scripts.

- **Docs**
  - Example vault walkthroughs.
  - Tips for large vaults (timeouts, batching, hardware).
  - Translations of the README.

---

## How to contribute

### 1. Issues

If you find a bug or have an idea:

1. Check if there’s already an issue open.
2. If not, open a new issue and include:
   - What you ran (commands, model).
   - What you expected.
   - What actually happened (logs, stack trace, screenshots).

### 2. Pull requests

1. Fork the repo and create a feature branch:

   ```bash
   git checkout -b feature/my-improvement
   ```

2. Make your changes:
   - Keep scripts small and readable.
   - Avoid adding heavy dependencies.
   - Preserve backwards compatibility when possible.

3. Run basic checks:
   - `python -m compileall scripts` (or your preferred lint/format).
   - Test on a small sample vault.

4. Commit with a clear message:

   ```bash
   git commit -m "Improve JSON parsing for fenced LLM outputs"
   ```

5. Push and open a PR against `main` with:
   - A short summary of the change.
   - How you tested it.
   - Any potential breaking changes or caveats.

---

## Guidelines & design philosophy

- **Non‑destructive first**  
  Scripts should prefer adding/annotating, not deleting or rewriting large chunks of content.

- **Model‑agnostic**  
  Keep enrichment logic able to work with any LLM endpoint that can return JSON (Ollama, Claude, etc.).

- **Readable over clever**  
  The code should be easy for others to copy, adapt, and extend in their own vault workflows.

- **Vault‑friendly**  
  Respect Obsidian’s conventions:
  - Don’t touch `.obsidian/`.
  - Don’t modify `.git/` or `.venv/`.
  - Be careful with filenames and paths (no breaking of existing links).

---

## License

By contributing, you agree that your contributions will be licensed under the same MIT license as the rest of the project.
