# EvoMas

Evolutionary multi-agent framework for [SWE-bench](https://www.swebench.com/)–style automated program repair.

## Prerequisites

| Tool | Why | Where to get it |
|---|---|---|
| Windows 11 / 10 | The project targets Windows; the `start_*.ps1` and `setup.ps1` scripts assume PowerShell. | — |
| Python 3.12+ (3.12.6 is the dev baseline) | Runs the agent framework and the FastAPI backend. | https://www.python.org/downloads/ |
| Ollama | Hosts the local LLM each agent calls. | https://ollama.com/download |
| Docker Desktop | Required for SWE-bench evaluation (the harness runs each instance in a container). Not needed for inference-only flows. | https://www.docker.com/products/docker-desktop/ |
| Node.js 18+ | Builds and serves the Angular frontend. | https://nodejs.org/ |

## Install

```powershell
.\setup.ps1
```

`setup.ps1` checks for the prerequisites above, creates a fresh venv at `evomas\venv`, runs `pip install -e .` (which reads `pyproject.toml` for dependencies + registers the `evomas` console command), and appends an `evomas` function to your PowerShell `$PROFILE` so the command is reachable from any directory.

Open a new PowerShell window after running setup so the profile change takes effect, then verify:

```powershell
evomas --help
```

### Setup fails or imports break after an upgrade

`setup.ps1` is intentionally non-destructive — it reuses any existing `evomas\venv`. If a previous install left the venv in a broken state (missing packages, mismatched versions, `ModuleNotFoundError`), delete it manually and rerun:

```powershell
Remove-Item -Recurse -Force .\evomas\venv
.\setup.ps1
```

## Environment

Two `.env` files drive the framework. Copy the examples and fill in values for your machine:

```powershell
Copy-Item evomas\.env.example evomas\.env
Copy-Item api\.env.example    api\.env
```

| Variable | File | Purpose |
|---|---|---|
| `OLLAMA_BASE_URL` | `evomas\.env` | URL of the Ollama server every agent's LLM call targets. Default: `http://localhost:11434`. |
| `WANDB_API_KEY` | `evomas\.env` | Optional. Only needed if you call `init_weave()`. |
| `RESULTS_DIR` | `evomas\.env` | Optional. Where predictions + evaluations are written. Relative paths resolve against the repo root. Default: `<repo>/results`. |
| `API_HOST`, `API_PORT` | `api\.env` | Bind addr for the FastAPI backend. Default: `0.0.0.0:8000`. |

## Run

The `evomas` command wraps every entry point. See [EVOMAS.md](./EVOMAS.md) for the full subcommand reference (one-line summary below):

```text
evomas ollama pull <model>     # ollama pull, targeting OLLAMA_BASE_URL
evomas ollama list             # ollama list
evomas ollama serve [--cpu-only]
evomas run instances ...       # generate the SWE-bench instances JSONL
evomas run prediction ...      # run inference, write predictions JSONL
evomas run evaluation ...      # score predictions via the SWE-bench harness (needs Docker)
evomas web                     # ng serve (Angular frontend on :4200)
evomas api                     # uvicorn (FastAPI backend on :8000)
```

For details on how a topology config is structured (`entry`, `end`, `edges`, `agents`, edge-driven state), see [TOPOLOGY_CONFIG.md](./TOPOLOGY_CONFIG.md).
