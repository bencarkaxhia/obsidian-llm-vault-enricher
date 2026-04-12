#!/usr/bin/env python3
"""
Local dashboard for your Obsidian vault enrichment.

Features (v0):
- Start a FastAPI server on a free local port.
- Auto-open the default browser to the dashboard.
- /api/status: show counts from vault_manifest.json and concept notes.
- /api/graph: simple nodes/links JSON built from link_to_titles.
- /: minimal HTML+JS front-end that calls these APIs.

Next steps (later):
- Implement /api/run-pipeline to run bootstrap → enrich → apply on demand.
- Add nicer graph visualization (D3 or a small graph library).
- Add search endpoint.

Run:
  source .venv/bin/activate
  python3 vault_dashboard.py
"""

import json
import socket
import sys
import webbrowser
import subprocess
import time
from pathlib import Path
from typing import Dict, List, Any

import uvicorn
from fastapi import FastAPI
from fastapi import Query, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

# ---------- CONFIG ----------

DEFAULT_VAULT_PATH = Path("/home/beni/my-vault/my-vault")
MANIFEST_FILENAME = "vault_manifest.json"
CONCEPT_NOTE_DIR = "00-Concepts"


# ---------- UTILITIES ----------

def find_free_port() -> int:
    """
    Ask OS for a free port by binding to port 0, then closing the socket.
    This avoids clashes with other services. [web:168][web:177]
    """
    s = socket.socket()
    s.bind(("127.0.0.1", 0))  # 0 = "pick a free port"
    port = s.getsockname()[1]
    s.close()
    return port


def get_vault_path() -> Path:
    """
    For now, just use DEFAULT_VAULT_PATH.
    Later, you can make this configurable via env var or CLI.
    """
    path = DEFAULT_VAULT_PATH.expanduser()
    if not path.exists() or not path.is_dir():
        print(f"ERROR: vault path does not exist or is not a directory: {path}", file=sys.stderr)
        sys.exit(1)
    return path


def load_manifest(vault_root: Path) -> Dict[str, Dict[str, Any]]:
    manifest_path = vault_root / MANIFEST_FILENAME
    if not manifest_path.exists():
        return {}
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    return {}


def count_concept_notes(vault_root: Path) -> int:
    concept_dir = vault_root / CONCEPT_NOTE_DIR
    if not concept_dir.exists() or not concept_dir.is_dir():
        return 0
    return sum(1 for p in concept_dir.glob("*.md") if p.is_file())


# ---------- FASTAPI APP ----------

