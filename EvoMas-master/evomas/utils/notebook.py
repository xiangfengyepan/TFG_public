"""Build a reproduce-this-run Jupyter notebook.

Lives in `evomas.utils` (not in `api/`) so the CLI, tests, and any other
caller can produce notebooks without dragging in FastAPI. HTTP endpoints
in `api/routers/results.py` and `api/routers/inference.py` are thin
wrappers that stream the dict this module returns as an `.ipynb` blob.

Two public entry points:
- `build_notebook_for_prediction(path)` — from an existing prediction
  JSONL (Results page). Includes the comparative section that diffs
  the re-run against the original `model_patch`.
- `build_notebook_for_inputs(instance_ids, config_data, …)` — from
  raw inputs (Inference page download button + CLI `--instances/--config`).
  No baseline patches, so the comparative section is omitted.
"""
from __future__ import annotations

import json
import pprint
from pathlib import Path
from typing import Any


# Default config-snapshot + instances locations come from evomas.paths so
# the environment-aware `RESULTS_DIR` override is honored without each
# caller having to forward the path explicitly.
from evomas.paths import INSTANCES_PATH as _DEFAULT_INSTANCES_PATH
from evomas.paths import PREDICTION_CONFIGS_DIR as _DEFAULT_CONFIGS_DIR


