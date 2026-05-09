# SWE-bench Graph Visualizer

Generates a GEXF graph from the SWE-bench repository analysis CSVs and opens it in **Gephi Lite** (running locally) with layout, appearance, filters, and quality settings applied automatically.

## Prerequisites

- **Windows** (tested on Windows 11)
- **Python 3** on PATH (`python`, `python3`, or `py`)
- **Node.js 18+** on PATH — required to run the local Gephi Lite dev server
- **Browser**: Edge, Chrome, or Firefox installed — tested with **Edge only**
- **gephi-lite** cloned into `repo_graph/gephi-lite/` with dependencies installed:

```powershell
cd gephi-lite
npm install
```

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
4. Start the local Gephi Lite dev server (`http://localhost:5173/gephi-lite/`)
5. Open a browser, load Gephi Lite, and automatically:
   - Upload the GEXF file
   - Set node color → `node_type`, node size → `Degree (dynamic)`
   - Set edge color → `Target nodes`
   - Apply the custom layout script
   - Enable *Connected-closeness* in Layout quality

The browser stays open. Close it or press `Ctrl+C` in the terminal to exit. The dev server is stopped automatically when the script exits.

### Available layouts

| Name | Description |
|---|---|
| `radial` | Repos at centre, agents/prompts/tools in concentric rings |
| `hierarchical` | Left-to-right columns: repo → agent → prompt/tool |

### Pre-starting the dev server

If you plan to run `open_gephi.py` multiple times (e.g. batch export), start the dev server once manually to avoid the startup wait on every run:

```powershell
# Terminal 1 — keep this running
cd gephi-lite
npm run start

# Terminal 2 — use --local without --start-server
python open_gephi.py --local --filter repo --export
```

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
python open_gephi.py --local --filter repo
```

Gephi Lite reads `1.0_filters` from `sessionStorage` on page load and applies the script filter automatically.

---

## Exporting a filtered GEXF

After all setup steps are complete the browser can export the filtered graph:

```powershell
# Export GEXF to browser's default download folder
python open_gephi.py --local --filter repo --export

# Export GEXF to a specific path and exit automatically
python open_gephi.py --local --filter repo --export-path .\exports\repo_OpenHands.gexf --no-interaction

# Export PNG snapshot (2480×3508 px) to browser's default download folder
python open_gephi.py --local --filter repo --export-png

# Export PNG to a specific path and exit automatically
python open_gephi.py --local --filter repo --export-png-path .\exports\repo_OpenHands.png --no-interaction

# Export both GEXF and PNG in one run
python open_gephi.py --local --filter repo `
    --export-path .\exports\repo_OpenHands.gexf `
    --export-png-path .\exports\repo_OpenHands.png `
    --no-interaction
```

| Option | Description |
|---|---|
| `--local` | Use the local dev server at `http://localhost:5173/gephi-lite/` |
| `--local-port PORT` | Override the dev server port (default: `5173`) |
| `--start-server` | Auto-start `npm run start` in `gephi-lite/` before opening the browser |
| `--gephi-dir PATH` | Path to the cloned gephi-lite repo (default: `./gephi-lite`) |
| `--export` | Click Workspace → Export graph file after setup |
| `--export-path PATH` | Save GEXF to PATH (implies `--export`; configures browser download dir) |
| `--export-png` | Click Workspace → Export image after setup |
| `--export-png-path PATH` | Save PNG to PATH (implies `--export-png`; configures browser download dir) |
| `--png-width PX` | PNG export width in pixels (default: `2480`) |
| `--png-height PX` | PNG export height in pixels (default: `3508`) |
| `--png-layout NAME` | Layout applied before PNG export (default: same as `--layout`). Re-applies layout in the same browser session without restarting. |
| `--no-interaction` | Exit automatically after all steps instead of waiting for browser close |

---

## Batch export — generate.ps1

`generate.ps1` iterates over every repository node and produces one filtered GEXF (and optionally PNG) per repo using `open_gephi.py`.