app = FastAPI(title="Vault Enrichment Dashboard", version="0.1.0")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """
    HTML dashboard with:
    - Status + pipeline control on the left.
    - Search + interactive graph on the right.
    """
    html = """
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>Vault Enrichment Dashboard</title>
      <style>
        body {
          font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
          margin: 0;
          padding: 0;
          background: #f7f6f2;
          color: #222;
        }
        header {
          padding: 1rem 1.5rem;
          background: #01696f;
          color: #fefefe;
        }
        header h1 {
          margin: 0;
          font-size: 1.4rem;
        }
        main {
          display: flex;
          flex-direction: row;
          gap: 1rem;
          padding: 1rem 1.5rem 1.5rem;
        }
        section {
          background: #ffffff;
          border-radius: 8px;
          box-shadow: 0 2px 4px rgba(0,0,0,0.06);
          padding: 1rem;
          flex: 1;
          min-height: 200px;
          display: flex;
          flex-direction: column;
        }
        h2 {
          margin-top: 0;
          font-size: 1.1rem;
        }
        h3 {
          font-size: 1rem;
          margin-bottom: 0.5rem;
        }
        pre {
          font-size: 0.8rem;
          background: #f4f4f4;
          padding: 0.75rem;
          border-radius: 4px;
          max-height: 240px;
          overflow: auto;
        }
        button {
          padding: 0.5rem 1rem;
          border-radius: 4px;
          border: none;
          background: #01696f;
          color: #fff;
          cursor: pointer;
          font-size: 0.9rem;
        }
        button:disabled {
          opacity: 0.5;
          cursor: default;
        }
        #status-list dt {
          font-weight: 600;
        }
        #status-list dd {
          margin: 0 0 0.5rem 0;
        }
        #search-bar {
          display: flex;
          gap: 0.5rem;
          margin-bottom: 0.5rem;
        }
        #search-input {
          flex: 1;
          padding: 0.4rem 0.6rem;
          border-radius: 4px;
          border: 1px solid #ccc;
          font-size: 0.9rem;
        }
        #search-results {
          margin-top: 0.5rem;
          font-size: 0.85rem;
          max-height: 140px;
          overflow: auto;
        }
        #search-results ul {
          list-style: none;
          padding-left: 0;
          margin: 0;
        }
        #search-results li {
          padding: 0.25rem 0;
          border-bottom: 1px solid #eee;
          cursor: pointer;
        }
        #search-results li:hover {
          background: #f0f5f5;
        }
        #search-results .path {
          color: #777;
        }
        #search-results .tags {
          color: #555;
        }
        #graph-container {
          flex: 1;
          border-radius: 6px;
          border: 1px solid #e0e0e0;
          background: #fbfbfb;
          margin-top: 0.75rem;
          display: flex;
        }
        #graph-svg {
          width: 100%;
          height: 360px;
        }
      </style>
      <script src="https://d3js.org/d3.v7.min.js"></script>
    </head>
    <body>
      <header>
        <h1>Vault Enrichment Dashboard</h1>
      </header>
      <div id="note-modal" style="
        position: fixed;
        inset: 0;
        background: rgba(0,0,0,0.4);
        display: none;
        align-items: center;
        justify-content: center;
        z-index: 9999;
      ">
        <div style="
          background: #ffffff;
          border-radius: 8px;
          max-width: 800px;
          width: 90%;
          max-height: 80vh;
          display: flex;
          flex-direction: column;
          box-shadow: 0 8px 30px rgba(0,0,0,0.2);
        ">
          <div style="padding: 0.75rem 1rem; border-bottom: 1px solid #eee; display:flex; justify-content:space-between; align-items:center;">
            <div>
              <div id="note-modal-title" style="font-weight:600;"></div>
              <div id="note-modal-path" style="font-size:0.8rem; color:#777;"></div>
              <div id="note-modal-tags" style="font-size:0.8rem; color:#555; margin-top:0.25rem;"></div>
            </div>
            <button id="note-modal-close" style="background:#ccc; color:#222;">Close</button>
          </div>
          <pre id="note-modal-body" style="
            margin: 0;
            padding: 0.75rem 1rem 1rem;
            font-size: 0.8rem;
            background: #fafafa;
            overflow: auto;
            white-space: pre-wrap;
          "></pre>
        </div>
      </div>
      <main>
        <section>
          <h2>Status</h2>
          <p>This shows a summary of your current vault manifest and concept notes.</p>
          <dl id="status-list">
            <dt>Total notes</dt><dd id="status-total">...</dd>
            <dt>Notes with extra tags</dt><dd id="status-extra-tags">...</dd>
            <dt>Notes with links</dt><dd id="status-links">...</dd>
            <dt>Concept notes</dt><dd id="status-concepts">...</dd>
          </dl>
          <button id="refresh-status">Refresh status</button>
          <hr>
          <h3>Run pipeline</h3>
          <p>Runs: bootstrap → enrich → apply on your vault. This may take a while.</p>
          <button id="run-pipeline">Run pipeline</button>
          <pre id="pipeline-log" style="margin-top:0.5rem;"></pre>
        </section>
        <section>
          <h2>Search & Graph</h2>
          <div id="search-bar">
            <input id="search-input" type="text" placeholder="Search notes by title or tag..." />
            <button id="search-button">Search</button>
          </div>
            <div id="search-results">
            <strong>Results</strong>
            <ul id="search-results-list"></ul>
          </div>
          <div style="margin-top:0.5rem; display:flex; justify-content:space-between; align-items:center;">
            <span style="font-size:0.85rem; color:#555;">Graph view</span>
            <button id="download-graph">Download JSON</button>
          </div>
          <div id="graph-container">
            <svg id="graph-svg"></svg>
          </div>
        </section>
      </main>
      <script>
        console.log("Dashboard script loaded");

        let currentGraph = { nodes: [], links: [] };
        let simulation = null;
        let svg = null;
        let graphGroup = null;
        let nodeSelection = null;
        let linkSelection = null;

        async function fetchStatus() {
          try {
            const res = await fetch('/api/status');
            if (!res.ok) throw new Error('HTTP ' + res.status);
            const data = await res.json();
            document.getElementById('status-total').textContent = data.total_notes;
            document.getElementById('status-extra-tags').textContent = data.notes_with_extra_tags;
            document.getElementById('status-links').textContent = data.notes_with_links;
            document.getElementById('status-concepts').textContent = data.concept_notes;
          } catch (e) {
            console.error('fetchStatus error', e);
            alert('Failed to load status. See console for details.');
          }
        }

        async function fetchGraph() {
          try {
            const res = await fetch('/api/graph');
            if (!res.ok) throw new Error('HTTP ' + res.status);
            const data = await res.json();
            currentGraph = data;
            renderGraph(data);
          } catch (e) {
            console.error('fetchGraph error', e);
            alert('Failed to load graph. See console for details.');
          }
        }

        async function runPipeline() {
          const btn = document.getElementById('run-pipeline');
          const logEl = document.getElementById('pipeline-log');
          btn.disabled = true;
          logEl.textContent = "Running pipeline...\\n";
          try {
            const res = await fetch('/api/run-pipeline', { method: 'POST' });
            if (!res.ok) throw new Error('HTTP ' + res.status);
            const data = await res.json();
            const statusLine = `success=${data.success}, duration=${data.duration_seconds}s`;
            const logText = (data.logs || []).join("\\n");
            logEl.textContent = statusLine + "\\n\\n" + logText;
            if (data.success) {
              fetchStatus();
              fetchGraph();
            }
          } catch (e) {
            console.error('runPipeline error', e);
            logEl.textContent = "Pipeline failed to start or crashed. See console.";
          } finally {
            btn.disabled = false;
          }
        }

        async function runSearch() {
          const q = document.getElementById('search-input').value.trim();
          const listEl = document.getElementById('search-results-list');
          listEl.innerHTML = "";
          if (!q) {
            return;
          }
          try {
            const res = await fetch('/api/search?q=' + encodeURIComponent(q));
            if (!res.ok) throw new Error('HTTP ' + res.status);
            const data = await res.json();
            const results = data.results || [];
            if (!results.length) {
              listEl.innerHTML = "<li>No results</li>";
              return;
            }
            results.forEach(item => {
              const li = document.createElement('li');
              li.dataset.title = item.title;
              li.dataset.path = item.path;
              li.innerHTML =
                "<strong>" + item.title + "</strong><br>" +
                "<span class='path'>" + item.path + "</span><br>" +
                "<span class='tags'>" + (item.tags || []).map(t => "#" + t).join(" ") + "</span>";
              li.addEventListener('click', () => {
                highlightNode(item.title);
                loadNoteDetails(item.path, item.title);
              });
              listEl.appendChild(li);
            });
          } catch (e) {
            console.error('runSearch error', e);
            listEl.innerHTML = "<li>Search failed. See console.</li>";
          }
        }

        function renderGraph(data) {
          if (!svg) {
            svg = d3.select("#graph-svg");
          }
          svg.selectAll("*").remove();

          const width = svg.node().clientWidth || 600;
          const height = svg.node().clientHeight || 360;
          svg.attr("viewBox", `0 0 ${width} ${height}`);

          const nodes = data.nodes.map(d => Object.assign({}, d));
          const links = data.links.map(d => Object.assign({}, d));

          // Container group for zoom/pan
          graphGroup = svg.append("g");

          const linkLayer = graphGroup.append("g")
            .attr("stroke", "#ccc")
            .attr("stroke-opacity", 0.7);

          const nodeLayer = graphGroup.append("g")
            .attr("stroke", "#fff")
            .attr("stroke-width", 1.5);

          linkSelection = linkLayer.selectAll("line")
            .data(links)
            .enter().append("line")
            .attr("stroke-width", 1);

          const color = d3.scaleOrdinal(d3.schemeCategory10);

          nodeSelection = nodeLayer.selectAll("circle")
            .data(nodes)
            .enter().append("circle")
            .attr("r", 6)
            .attr("fill", d => color((d.tags && d.tags[0]) || "default"))
            .on("click", (event, d) => {
              highlightNode(d.id);
              // each node has path from backend graph JSON
              if (d.path) {
                loadNoteDetails(d.path, d.id);
              }
            })
            .call(d3.drag()
              .on("start", (event, d) => {
                if (!event.active) simulation.alphaTarget(0.3).restart();
                d.fx = d.x;
                d.fy = d.y;
              })
              .on("drag", (event, d) => {
                d.fx = event.x;
                d.fy = event.y;
              })
              .on("end", (event, d) => {
                if (!event.active) simulation.alphaTarget(0);
                d.fx = null;
                d.fy = null;
              })
            );

          nodeSelection.append("title").text(d => d.id);

          simulation = d3.forceSimulation(nodes)
            .force("link", d3.forceLink(links).id(d => d.id).distance(70))
            .force("charge", d3.forceManyBody().strength(-80))
            .force("center", d3.forceCenter(width / 2, height / 2))
            .force("collision", d3.forceCollide().radius(20));

          simulation.on("tick", () => {
            linkSelection
              .attr("x1", d => d.source.x)
              .attr("y1", d => d.source.y)
              .attr("x2", d => d.target.x)
              .attr("y2", d => d.target.y);

            nodeLayer.selectAll("circle")
              .attr("cx", d => d.x)
              .attr("cy", d => d.y);
          });

          // Zoom + pan
          const zoom = d3.zoom()
            .scaleExtent([0.25, 4])
            .on("zoom", (event) => {
              graphGroup.attr("transform", event.transform);
            });

          svg.call(zoom);
        }

        function highlightNode(title) {
          if (!nodeSelection) return;
          nodeSelection.attr("stroke", "#fff").attr("stroke-width", 1.5);
          nodeSelection
            .filter(d => d.id === title)
            .attr("stroke", "#ff9800")
            .attr("stroke-width", 3);
        }
        
        function downloadGraphJson() {
          if (!currentGraph || !currentGraph.nodes || !currentGraph.links) {
            alert("Graph data not loaded yet.");
            return;
          }
          const blob = new Blob(
            [JSON.stringify(currentGraph, null, 2)],
            { type: "application/json" }
          );
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          const ts = new Date().toISOString().replace(/[:.]/g, "-");
          a.download = "vault-graph-" + ts + ".json";
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
        }
        
        async function loadNoteDetails(path, titleOverride) {
          try {
            const res = await fetch('/api/note?path=' + encodeURIComponent(path));
            if (!res.ok) {
              const text = await res.text().catch(() => "");
              throw new Error('HTTP ' + res.status + ' ' + text);
            }
            const data = await res.json();

            const title = titleOverride || data.title;
            const tags = data.tags || [];
            const extraTags = data.extra_tags || [];

            document.getElementById('note-modal-title').textContent = title;
            document.getElementById('note-modal-path').textContent = data.path;

            const allTags = [...tags, ...extraTags];
            const tagsText = allTags.length
              ? allTags.map(t => "#" + t).join(" ")
              : "(no tags)";
            document.getElementById('note-modal-tags').textContent = tagsText;

            document.getElementById('note-modal-body').textContent = data.body || "";

            const modal = document.getElementById('note-modal');
            modal.style.display = "flex";
          } catch (e) {
            console.error('loadNoteDetails error', e);
            alert('Failed to load note. See console for details.');
          }
        }

        function closeNoteModal() {
          const modal = document.getElementById('note-modal');
          modal.style.display = "none";
        }

        document.addEventListener('DOMContentLoaded', () => {
          console.log("DOM ready, wiring buttons");
          const statusBtn = document.getElementById('refresh-status');
          const pipelineBtn = document.getElementById('run-pipeline');
          const searchBtn = document.getElementById('search-button');
          const searchInput = document.getElementById('search-input');
          const downloadBtn = document.getElementById('download-graph');
          const modalCloseBtn = document.getElementById('note-modal-close');
          const modal = document.getElementById('note-modal');  // <-- THIS LINE MUST EXIST

          statusBtn.addEventListener('click', fetchStatus);
          pipelineBtn.addEventListener('click', runPipeline);
          searchBtn.addEventListener('click', runSearch);
          searchInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
              runSearch();
            }
          });
          downloadBtn.addEventListener('click', downloadGraphJson);

          modalCloseBtn.addEventListener('click', closeNoteModal);
          modal.addEventListener('click', (e) => {
            if (e.target === modal) {
              closeNoteModal();
            }
          });

          // initial load
          fetchStatus();
          fetchGraph();
        });
      </script>
    </body>
    </html>
    """
    return html


