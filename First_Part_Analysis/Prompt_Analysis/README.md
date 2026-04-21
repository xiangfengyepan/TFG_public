# Prompt Analysis

Extracts prompt-engineering pattern features from the SWE-bench agent CSVs and writes a consolidated `prompt_analysis.csv` for further analysis.

## Prerequisites

- **Python 3** on PATH (`python`, `python3`, or `py`)
- Standard library only — no external packages required

---

## Quick start

Open PowerShell in the `Prompt_Anlysis` folder and run:

```powershell
# Default: reads agents_csv/, writes prompt_analysis.csv
.\run.ps1

# Custom input folder and output file
.\run.ps1 -InputFolder my_csvs -OutputFile results.csv
```

Or run the script directly with Python:

```bash
python prompt_analysis.py
python prompt_analysis.py --input-folder my_csvs --output-file results.csv
```

---

## Input

### `agents_csv/` folder

Contains one CSV file per SWE-bench repository (27 files total). Each file follows this schema:

| Column | Description |
|---|---|
| `#` | Row index |
| `Name` | Agent name |
| `Agent Type` | Category of the agent (e.g. Base agent, Orchestrator) |
| `Short Description` | Brief description of the agent |
| `Agent in the repo` | URL to the agent source in GitHub |
| `Prompt N Type` | Type of prompt N — `SYSTEM`, `PROXY`, or `HUMAN` |
| `Prompt N` | Raw text of prompt N |
| `URL Prompt N` | Source URL for the prompt |
| `URL Tool N` | URLs to tools used by the agent |
| `Comment` | Free-text notes |

The script detects all columns matching `Prompt <digit>` automatically, so files with more than one prompt are handled without any code changes.

### Prompt types

| Type | Meaning |
|---|---|
| `SYSTEM` | Instructions or guidelines fed to the model at the system level |
| `PROXY` | Prompt that acts as an intermediary, relaying context or instructions on behalf of another component |
| `HUMAN` | Turn-level prompt meant to simulate or represent a human message |

See [PromptAnalysis.md](PromptAnalysis.md) for a full description of each type and the eight detected categories.

---

## Output — `prompt_analysis.csv`

One row is written per (repo, agent, prompt) combination. Columns:

| Column | Description |
|---|---|
| `Repo` | Source CSV filename |
| `Agent` | Value from the `Name` column |
| `UPPERCASE` | Sentences containing a fully-uppercase word (≥ 2 chars), e.g. `IMPORTANT`, `MUST`, `NOTE` |
| `Use of words` | Sentences with directive modal/obligatory verbs: *should, must, have to, need to, always, ensure* |
| `Punctuation` | Sentences ending with `!` or containing `?` |
| `Markup tags` | Sentences containing an XML/HTML-style tag, e.g. `<IMPORTANT>`, `</instruction>`, `[INST]` |
| `Role definition` | Sentences opening with *"You are (a/an/the…)"* or *"Act as"*, establishing the agent's persona |
| `Negation` | Sentences with explicit prohibitions: *do not, don't, never, avoid, must not, cannot, refrain* |
| `Output format` | Sentences specifying the expected response structure: *return, output, format, JSON, markdown, YAML, XML, structured, bullet, numbered list, …* |
| `Numbered list` | Lines that begin with a number followed by `.` or `)`, indicating an enumerated instruction list |
| `Comments` | Empty column reserved for manual annotation |

Within each feature cell, matches are separated by a newline character so multi-match cells remain readable in spreadsheet tools.

---

## CLI options

| Option | Default | Description |
|---|---|---|
| `--input-folder` | `agents_csv` | Folder containing the per-repo agent CSVs |
| `--output-file` | `prompt_analysis.csv` | Path for the output CSV |

---

## Adding new agent CSVs

1. Place the new CSV file in `agents_csv/`.
2. Ensure it has at least `Name` and one `Prompt <digit>` column.
3. Re-run `.\run.ps1` — the new file is picked up automatically.