> **Note:** Start the local dev server manually before running `generate.ps1` (see [Pre-starting the dev server](#pre-starting-the-dev-server)), then pass `--local` via the `-OpenGephiArgs` parameter if you have customised the script. The default invocation in `generate.ps1` uses the remote URL; edit line 122 to add `--local` if needed.

```powershell
# All repos found in config/dataset.json → exports\ folder
.\generate.ps1

# Specific repos only
.\generate.ps1 -Repos "repo_OpenHands,repo_Prometheus"

# Different layout and output directory
.\generate.ps1 -Layout hierarchical -OutputDir ".\exports_hierarchical"

# Overwrite files that already exist (default is to skip them)
.\generate.ps1 -Replace

# Also export a PNG snapshot (2480×3508 px) for each repo
.\generate.ps1 -ExportPng

# PNG with custom dimensions
.\generate.ps1 -ExportPng -PngWidth 1920 -PngHeight 1080

# Full example: specific repos, replace existing, GEXF + PNG
.\generate.ps1 -Repos "repo_OpenHands,repo_Prometheus" -Replace -ExportPng
```

| Parameter | Default | Description |
|---|---|---|
| `-OutputDir` | `.\exports` | Folder where the exported files are saved |
| `-Layout` | `radial` (or `hierarchical` when `-ExportPng`) | Layout name passed to `open_gephi.py` |
| `-Repos` | *(all)* | Comma-separated repo node IDs to process |
| `-Replace` | *(off)* | Overwrite existing files; skip them when not set |
| `-ExportPng` | *(off)* | Also export a PNG snapshot for each repo |
| `-PngWidth` | `2480` | PNG export width in pixels |
| `-PngHeight` | `3508` | PNG export height in pixels |
| `-PngLayout` | `hierarchical` | Layout name used for the PNG snapshot |

> **Layout auto-selection:** when `-ExportPng` is set without an explicit `-Layout`, the script defaults to `hierarchical` instead of `radial`. Pass `-Layout radial` to override.

For each repo the script:
1. Patches `REPO_NODE` in `filters/repo/node.js`
2. Runs `generate_filters.py` to rebuild the filter JSON
3. Runs `open_gephi.py --filter repo --export-path <OutputDir>/<repo>.gexf [--export-png-path <OutputDir>/<repo>.png] --no-interaction`

---

## Manual setup (if the script fails)

If the automation does not work (wrong Gephi Lite version, browser driver issues, etc.) you can reproduce the same result by hand.

### 1 — Start the local dev server

```powershell
cd gephi-lite
npm run start
```

Wait until the terminal shows `Local: http://localhost:5173/gephi-lite/`.

### 2 — Generate the files

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

### 3 — Open Gephi Lite

Go to **http://localhost:5173/gephi-lite/** in your browser.

### 4 — Load the layout script

In the left sidebar: **Layout → Custom layout**, then click **Open code editor**.

Replace the placeholder function with the contents of the layout file you want:

- `layouts/radial_layout.js` — radial layout
- `layouts/hierarchical_layout.js` — hierarchical layout
- `layouts/repo_layout.js` — single-repo fan layout (for per-repo PNG exports)

> **Note:** Keyboard shortcuts (`Ctrl+A`, `Ctrl+V`) do not work inside the editor. Select the text with the mouse and use **right-click → Paste** to insert the code.

Click **Save and run** inside the editor to apply the layout.

### 5 — Upload the graph

Click **Open a local file** in the welcome dialog (or **Workspace → Open**), select `swe_bench_graph.gexf`, and click **Open**.

### 6 — Apply a filter (optional)

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

### 7 — Set node appearance

In the left sidebar: **Appearance → Nodes**

| Setting | Value |
|---|---|
| Set color from… | `node_type` |
| Set size from… | `Degree (dynamic)` |

### 8 — Set edge appearance

In the left sidebar: **Appearance → Edges**

| Setting | Value |
|---|---|
| Set color from… | `Target nodes` |

### 9 — Apply the custom layout

In the left sidebar: **Layout → Custom layout → Apply**

### 10 — Enable Layout quality

In the left sidebar: **Layout → Layout quality**

Check **Enable Connected-closeness**.

### 11 — Export the graph (optional)

- **Workspace → Export graph file** — downloads the current (filtered) graph as a GEXF file.
- **Workspace → Export image** — opens a dialog to export a PNG snapshot; set width/height (e.g. 2480×3508) and click **Save**.