@app.get("/api/status", response_class=JSONResponse)
def api_status() -> Dict[str, Any]:
    """
    Return a simple summary of the vault based on the manifest and concept notes.
    """
    vault_root = get_vault_path()
    manifest = load_manifest(vault_root)

    total_notes = len(manifest)
    notes_with_extra_tags = 0
    notes_with_links = 0

    for meta in manifest.values():
        if meta.get("extra_tags"):
            notes_with_extra_tags += 1
        if meta.get("link_to_titles"):
            notes_with_links += 1

    concept_notes = count_concept_notes(vault_root)

    return {
        "total_notes": total_notes,
        "notes_with_extra_tags": notes_with_extra_tags,
        "notes_with_links": notes_with_links,
        "concept_notes": concept_notes,
    }


@app.get("/api/graph", response_class=JSONResponse)
def api_graph() -> Dict[str, Any]:
    """
    Build a simple nodes/links graph from the manifest:
    - nodes: each note with (id=title, path, tags)
    - links: edges from title -> titles in link_to_titles
    Only include links whose source and target both exist as node IDs.
    """
    vault_root = get_vault_path()
    manifest = load_manifest(vault_root)

    # Build nodes
    nodes: List[Dict[str, Any]] = []
    for path_str, meta in manifest.items():
        title = meta.get("title") or path_str
        tags = meta.get("tags") or []
        nodes.append({
            "id": title,
            "path": path_str,
            "tags": tags,
        })

    # Index node IDs for fast lookup
    node_ids = {n["id"] for n in nodes}

    # Build links, but only keep those where both ends exist
    links: List[Dict[str, str]] = []
    for meta in manifest.values():
        src_title = meta.get("title")
        if not isinstance(src_title, str):
            continue
        if src_title not in node_ids:
            continue
        link_titles = meta.get("link_to_titles") or []
        for tgt in link_titles:
            if not isinstance(tgt, str):
                continue
            if tgt not in node_ids:
                continue
            links.append({
                "source": src_title,
                "target": tgt,
            })

    return {"nodes": nodes, "links": links}

