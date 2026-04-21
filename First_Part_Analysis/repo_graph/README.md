# SWE-bench Graph Visualizer

Generates a GEXF graph from the SWE-bench repository analysis CSVs and opens it in **Gephi Lite** with layout, appearance, filters, and quality settings applied automatically.

## Prerequisites

- **Windows** (tested on Windows 11)
- **Python 3** on PATH (`python`, `python3`, or `py`)
- **Browser**: Edge, Chrome, or Firefox installed — tested with **Edge only**
- **Internet access** to reach `https://lite.gephi.org`

`pip install selenium` is handled automatically by `run.ps1`.

---

## Quick start

Open PowerShell in the `repo_graph` folder and run:

```powershell
# Radial layout (default)
.\run.ps1

# Hierarchical layout
.\run.ps1 -Layout hierarchical

# Skip GEXF/session regeneration and go straight to Gephi Lite
.\run.ps1 -SkipGenerate
.\run.ps1 -SkipGenerate -Layout hierarchical
```

The script will:
1. Check Python and install `selenium` if missing
2. Generate `swe_bench_graph.gexf` from the analysis CSVs
3. Generate `config/session_<layout>.json` from the JS layout files in `layouts/`
4. Open a browser, load Gephi Lite, and automatically:
   - Upload the GEXF file
   - Set node color → `node_type`, node size → `Degree (dynamic)`
   - Set edge color → `Target nodes`
   - Apply the custom layout script
   - Enable *Connected-closeness* in Layout quality

The browser stays open. Close it or press `Ctrl+C` in the terminal to exit.

### Available layouts

| Name | Description |
|---|---|
| `radial` | Repos at centre, agents/prompts/tools in concentric rings |
| `hierarchical` | Left-to-right columns: repo → agent → prompt/tool |

---

## Filters

Script-based node/edge filters let you restrict the graph to a connected subgraph rooted at a specific repository node.

### Filter files

Each subfolder under `filters/` defines one filter set:

```
filters/
└── repo/
    ├── node.js   ← keep only nodes reachable from REPO_NODE via directed edges (BFS)
    └── edge.js   ← passthrough (Gephi Lite hides edges whose endpoints are hidden)
```

Edit `REPO_NODE` inside `filters/repo/node.js` to target a specific repository:

```javascript
const REPO_NODE = "repo_OpenHands";   // ← change this value
```

The node ID follows the pattern `repo_<SanitisedName>` (spaces → underscores, special characters removed).

### Generating the filter JSON

After editing `node.js`, regenerate the filter JSON:

```powershell
python generate_filters.py
```

This writes `config/filters_repo.json` (and one file per folder found in `filters/`).

### Applying a filter in open_gephi.py

Pass `--filter <folder>` to load the corresponding filter JSON:

```powershell
python open_gephi.py --filter repo
```

Gephi Lite reads `1.0_filters` from `sessionStorage` on page load and applies the script filter automatically.

---

## Exporting a filtered GEXF

After all setup steps are complete the browser can export the filtered graph:

```powershell
# Export to browser's default download folder
python open_gephi.py --filter repo --export

# Export to a specific path and exit automatically
python open_gephi.py --filter repo --export-path .\exports\repo_OpenHands.gexf --no-interaction
```

| Option | Description |
|---|---|
| `--export` | Click Workspace → Export graph file after setup |
| `--export-path PATH` | Save to PATH (implies `--export`; configures browser download dir) |
| `--no-interaction` | Exit automatically after all steps instead of waiting for browser close |

---

## Batch export — generate.ps1

`generate.ps1` iterates over every repository node and produces one filtered GEXF per repo using `open_gephi.py`.

```powershell
# All repos found in config/dataset.json → exports\ folder
.\generate.ps1

# Specific repos only
.\generate.ps1 -Repos "repo_OpenHands,repo_Prometheus"

# Different layout and output directory
.\generate.ps1 -Layout hierarchical -OutputDir ".\exports_hierarchical"

# Overwrite files that already exist (default is to skip them)
.\generate.ps1 -Replace
```

| Parameter | Default | Description |
|---|---|---|
| `-OutputDir` | `.\exports` | Folder where the GEXF files are saved |
| `-Layout` | `radial` | Layout name passed to `open_gephi.py` |
| `-Repos` | *(all)* | Comma-separated repo node IDs to process |
| `-Replace` | *(off)* | Overwrite existing files; skip them when not set |

For each repo the script:
1. Patches `REPO_NODE` in `filters/repo/node.js`
2. Runs `generate_filters.py` to rebuild the filter JSON
3. Runs `open_gephi.py --filter repo --export-path <OutputDir>/<repo>.gexf --no-interaction`

---

## Manual setup (if the script fails)

If the automation does not work (wrong Gephi Lite version, browser driver issues, etc.) you can reproduce the same result by hand.

### 1 — Generate the files

```powershell
python generate_gexf.py
python generate_sessions.py
python generate_filters.py   # optional — only needed if you want filters
```

This produces:
- `swe_bench_graph.gexf`
- `config/session_radial.json`
- `config/session_hierarchical.json`
- `config/filters_repo.json` *(if generate_filters.py was run)*

### 2 — Open Gephi Lite

Go to **https://lite.gephi.org** in your browser.

### 3 — Load the layout script

In the left sidebar: **Layout → Custom layout**, then click **Open code editor**.

Replace the placeholder function with the contents of the layout file you want:

- `layouts/radial_layout.js` — radial layout
- `layouts/hierarchical_layout.js` — hierarchical layout

> **Note:** Keyboard shortcuts (`Ctrl+A`, `Ctrl+V`) do not work inside the editor. Select the text with the mouse and use **right-click → Paste** to insert the code.

Click **Save and run** inside the editor to apply the layout.

### 4 — Upload the graph

Click **Open a local file** in the welcome dialog (or **Workspace → Open**), select `swe_bench_graph.gexf`, and click **Open**.

### 5 — Apply a filter (optional)

Paste the following in the browser console to load the repo filter, then reload the page:

```javascript
const nodeCode = `<contents of filters/repo/node.js (function body only)>`;
const edgeCode = `function edgeFilter(id, attributes, graph) { return true; }`;
sessionStorage.setItem('1.0_filters', JSON.stringify({
  filters: [
    { type: "script", itemType: "nodes", script: ["<<Function", nodeCode, "Function>>"] },
    { type: "script", itemType: "edges", script: ["<<Function", edgeCode, "Function>>"] }
  ]
}));
```

Reload the page — the filter will be active when the graph finishes loading.

### 6 — Set node appearance

In the left sidebar: **Appearance → Nodes**

| Setting | Value |
|---|---|
| Set color from… | `node_type` |
| Set size from… | `Degree (dynamic)` |

### 7 — Set edge appearance

In the left sidebar: **Appearance → Edges**

| Setting | Value |
|---|---|
| Set color from… | `Target nodes` |

### 8 — Apply the custom layout

In the left sidebar: **Layout → Custom layout → Apply**

### 9 — Enable Layout quality

In the left sidebar: **Layout → Layout quality**

Check **Enable Connected-closeness**.

### 10 — Export the graph (optional)

**Workspace → Export graph file** to download the current (filtered) graph as a GEXF file.
