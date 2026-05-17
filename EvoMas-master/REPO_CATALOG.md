# Upstream projects & licensing

EvoMas is built on top of, and inspired by, a long list of open-source
coding-agent projects. This page tells you which projects feed into the
agent-variant catalog, what license each one ships under, and what those
licenses mean if you want to use EvoMas — internally, in research, or
commercially.

## How EvoMas relates to each upstream project

Three layers, with very different copyright posture for each:

1. **Prompts and agent roles** — `evomas/config/agent_types/<repo>.json`.
   Each catalog mirrors an upstream project's agent personas (search
   agent, patch agent, reviewer, etc.) and their instruction templates.
   Most catalogs ship paraphrased prompts; a handful still carry the
   upstream wording verbatim and are flagged in the table.
2. **Tool implementations** — `evomas/tools/<repo>/*.py`. Every Python
   tool body is written from scratch by the EvoMas authors. The
   *filename* and exported symbol name match the upstream identifier so
   the catalog reads cleanly, but the executable behavior is EvoMas's
   own — no upstream function bodies are copied.
3. **Topology engine, MCP server, evaluation harness, and frontend** —
   entirely EvoMas-authored. No upstream code feeds into these.

## Upstream projects

Each row is pinned to the exact commit EvoMas references. License was
read directly from the LICENSE file at that commit.

| Project | License | EvoMas surface | Caveat |
|---|---|---|---|
| [aider](https://github.com/Aider-AI/aider) | Apache-2.0 | prompts (14 agents) | — |
| [augment-swebench-agent](https://github.com/augmentcode/augment-swebench-agent) | MIT | prompts (1) + 3 tools | — |
| [auto-code-rover](https://github.com/AutoCodeRoverSG/auto-code-rover) | **SONAR Source-Available v1.0** | prompts (6, verbatim) + 1 tool | Source-available — commercial / competing-product use forbidden |
| [claude-coder](https://github.com/kodu-ai/claude-coder) | **AGPL-3.0-or-later** | prompts (1, verbatim) + 15 tools | Strong network-copyleft — hosted use triggers source-release |
| [composio](https://github.com/ComposioHQ/composio) | MIT | prompts (14) + 4 tools | — |
| [DARS-Agent](https://github.com/darsagent/DARS-Agent) | Apache-2.0 | prompts (2) | — |
| [debug-gym](https://github.com/microsoft/debug-gym) | MIT | prompts (4) + 1 tool | — |
| [ExpeRepair](https://github.com/ExpeRepair/ExpeRepair) | MIT | prompts (4) | — |
| [HyperAgent](https://github.com/FSoft-AI4Code/HyperAgent) | Apache-2.0 | prompts (7) | — |
| [joycode-agent](https://github.com/jd-opensource/joycode-agent) | MIT | prompts (1) + 3 tools | — |
| [KGCompass](https://github.com/GLEAM-Lab/KGCompass) | MIT | prompts (3) | — |
| [Lingma-SWE-GPT](https://github.com/LingmaTongyi/Lingma-SWE-GPT) | **No LICENSE** | prompts (6, verbatim) + 8 tools | All-rights-reserved by default |
| [Lingxi](https://github.com/nimasteryang/Lingxi) | MIT | prompts (4) | — |
| [mini-SWE-agent](https://github.com/SWE-agent/mini-SWE-agent) | MIT | prompts (2) | — |
| [OpenHands](https://github.com/All-Hands-AI/OpenHands) | MIT (root) | prompts (8) + 11 tools | `enterprise/` subtree is non-MIT — EvoMas uses no enterprise code |
| [OrcaLoca](https://github.com/fishmingyu/OrcaLoca) | MIT | prompts (6) | — |
| [patchwork](https://github.com/patched-codes/patchwork) | **AGPL-3.0-only** | prompts (15, verbatim) + 5 tools | Strong network-copyleft |
| [programmer](https://github.com/wandb/programmer) | Apache-2.0 | prompts (3) | — |
| [R2E-Gym](https://github.com/agentica-project/R2E-Gym) | Apache-2.0 | prompts (1) | — |
| [suna](https://github.com/kortix-ai/suna) | **KPSL v1.0** (source-available) | 1 tool | Source-available — commercial / hosted use restricted |
| [SWE-agent](https://github.com/SWE-agent/SWE-agent) | MIT | prompts (9) + 1 tool | — |
| [trae-agent](https://github.com/bytedance/trae-agent) | MIT | prompts (4) + 6 tools | — |

## What this means in practice

### If you want to use EvoMas for **internal evaluation or research**

You can use the whole catalog. None of the upstream licenses above
forbid internal/academic/research use. Attribution is appreciated for
the MIT/Apache projects; it's the explicit condition of the
permissive licenses.

### If you want to **ship EvoMas as a hosted service** or as part of a **commercial product**

Three groups need attention:

- **AGPL projects** (`claude-coder`, `patchwork`) — even running EvoMas
  as a service that exposes these agent variants would, on a strict
  reading of AGPL, require you to release your full deployment under
  AGPL. The conservative move is to disable these two variants in
  hosted/commercial deployments, or accept the AGPL obligation.

- **Source-available projects** (`auto-code-rover` under SONAR,
  `suna` under KPSL) — commercial and competing-product use is
  explicitly forbidden by these licenses. Same recommendation:
  disable these variants in commercial deployments.

- **No-LICENSE projects** (`Lingma-SWE-GPT`) — with no license granted,
  the upstream content defaults to all-rights-reserved. The
  `Lingma-SWE-GPT` prompts that ship in the catalog were imported
  verbatim and have no legal basis for redistribution; if you ship
  EvoMas commercially, disable those variants.

The MIT, Apache-2.0, and BSD-licensed rows have no commercial
restriction beyond attribution.

### What EvoMas itself contributes back

The tool implementations under `evomas/tools/`, the LangGraph topology
engine, the MCP server, the evaluation harness, and the Angular
frontend are all original to EvoMas. They carry the project's own
license (see `LICENSE` at the repo root). The upstream projects above
have no copyright claim over those layers.

## Disclaimer

The license labels and caveats on this page are a best-effort summary
of upstream LICENSE files read at the exact commits EvoMas pins. They
are not legal advice. For any commercial deployment, you should obtain
a real license review of every upstream project you ship.