# Search endpoint
@app.get("/api/search", response_class=JSONResponse)
def api_search(q: str = Query("", alias="q")) -> Dict[str, Any]:
    """
    Simple search over title + tags + extra_tags.

    - q: substring match (case-insensitive).
    - Returns at most 50 results, sorted by degree (number of links).
    """
    vault_root = get_vault_path()
    manifest = load_manifest(vault_root)

    q_norm = (q or "").strip().lower()
    results: List[Dict[str, Any]] = []

    for path_str, meta in manifest.items():
        title = meta.get("title") or path_str
        tags = meta.get("tags") or []
        extra_tags = meta.get("extra_tags") or []
        all_tags = tags + extra_tags
        link_titles = meta.get("link_to_titles") or []

        haystack = " ".join([title] + [str(t) for t in all_tags]).lower()
        if q_norm and q_norm not in haystack:
            continue

        results.append(
            {
                "title": title,
                "path": path_str,
                "tags": list(dict.fromkeys(all_tags)),  # dedupe, preserve order
                "degree": len(link_titles),
            }
        )

    # sort by degree desc, then title
    results.sort(key=lambda r: (-r["degree"], r["title"]))
    return {"query": q, "results": results[:50]}

# Note details endpoint
@app.get("/api/note", response_class=JSONResponse)
def api_note(path: str = Query(..., alias="path")) -> Dict[str, Any]:
    """
    Return metadata + content for a single note identified by its relative path.

    This version is deliberately simple:
    - It returns the full file content in 'body' (including frontmatter).
    - It does not call split_frontmatter to avoid NameError issues.
    """
    vault_root = get_vault_path()
    manifest = load_manifest(vault_root)

    if path not in manifest:
        raise HTTPException(status_code=404, detail="Note not found in manifest")

    meta = manifest[path]
    title = meta.get("title") or path
    tags = meta.get("tags") or []
    extra_tags = meta.get("extra_tags") or []

    file_path = vault_root / path
    if not file_path.exists() or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Note file not found on disk")

    body = file_path.read_text(encoding="utf-8")

    return {
        "title": title,
        "path": path,
        "tags": tags,
        "extra_tags": extra_tags,
        "body": body,
    }