def build_notebook_for_prediction(
    path: Path,
    *,
    configs_dir: Path | None = None,
    instances_path: Path | None = None,
) -> tuple[str, dict[str, Any]]:
    """Build the reproduce-this-run notebook for a prediction JSONL.
    Shared between the HTTP endpoint and the `evomas notebook` CLI so
    both produce byte-identical .ipynb output. Raises FileNotFoundError
    when `path` doesn't exist.

    `configs_dir` is where this run's config snapshot lives (defaults
    to `<repo>/results/predictions/configs/`); `instances_path` is the
    SWE-bench cache (defaults to `<repo>/swebench_instances.jsonl`).
    """
    if not path.is_file():
        raise FileNotFoundError(f"prediction file not found: {path}")

    cfg_dir = configs_dir if configs_dir is not None else _DEFAULT_CONFIGS_DIR
    inst_path = instances_path if instances_path is not None else _DEFAULT_INSTANCES_PATH

    instance_ids: list[str] = []
    baseline_patches: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            iid = rec.get("instance_id")
            if isinstance(iid, str):
                instance_ids.append(iid)
                bp = rec.get("model_patch")
                if isinstance(bp, str):
                    baseline_patches[iid] = bp

    # Inline the resolved config snapshot so the notebook survives
    # edits/renames/deletions of the source config.
    cfg_snapshot_path = cfg_dir / (path.stem + ".json")
    config_data: dict[str, Any] = {}
    if cfg_snapshot_path.is_file():
        try:
            config_data = json.loads(cfg_snapshot_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass

    run_id = path.stem
    if run_id.startswith("prediction-"):
        run_id = run_id[len("prediction-"):]

    notebook = _build_reproduction_notebook(
        run_id=run_id,
        source_jsonl=str(path),
        config_data=config_data,
        instance_ids=instance_ids,
        baseline_patches=baseline_patches,
        # Server-side absolute path so the notebook works from ~/Downloads;
        # the cell falls back to env override + cwd-relative defaults.
        default_instances_path=str(inst_path),
    )
    return run_id, notebook


def build_notebook_for_inputs(
    *,
    instance_ids: list[str],
    config_data: dict[str, Any],
    run_id_label: str | None = None,
    instances_path: Path | None = None,
) -> tuple[str, dict[str, Any]]:
    """Build a notebook from raw inputs (no prediction file yet).

    Used by the Inference page's download button and the CLI's
    `evomas notebook --instances/--config` mode. The comparative section
    is omitted (there's no baseline `model_patch` to diff against).

    `run_id_label` defaults to `<config-id>-pending` so the on-disk
    `notebook-<run_id>/` folder name is meaningful before any run.
    """
    inst_path = instances_path if instances_path is not None else _DEFAULT_INSTANCES_PATH
    cfg_id = str(config_data.get("id") or "session")
    run_id = run_id_label or f"{cfg_id}-pending"

    notebook = _build_reproduction_notebook(
        run_id=run_id,
        source_jsonl=f"<inference page: {cfg_id} x {len(instance_ids)} instance(s)>",
        config_data=config_data,
        instance_ids=instance_ids,
        baseline_patches=None,
        default_instances_path=str(inst_path),
    )
    return run_id, notebook


def _build_reproduction_notebook(
    *,
    run_id: str,
    source_jsonl: str,
    config_data: dict[str, Any],
    instance_ids: list[str],
    baseline_patches: dict[str, str] | None,
    default_instances_path: str = "swebench_instances.jsonl",
) -> dict[str, Any]:
    """Build the nbformat-v4 dict reproducing one run. Kept as a plain
    dict (no `nbformat` import) — structure is small enough to maintain
    inline."""
    def md(text: str) -> dict[str, Any]:
        return {"cell_type": "markdown", "metadata": {}, "source": text}

    def code(text: str) -> dict[str, Any]:
        return {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": text,
        }

    # pprint, not json.dumps: the CONFIG cell needs Python literals
    # (True/False/None), not JSON (true/false/null) — the latter would
    # NameError when the cell executes.
    cfg_repr = pprint.pformat(config_data, indent=4, width=100, sort_dicts=False)
    ids_repr = pprint.pformat(instance_ids, indent=4, width=100)

    cells: list[dict[str, Any]] = [
        md(
            f"# Reproduce `{run_id}`\n"
            f"\n"
            f"Generated from `{source_jsonl}`. The notebook replays inference + "
            f"evaluation against the exact config snapshot that produced the "
            f"original run, so a re-execution should produce a comparable "
            f"`model_patch` (LLM determinism caveats notwithstanding).\n"
            f"\n"
            f"- **Instances:** {len(instance_ids)}\n"
            f"- **Config id:** `{config_data.get('id', '(unknown)')}`\n"
        ),
        md(
            "## 1. Setup\n"
            "\n"
            "The notebook's `kernelspec.name = \"evomas\"` (see metadata at "
            "the bottom of the file) tells Jupyter / VSCode to auto-pick the "
            "interpreter `setup.ps1` / `setup.sh` registered for "
            "`~/.evomas-venv`. As a safety net the first cell also prepends "
            "the venv's site-packages to `sys.path` — so even if the kernel "
            "falls back to a generic Python 3 (different machine, no "
            "`setup.ps1` run), the evomas imports still resolve. Adjust "
            "`OLLAMA_BASE_URL` if your Ollama daemon isn't on the default "
            "host; `SWEBENCH_API_KEY` is only required by the remote-eval "
            "cell at the bottom.\n"
            "\n"
            "### Picking the kernel in VSCode\n"
            "\n"
            "If VSCode opens the notebook outside the EvoMas workspace "
            "(e.g. straight from `~/Downloads`), it won't auto-resolve the "
            "kernelspec and asks you to **Select Kernel**. Two-tier picker:\n"
            "\n"
            "- **\"Python Environments…\"** lists raw Python interpreters "
            "discovered by the Python extension (system Python, conda envs, "
            "`.venv`/`venv` folders inside workspaces). `~/.evomas-venv` is "
            "outside the conventional discovery paths, so it does NOT show "
            "up here.\n"
            "- **\"Jupyter Kernel…\"** lists registered Jupyter kernelspecs "
            "(`%APPDATA%\\jupyter\\kernels\\*` on Windows, "
            "`~/.local/share/jupyter/kernels/*` on Linux/mac). This is "
            "where the EvoMas one lives — pick **\"Python 3 (EvoMas)\"** "
            "here. VSCode remembers the choice per-notebook so you only "
            "have to do it once.\n"
            "\n"
            "If the entry doesn't appear there: `Ctrl+Shift+P` → "
            "**\"Developer: Reload Window\"** so the Jupyter extension "
            "re-scans kernelspecs, or run `jupyter kernelspec list` to "
            "confirm `evomas` is registered (if not, re-run "
            "`setup.ps1` / `setup.sh`)."
        ),
        code(
            "import os\n"
            "import sys\n"
            "import json\n"
            "import subprocess\n"
            "from pathlib import Path\n"
            "\n"
            "# Defensive sys.path prepend: if the running kernel isn't the\n"
            "# evomas-venv one (e.g. user opened the notebook on a fresh\n"
            "# clone without running setup.ps1, or VSCode picked a generic\n"
            "# Python 3), surface the venv's site-packages so `import\n"
            "# evomas...` still resolves. Skipped when the active sys\n"
            "# already points at the venv.\n"
            "_venv = Path.home() / '.evomas-venv'\n"
            "if _venv.is_dir() and str(_venv) not in sys.executable:\n"
            "    for _sp in (_venv / 'Lib' / 'site-packages',\n"
            "                _venv / 'lib' / 'site-packages'):\n"
            "        if _sp.is_dir() and str(_sp) not in sys.path:\n"
            "            sys.path.insert(0, str(_sp))\n"
            "\n"
            "from evomas.core.workflow.runner import run as run_evomas\n"
            "from evomas.utils.instances import load_instances\n"
            "\n"
            "# Route Python `logging` records to the notebook output so\n"
            "# every `logger.info(...)` call from the agent loop (handoffs,\n"
            "# tool calls, token counts, …) appears inline as the cell\n"
            "# runs. `force=True` overrides any prior basicConfig (e.g.\n"
            "# from a stale kernel) so the format actually takes effect.\n"
            "import logging\n"
            "logging.basicConfig(\n"
            "    level=logging.INFO,\n"
            "    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',\n"
            "    force=True,\n"
            ")\n"
        ),
        md(
            "### Environment variables\n"
            "\n"
            "All run-time configuration the notebook needs lives in this "
            "cell — edit values here rather than chasing them through the "
            "code. Each variable falls back to the value the EvoMas .env "
            "file / shell already has set (via `os.environ.setdefault`), "
            "so the cell is safe to re-run.\n"
            "\n"
            "- **`OLLAMA_BASE_URL`** — where the Ollama daemon serves. "
            "Local default works when `ollama serve` runs on this machine; "
            "swap to e.g. `http://192.168.1.100:11434` for a remote host.\n"
            "- **`SWEBENCH_API_KEY`** — required by the remote-eval cell "
            "(section 5) when running `--remote` against sb-cli. Local "
            "Docker harness runs don't need it.\n"
            "- **`EVOMAS_INSTANCES`** — override the SWE-bench instance "
            "cache location. The next cell already searches sensible "
            "defaults; only set this if your cache is somewhere "
            "non-standard.\n"
            "- **`GOOGLE_API_KEY` / `OPENAI_API_KEY`** — only needed if the "
            "inlined config picks a Gemini / OpenAI model instead of Ollama.\n"
        ),
        code(
            "# Edit these inline OR export them in your shell before\n"
            "# launching Jupyter. `setdefault` means values already in the\n"
            "# environment (e.g. loaded from evomas/.env) win.\n"
            "os.environ.setdefault('OLLAMA_BASE_URL',   'http://127.0.0.1:11434')\n"
            "# os.environ.setdefault('SWEBENCH_API_KEY', 'swb_...')\n"
            "# os.environ.setdefault('EVOMAS_INSTANCES', '/path/to/swebench_instances.jsonl')\n"
            "# os.environ.setdefault('GOOGLE_API_KEY',   '...')\n"
            "# os.environ.setdefault('OPENAI_API_KEY',   '...')\n"
            "\n"
            "# Echo the effective values (mask secrets) so you can verify the cell ran.\n"
            "for _k in ('OLLAMA_BASE_URL', 'SWEBENCH_API_KEY', 'EVOMAS_INSTANCES',\n"
            "           'GOOGLE_API_KEY', 'OPENAI_API_KEY'):\n"
            "    _v = os.environ.get(_k, '')\n"
            "    if not _v:\n"
            "        print(f'  {_k:<18} <unset>')\n"
            "    elif _k.endswith('_API_KEY'):\n"
            "        print(f'  {_k:<18} {_v[:6]}***({len(_v)} chars)')\n"
            "    else:\n"
            "        print(f'  {_k:<18} {_v}')\n"
        ),
        md(
            "## 2. Inlined config\n"
            "\n"
            "Exact resolved config the original run used. Tweak hyperparameters "
            "here if you want to experiment with variations.\n"
            "\n"
            "The cell below the config dict renders a mermaid diagram of the "
            "topology so you can see the agent-graph shape at a glance. The "
            "diagram is regenerated from `CONFIG['edges']` + `CONFIG['agents']` "
            "every time the cell runs, so edits to the dict above are "
            "reflected immediately."
        ),
        code(f"CONFIG = {cfg_repr}"),
        code(
            "from IPython.display import Markdown, display\n"
            "\n"
            "def _topology_mermaid(cfg):\n"
            "    \"\"\"Render the topology as a Mermaid flowchart.\n"
            "\n"
            "    Mirrors what the topology page's cytoscape canvas shows:\n"
            "    virtual START/END boundary nodes, one node per agent with\n"
            "    its class as a second-line label, edges directed left-to-\n"
            "    right. Renders inline in Jupyter Lab + VSCode Jupyter; if\n"
            "    the cell falls back to plain text the source stays readable.\n"
            "    \"\"\"\n"
            "    lines = ['graph LR']\n"
            "    lines.append('    START((START))')\n"
            "    lines.append('    END((END))')\n"
            "    for name, block in (cfg.get('agents') or {}).items():\n"
            "        cls = (block or {}).get('class', '') or ''\n"
            "        label = f'{name}<br/><i>{cls}</i>' if cls else name\n"
            "        # Backticks would break the mermaid parser; strip them\n"
            "        # defensively. Class names never contain them today,\n"
            "        # this is just future-proofing.\n"
            "        label = label.replace('`', '')\n"
            "        lines.append(f'    {name}[\"{label}\"]')\n"
            "    entry = cfg.get('entry') or ''\n"
            "    if entry:\n"
            "        lines.append(f'    START --> {entry}')\n"
            "    for e in (cfg.get('edges') or []):\n"
            "        if isinstance(e, dict) and e.get('from') and e.get('to'):\n"
            "            lines.append(f'    {e[\"from\"]} --> {e[\"to\"]}')\n"
            "    end_field = cfg.get('end')\n"
            "    ends = (\n"
            "        [end_field] if isinstance(end_field, str) and end_field\n"
            "        else list(end_field or [])\n"
            "    )\n"
            "    # Only emit `→ END` for nodes with no outgoing edges (the\n"
            "    # same wiring rule `graph_builder.py` uses). Hub-in-end\n"
            "    # nodes with outgoing edges don't get the static edge.\n"
            "    out_sources = {e.get('from') for e in (cfg.get('edges') or [])\n"
            "                   if isinstance(e, dict)}\n"
            "    for n in ends:\n"
            "        if n and n not in out_sources:\n"
            "            lines.append(f'    {n} --> END')\n"
            "    return '\\n'.join(lines)\n"
            "\n"
            "display(Markdown('```mermaid\\n' + _topology_mermaid(CONFIG) + '\\n```'))\n"
        ),
        md(
            "## 3. Instance ids\n"
            "\n"
            "Looked up against the local `swebench_instances.jsonl` cache "
            "(generated by `evomas instances`). For custom (non-SWE-bench) "
            "instances the dataset row is loaded from disk; for stock ones it "
            "comes from the HuggingFace cache populated by `instances refresh`."
        ),
        code(f"INSTANCE_IDS = {ids_repr}\n"),
        code(
            "# Locate the SWE-bench instance cache. Priority:\n"
            "#   1. $EVOMAS_INSTANCES (explicit override, takes precedence)\n"
            "#   2. The absolute path the API server saw at notebook-gen time\n"
            "#      (works when the user opens the notebook on the same\n"
            "#      machine, even from ~/Downloads / outside the repo)\n"
            "#   3. ./swebench_instances.jsonl  (cwd-relative — works when\n"
            "#      the notebook is opened from the repo root directly)\n"
            "# If none exist, surface a clear hint to regenerate.\n"
            f"_default_instances = r'{default_instances_path}'\n"
            "_candidates = [\n"
            "    os.environ.get('EVOMAS_INSTANCES', ''),\n"
            "    _default_instances,\n"
            "    'swebench_instances.jsonl',\n"
            "]\n"
            "INSTANCES_PATH = next(\n"
            "    (c for c in _candidates if c and Path(c).is_file()),\n"
            "    _default_instances,\n"
            ")\n"
            "print(f'Loading instances from {INSTANCES_PATH}')\n"
            "all_instances = load_instances(INSTANCES_PATH)\n"
            "by_id = {i['instance_id']: i for i in all_instances}\n"
            "missing = [iid for iid in INSTANCE_IDS if iid not in by_id]\n"
            "if missing:\n"
            "    print('Missing from local cache:', missing)\n"
            "    print('Hint: regenerate with `evomas instances refresh`.')\n"
            "selected = [by_id[i] for i in INSTANCE_IDS if i in by_id]\n"
            "print(f'Ready to run {len(selected)} instance(s).')\n"
        ),
        md(
            "## 4. Inference\n"
            "\n"
            "Re-runs the EvoMas workflow for each instance with the inlined "
            "config. All notebook-produced artefacts (prediction JSONL, "
            "evaluation reports, custom-instance sidecar) land under one "
            f"per-run folder at `notebook-{run_id}/` so they stay grouped "
            "together and don't mix with UI/CLI runs in the repo's "
            "`results/` tree."
        ),
        code(
            "from evomas.exceptions.errors import OllamaMemoryError\n"
            "\n"
            f"output_dir = Path('notebook-{run_id}')\n"
            "output_dir.mkdir(parents=True, exist_ok=True)\n"
            f"output_path = output_dir / 'prediction-{run_id}.jsonl'\n"
            "\n"
            "predictions = []\n"
            "with open(output_path, 'w', encoding='utf-8') as out:\n"
            "    for inst in selected:\n"
            "        iid = inst['instance_id']\n"
            "        print(f'--- {iid} ---')\n"
            "        try:\n"
            "            patch = run_evomas(inst, config=CONFIG)\n"
            "        except OllamaMemoryError as exc:\n"
            "            print(f'Ollama OOM; aborting: {exc}')\n"
            "            break\n"
            "        except Exception as exc:\n"
            "            print(f'run failed on {iid}: {exc}')\n"
            "            patch = ''\n"
            "        rec = {\n"
            "            'instance_id': iid,\n"
            "            'model_patch': patch,\n"
            "            'model_name_or_path': 'evomas-notebook',\n"
            "        }\n"
            "        predictions.append(rec)\n"
            "        out.write(json.dumps(rec) + '\\n')\n"
            "print(f'Wrote {len(predictions)} prediction(s) to {output_path}.')\n"
        ),
        md(
            "## 5. Evaluation\n"
            "\n"
            "Two routes depending on the instance type:\n"
            "\n"
            "- **SWE-bench instances** (any subset other than `custom`) → "
            "submitted to the harness via `evomas run evaluation --remote` "
            "(sb-cli, needs `SWEBENCH_API_KEY`). Flip to `--local` in the "
            "cell below if you have the Docker harness installed and want "
            "to avoid the leaderboard upload.\n"
            "- **Custom GitHub repos** (subset/split = `custom`, or any "
            "instance whose id starts with `custom-`) → run through "
            "`scripts/apply_and_test.py`: clone the repo, apply the patch, "
            "run `pytest`. sb-cli rejects these because they lack the "
            "SWE-bench `test_patch` / `FAIL_TO_PASS` / `PASS_TO_PASS` "
            "metadata, so this is the only path that scores them.\n"
            "\n"
            "Subset / split come from the first instance's metadata; the "
            "cell auto-detects the custom case by sniffing `subset`, "
            "`split`, and the instance-id prefix."
        ),
        code(
            "first = selected[0] if selected else None\n"
            "SUBSET = (first or {}).get('subset', 'lite')\n"
            "SPLIT  = (first or {}).get('split',  'dev')\n"
            "_is_custom = (\n"
            "    SUBSET == 'custom'\n"
            "    or SPLIT == 'custom'\n"
            "    or any(iid.startswith('custom-') for iid in INSTANCE_IDS)\n"
            ")\n"
            "print(f'Evaluating against {SUBSET} / {SPLIT}' + (' (custom mode)' if _is_custom else ''))\n"
            "\n"
            "if _is_custom:\n"
            "    # Custom GitHub repos don't have SWE-bench's `test_patch`\n"
            "    # / `FAIL_TO_PASS` / `PASS_TO_PASS` metadata, so sb-cli\n"
            "    # rejects them outright. Instead clone the repo, apply\n"
            "    # the patch, and run `pytest` against the working tree.\n"
            "    # That's what `scripts/apply_and_test.py` does — same\n"
            "    # script the API server routes custom predictions to.\n"
            "    #\n"
            "    # Reusing the SWE-bench instances cache means we have\n"
            "    # `repo` + `base_commit` for each custom id (the\n"
            "    # inference page wrote them when the user added the\n"
            "    # custom row).\n"
            "    repo_root = Path(INSTANCES_PATH).parent\n"
            "    apply_and_test = repo_root / 'scripts' / 'apply_and_test.py'\n"
            "    if not apply_and_test.is_file():\n"
            "        # Fall back to the repo-relative path inferred from\n"
            "        # the evomas package location.\n"
            "        import evomas as _evomas\n"
            "        repo_root = Path(_evomas.__file__).resolve().parents[1]\n"
            "        apply_and_test = repo_root / 'scripts' / 'apply_and_test.py'\n"
            "    # Sidecar + report dir both live under the same\n"
            "    # `notebook-<run_id>/` folder the inference cell created,\n"
            "    # so every artefact for this notebook run stays grouped\n"
            "    # together (and the repo's `results/` tree stays clean).\n"
            "    custom_instances_path = output_dir / 'custom_instances.jsonl'\n"
            "    with custom_instances_path.open('w', encoding='utf-8') as fh:\n"
            "        for inst in selected:\n"
            "            fh.write(json.dumps(inst, ensure_ascii=False) + '\\n')\n"
            "    eval_report_dir = output_dir / 'evaluations'\n"
            "    eval_report_dir.mkdir(parents=True, exist_ok=True)\n"
            "    cmd = [\n"
            "        sys.executable, str(apply_and_test),\n"
            "        '--instances',   str(custom_instances_path),\n"
            "        '--predictions', str(output_path),\n"
            "        '--report-dir',  str(eval_report_dir),\n"
            "        '--run-id',      f'notebook-{SUBSET}-{SPLIT}',\n"
            "        '--model',       'evomas-notebook',\n"
            "    ]\n"
            "else:\n"
            "    # Real SWE-bench instance — defer to the CLI which knows\n"
            "    # how to drive sb-cli or the local Docker harness based\n"
            "    # on --remote / --local. Default to --remote (sb-cli)\n"
            "    # since it doesn't require Docker.\n"
            "    # `--report-dir` lands under the same per-run folder\n"
            "    # the custom-eval branch uses, so the notebook's whole\n"
            "    # output is self-contained at `notebook-<run_id>/`.\n"
            "    eval_report_dir = output_dir / 'evaluations'\n"
            "    eval_report_dir.mkdir(parents=True, exist_ok=True)\n"
            "    cmd = [\n"
            "        'evomas', 'run', 'evaluation',\n"
            "        '--predictions', str(output_path),\n"
            "        '--subset', SUBSET,\n"
            "        '--split',  SPLIT,\n"
            "        '--report-dir', str(eval_report_dir),\n"
            "        '--remote',\n"
            "    ]\n"
            "\n"
            "print('+ ' + ' '.join(cmd))\n"
            "\n"
            "# Stream the harness's stdout line-by-line so progress is\n"
            "# visible in the notebook output as it happens, not just\n"
            "# dumped at the end. `subprocess.run(stdout=PIPE)` buffers\n"
            "# until the process exits — Popen + iter().readline() is\n"
            "# the standard pattern for live streaming.\n"
            "eval_proc = subprocess.Popen(\n"
            "    cmd,\n"
            "    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,\n"
            "    text=True, bufsize=1, encoding='utf-8', errors='replace',\n"
            ")\n"
            "assert eval_proc.stdout is not None\n"
            "for line in eval_proc.stdout:\n"
            "    print(line, end='')\n"
            "eval_proc.wait()\n"
            "print(f'\\n[evaluation finished with exit code {eval_proc.returncode}]')\n"
        ),
    ]

    # Compare-with-original section: only emitted when we have a baseline
    # to diff against (i.e. the notebook was generated from a prediction
    # JSONL on the Results page). Inference-page downloads and CLI
    # `--instances/--config` mode skip this — there's nothing to compare.
    if baseline_patches is not None:
        cells.extend([
            md(
                "## 6. Compare with the original run\n"
                "\n"
                "The notebook keeps the original `model_patch` per instance so you "
                "can diff the new and old runs side-by-side. Different patches with "
                "the same `resolved` verdict often mean both LLM outputs happened "
                "to satisfy the test suite differently."
            ),
            code(
                "import difflib\n"
                "import html as _html\n"
                "from IPython.display import HTML, display\n"
                "\n"
                "BASELINE_PATCHES = "
                + pprint.pformat(baseline_patches, indent=4, width=120) + "\n"
                "\n"
                "\n"
                "def _render_diff(old: str, new: str, title: str) -> str:\n"
                "    \"\"\"Build a GitHub-style colored unified diff. Each line\n"
                "    is escaped + wrapped in a div so longer patches stay\n"
                "    legible (no wrapping) and the +/- colors render even when\n"
                "    Jupyter's CSS doesn't ship a diff theme.\n"
                "    \"\"\"\n"
                "    diff_lines = list(difflib.unified_diff(\n"
                "        old.splitlines(), new.splitlines(),\n"
                "        fromfile='baseline', tofile='new',\n"
                "        lineterm='',\n"
                "    ))\n"
                "    if not diff_lines:\n"
                "        return (f'<div style=\"color:#888;font-style:italic\">'\n"
                "                f'{_html.escape(title)} — identical to baseline'\n"
                "                f'</div>')\n"
                "    rows = []\n"
                "    for line in diff_lines:\n"
                "        esc = _html.escape(line) or '&nbsp;'\n"
                "        if line.startswith('+++') or line.startswith('---'):\n"
                "            color, bg = '#666', 'transparent'\n"
                "        elif line.startswith('@@'):\n"
                "            color, bg = '#a371f7', 'rgba(163,113,247,0.10)'\n"
                "        elif line.startswith('+'):\n"
                "            color, bg = '#2ea043', 'rgba(46,160,67,0.16)'\n"
                "        elif line.startswith('-'):\n"
                "            color, bg = '#f85149', 'rgba(248,81,73,0.16)'\n"
                "        else:\n"
                "            color, bg = 'inherit', 'transparent'\n"
                "        rows.append(\n"
                "            f'<div style=\"color:{color};background:{bg};'\n"
                "            f'white-space:pre;font-family:monospace;'\n"
                "            f'padding:0 6px\">{esc}</div>'\n"
                "        )\n"
                "    return (\n"
                "        f'<div style=\"font-weight:bold;margin-top:8px\">'\n"
                "        f'{_html.escape(title)}</div>'\n"
                "        + ''.join(rows)\n"
                "    )\n"
                "\n"
                "\n"
                "parts = []\n"
                "for rec in predictions:\n"
                "    iid = rec['instance_id']\n"
                "    new_p = rec.get('model_patch') or ''\n"
                "    old_p = BASELINE_PATCHES.get(iid, '')\n"
                "    if new_p.strip() == '' and old_p.strip() == '':\n"
                "        parts.append(\n"
                "            f'<div style=\"color:#888;font-style:italic;margin-top:8px\">'\n"
                "            f'{iid} — both new and baseline patches are empty</div>'\n"
                "        )\n"
                "        continue\n"
                "    parts.append(_render_diff(old_p, new_p, iid))\n"
                "\n"
                "display(HTML(''.join(parts) or '<i>no predictions to compare</i>'))\n"
            ),
        ])

    return {
        "cells": cells,
        "metadata": {
            # `evomas` is the kernelspec that `setup.ps1` registers via
            # `python -m ipykernel install --user --name evomas` against
            # `~/.evomas-venv`. Jupyter / VSCode will pick it
            # automatically on open. If the user's installation doesn't
            # have it, the setup cell's defensive sys.path prepend keeps
            # the imports working under any Python 3 kernel.
            "kernelspec": {
                "name": "evomas",
                "display_name": "Python 3 (EvoMas)",
                "language": "python",
            },
            "language_info": {
                "name": "python",
                "mimetype": "text/x-python",
                "file_extension": ".py",
            },
            # Self-documenting `extra` block so the notebook carries
            # provenance even after re-saves.
            "evomas": {
                "generated_from": source_jsonl,
                "run_id": run_id,
                "instance_count": len(instance_ids),
            },
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
