# Public deploy — `https://xiangfengyepan.github.io/TFG_public/repo-graph/`

This folder builds a static, self-contained copy of the SWE-bench graph
visualizer and publishes it as a subfolder of the `TFG_public` GitHub Pages
site, so a single citable URL opens the graph with layout (and optionally a
per-repo filter) already applied.

## Citation URLs

| URL | What it shows |
|---|---|
| `https://xiangfengyepan.github.io/TFG_public/repo-graph/` | Full graph, radial layout |
| `…/repo-graph/?layout=hierarchical` | Full graph, hierarchical layout |
| `…/repo-graph/?repo=repo_OpenHands` | Only nodes reachable from `repo_OpenHands` (radial) |
| `…/repo-graph/?repo=repo_OpenHands&layout=hierarchical` | Same, hierarchical layout |

The `repo` value follows the same `repo_<SanitisedName>` pattern used by the
local filter — see the top-level README for the naming rule.

> **Known limitation (v1):** the deploy applies layout + filter but **not**
> the appearance settings (node colours by `node_type`, node size by degree,
> edge colours by target). Nodes show in gephi-lite's defaults. Adding
> appearance requires baking a `1.0_appearance` sessionStorage entry — see
> "Future work" below.

## How it works

1. **`boot.template.js`** — runs as a classic inline `<script>` in
   gephi-lite's `index.html` **before** the React bundle.
   - Reads `?repo` and `?layout` from the URL.
   - Writes the chosen layout into `sessionStorage['1.0_session']`.
   - Picks the right GEXF: `repo_OpenHands.gexf` for `?repo=repo_OpenHands`,
     or the full `swe_bench_graph.gexf` (from `exports/`) when no `?repo=` is
     given. **Every** GEXF served by the deploy comes from `exports/` — both
     the per-repo subsets and the full graph — so they share the same
     pre-computed layout/styling pipeline.
   - Calls `history.replaceState` to add `?file=./<filename>.gexf`, which
     gephi-lite's `Initialize.tsx` reads on startup to auto-fetch the graph.
2. **`build.ps1`** — regenerates the session JSONs, copies every
   `exports/*.gexf` into gephi-lite's `public/` folder, inlines the session
   JSONs + `repo_*` → filename map into `boot.template.js` → `boot.js`,
   patches `index.html` to load `boot.js`, then runs `npm run build` with
   `BASE_URL=/TFG_public/repo-graph/`.
3. **`github-workflow.yml`** — runs `build.ps1` on every push and publishes
   the output to the `repo-graph/` subfolder of the `gh-pages` branch using
   `peaceiris/actions-gh-pages` with `keep_files: true` (so future siblings
   on `gh-pages` are preserved).

> **Prerequisite**: `build.ps1` expects `exports/*.gexf` to exist. Run
> `.\generate.ps1` first (locally or in CI) to produce them. The CI workflow
> can be extended to call `generate.ps1` as a pre-step if you want fully
> automatic exports — for now they're treated as build inputs.

## One-time setup for `TFG_public`

1. Copy `deploy/github-workflow.yml` from this folder to
   `TFG_public/.github/workflows/deploy-repo-graph.yml`.
2. Push that workflow file to `main`.
3. In `TFG_public` on GitHub: **Settings → Pages** → set
   *Source* = "Deploy from a branch", *Branch* = `gh-pages` (folder `/`).
4. Trigger the workflow once manually (Actions → "Deploy repo-graph" →
   *Run workflow*), or push any change under
   `First_Part_Analysis/repo_graph-master/**`.

The first run creates the `gh-pages` branch. After about 2–4 min the site is
live at `https://xiangfengyepan.github.io/TFG_public/repo-graph/`.

## Local test build

To build without pushing anything:

```powershell
# Clone gephi-lite from upstream (slow first time)
.\deploy\build.ps1

# Or reuse the local clone already in .\gephi-lite\
.\deploy\build.ps1 -GephiSrc ..\gephi-lite

# Custom base path / output directory
.\deploy\build.ps1 -BasePath "/" -OutputDir .\deploy\dist-local
```

Then serve the output to test:

```powershell
# Python's built-in static server
cd deploy\dist
python -m http.server 8000
# open http://localhost:8000/?repo=repo_OpenHands
```

For local testing pass `-BasePath "/"` so asset URLs resolve at the root.

## Future work — baking in appearance (v2)

`open_gephi.py` currently sets appearance via Selenium-driven UI clicks.
gephi-lite stores the result in `sessionStorage['1.0_appearance']`, but the
schema isn't documented anywhere we control. To make the deploy
visually identical to the local run, we'd need to:

1. Run `open_gephi.py` once locally with the desired appearance.
2. Dump `sessionStorage.getItem('1.0_appearance')` to `config/appearance.json`.
3. Inline that JSON into `boot.js` and write it to sessionStorage alongside
   `1.0_session` and `1.0_filters`.

`open_gephi.py` could be extended with a `--dump-state PATH` flag that writes
all relevant sessionStorage keys to a JSON file after setup completes.

## Files in this folder

| File | Purpose |
|---|---|
| `boot.template.js` | Browser-side boot script (template, with placeholders) |
| `build.ps1` | Build driver — generates configs, clones gephi-lite, builds |
| `github-workflow.yml` | GitHub Actions workflow to copy into `TFG_public/.github/workflows/` |
| `README.md` | This file |
| `dist/` *(gitignored)* | Build output |
| `_gephi-lite-src/` *(gitignored)* | Cached gephi-lite clone used by local builds |