# Endpoint to run the pipeline Tag -> Enrich -> Apply
@app.post("/api/run-pipeline", response_class=JSONResponse)
def api_run_pipeline() -> Dict[str, Any]:
    """
    Run the full pipeline (bootstrap -> enrich -> apply) synchronously and
    return combined logs + basic status.

    This is blocking: the HTTP request stays open until the three scripts finish.
    For a local CLI-style dashboard that's fine as a first step.
    """
    vault_root = get_vault_path()
    start_ts = time.time()
    logs: List[str] = []
    success = True

    def run_step(label: str, cmd: List[str]) -> int:
        nonlocal logs, success
        logs.append(f"$ {' '.join(cmd)}  # {label}")
        try:
            result = subprocess.run(
                cmd,
                cwd=str(vault_root),
                text=True,
                capture_output=True,   # capture stdout+stderr so we can show in UI [web:188][web:194]
            )
        except Exception as e:
            logs.append(f"[{label}] FAILED to start: {e}")
            success = False
            return -1

        if result.stdout:
            logs.append(result.stdout.strip())
        if result.stderr:
            logs.append("[stderr]")
            logs.append(result.stderr.strip())

        if result.returncode != 0:
            logs.append(f"[{label}] exited with code {result.returncode}")
            success = False
        else:
            logs.append(f"[{label}] completed successfully.")
        logs.append("")  # blank line between steps
        return result.returncode

    # 1) Bootstrap    
    run_step("bootstrap", ["python3", "vault_tag_link_bootstrap.py"])

    # 2) Enrich (only if previous step succeeded)
    if success:        
        run_step("enrich", ["python3", "vault_enrich_with_llm.py"])

    # 3) Apply (only if previous step(s) succeeded)
    if success:        
        run_step("apply", ["python3", "vault_apply_links.py"])
        
    duration = time.time() - start_ts
    return {
        "success": success,
        "duration_seconds": round(duration, 2),
        "logs": logs,
    }


# ---------- ENTRY POINT ----------

if __name__ == "__main__":
    vault_root = get_vault_path()
    port = find_free_port()
    url = f"http://127.0.0.1:{port}"
    print(f"Vault Dashboard starting for {vault_root}")
    print(f"Serving at {url}")

    # Open browser after server starts; webbrowser will open the URL in default browser. [web:173][web:179]
    webbrowser.open(url)

    uvicorn.run(
        "vault_dashboard:app",
        host="127.0.0.1",
        port=port,
        log_level="info",
        reload=False,
    )
