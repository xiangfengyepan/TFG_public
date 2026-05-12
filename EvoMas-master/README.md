# EvoMas

Evolutionary multi-agent framework for [SWE-bench](https://www.swebench.com/)–style automated program repair.

## Prerequisites

| Tool | Why | Where to get it |
|---|---|---|
| Python 3.12+ (3.12.6 is the dev baseline) | Runs the agent framework and the FastAPI backend. | https://www.python.org/downloads/ |
| Ollama | Hosts the local LLM each agent calls. | https://ollama.com/download |
| Docker (Desktop on Windows/macOS, Engine on Linux) | Required for SWE-bench evaluation (the harness runs each instance in a container). Not needed for inference-only flows. On Windows the harness invocation is shelled through WSL; on macOS / Linux it runs natively. | https://www.docker.com/products/docker-desktop/  ·  https://docs.docker.com/engine/install/ |
| Node.js 18+ | Builds and serves the Angular frontend. | https://nodejs.org/ |
| WSL2 (Windows only) | The SWE-bench harness ships POSIX-only steps; on Windows the API server shells out via `wsl ...`. Not needed on macOS / Linux. | https://learn.microsoft.com/windows/wsl/install |

## Install

Windows (PowerShell):

```powershell
.\setup.ps1
```

Linux / macOS (bash):

```bash
chmod +x setup.sh 
bash setup.sh
```

The setup script checks for the prerequisites above, creates a venv at `evomas/venv` (reusing it if already present), runs `pip install -e "."` (which reads `pyproject.toml` for dependencies + registers the `evomas` console command), regenerates `requirements.txt` as a lockfile, and appends an `evomas` function to your shell rc (`$PROFILE` on Windows, `~/.zshrc` / `~/.bashrc` / `~/.config/fish/config.fish` on Linux/macOS) so the command is reachable from any directory.

Open a new shell (or `source` the rc file) so the profile change takes effect, then verify:

```bash
evomas --help
```

### Setup fails or imports break after an upgrade

The setup script is intentionally non-destructive — it reuses any existing `evomas/venv`. If a previous install left the venv in a broken state (missing packages, mismatched versions, `ModuleNotFoundError`), delete it and rerun setup (`rm -r` works in both bash and PowerShell, which aliases it to `Remove-Item -Recurse`):

```
rm -r evomas/venv
```

Then rerun the platform-appropriate setup command from the Install section above.

## Environment

Two `.env` files drive the framework. Copy the examples and fill in values for your machine — `cp` is an alias for `Copy-Item` in PowerShell, so the same line works in both shells:

```
cp evomas/.env.example evomas/.env
cp api/.env.example    api/.env
```

| Variable | File | Purpose |
|---|---|---|
| `OLLAMA_BASE_URL` | `evomas/.env` | URL of the Ollama server every agent's LLM call targets. Default: `http://localhost:11434`. |
| `WANDB_API_KEY` | `evomas/.env` | Optional. Only needed if you call `init_weave()`. |
| `RESULTS_DIR` | `evomas/.env` | Optional. Where predictions + evaluations are written. Relative paths resolve against the repo root. Default: `<repo>/results`. |
| `API_HOST`, `API_PORT` | `api/.env` | Bind addr for the FastAPI backend. Default: `0.0.0.0:8000`. |

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
