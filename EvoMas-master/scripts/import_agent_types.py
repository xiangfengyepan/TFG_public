"""Convert the SWE-bench agent-type analysis CSVs into EvoMas catalog data.

Run once after the source CSVs change. Reads every `*.csv` under `--csv-dir`
(one CSV = one open-source SWE-bench solver repo) and emits:

  * `evomas/config/agent_types/<RepoStem>.json`  -- agents + prompts + tool URLs.
  * `evomas/tools/<repo_snake>/__init__.py` + one stub `.py` per `URL Tool` --
    every stub function carries the source URL in its docstring and raises
    `NotImplementedError`. Discoverable / documented; port the real impl when
    a real agent needs the tool.

Usage:
    python scripts/import_agent_types.py
    python scripts/import_agent_types.py --csv-dir /path/to/agents_csv \\
                                         --overview /path/to/AgentType.csv \\
                                         --out-config evomas/config/agent_types \\
                                         --out-tools  evomas/tools
"""
from __future__ import annotations

import argparse
import csv
import json
import logging
import re
import sys
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Repos with hand-maintained tool packages (do not regenerate stubs that
# would clobber the working implementations).
_SKIP_REPOS = {"OpenHands"}

# Canonical AGENT_TYPE taxonomy (mirrors evomas.agents.types). The overview
# Match the canonical EvoMas taxonomy (formerly "Localizator" -- corrected
# to the typo-free "Locator" 2026-05-13).
CANONICAL_TYPES: tuple[str, ...] = (
    "Locator",
    "Patcher",
    "Helper/Proxy",
    "Planner/Orchestrator",
    "Base agent",
    "Bug reproduction",
    "Environment setup",
    "Reviewer",
)
_TYPE_ALIASES: dict[str, str] = {
    "locator": "Locator",
    "patcher": "Patcher",
    "helper/proxy": "Helper/Proxy",
    "helper": "Helper/Proxy",
    "proxy": "Helper/Proxy",
    "planner/orchestrator": "Planner/Orchestrator",
    "planner": "Planner/Orchestrator",
    "orchestrator": "Planner/Orchestrator",
    "base agent": "Base agent",
    "bug reproduction": "Bug reproduction",
    "environment setup": "Environment setup",
    "enviorment setup": "Environment setup",  # common typo in source CSVs
    "reviewer": "Reviewer",
}

# Prompt-Type column values that map to each canonical slot. Case-insensitive
# comparison; values not in any list are ignored with a warning.
_PROMPT_SLOTS: dict[str, tuple[str, ...]] = {
    "system":  ("system",),
    "user":    ("user", "human", "instance", "task"),
    "proxy":   ("proxy", "assistant", "tool"),
}


def _slugify_repo(name: str) -> str:
    """Normalize a CSV stem ("SWE_agent", "auto_code_rover", "OpenHands") into
    a Python-package-safe snake_case identifier for `evomas/tools/<...>/`."""
    s = name.strip()
    # Insert _ between lower-upper and upper-upper-lower transitions
    s = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", s)
    s = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", s)
    s = s.lower()
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "unknown"


def _tool_name_from_url(url: str) -> str:
    """Derive a Python-identifier-safe function name from a source URL.

    Examples:
        .../tools/edit_file.py#L12  -> edit_file
        .../tools/finish-tool.py    -> finish_tool
        .../path/to/                -> tool   (fallback)
    """
    if not url:
        return "tool"
    # Drop fragment and trailing slash
    path = url.split("#", 1)[0].rstrip("/")
    # Last path segment
    seg = path.rsplit("/", 1)[-1] or "tool"
    # Drop extension
    seg = re.sub(r"\.(py|js|ts|md|rs|go|java|cpp|c|h)$", "", seg, flags=re.IGNORECASE)
    # Sanitize to a valid Python identifier
    seg = re.sub(r"[^A-Za-z0-9_]+", "_", seg).strip("_") or "tool"
    if seg[0].isdigit():
        seg = f"t_{seg}"
    return seg


def _canon_types(raw: str | None) -> list[str]:
    """Return every canonical AGENT_TYPE the raw cell mentions.

    The CSV's `Agent Type` column sometimes holds a comma-separated list
    (e.g. "Patcher, Locator" for agents that span multiple roles) and
    sometimes accidentally holds a description (a CSV parsing artefact
    when the previous row's prompt cell ate part of the line). We split
    on comma + bullets, resolve each token through `_TYPE_ALIASES`, and
    drop anything that isn't in the canonical 8."""
    if not raw:
        return []
    out: list[str] = []
    # Allow "; " and " / " as separators too; some rows use those.
    for token in re.split(r"[,;]+|\s+/\s+", raw):
        key = token.strip().lower()
        if not key:
            continue
        canon = _TYPE_ALIASES.get(key)
        if canon:
            if canon not in out:
                out.append(canon)
            continue
        # exact match against canonical (covers case differences only)
        for c in CANONICAL_TYPES:
            if c.lower() == key:
                if c not in out:
                    out.append(c)
                break
    return out


def _slot_for_prompt_type(raw: str | None) -> str | None:
    if not raw:
        return None
    key = raw.strip().lower()
    for slot, aliases in _PROMPT_SLOTS.items():
        if key in aliases:
            return slot
    return None


def _extract_prompts(row: dict[str, str]) -> dict[str, str]:
    """Aggregate `Prompt N Type` / `Prompt N` columns into the 3 EvoMas slots
    (system / user / proxy). Multiple prompts of the same type get joined with
    a blank line so no content is lost."""
    buckets: dict[str, list[str]] = {"system": [], "user": [], "proxy": []}
    # Find every "Prompt N Type" column the CSV row carries.
    type_keys = [k for k in row.keys() if k and re.match(r"^Prompt\s+\d+\s+Type$", k.strip())]
    for type_key in type_keys:
        n_match = re.match(r"^Prompt\s+(\d+)\s+Type$", type_key.strip())
        if not n_match:
            continue
        n = n_match.group(1)
        body_key = next((k for k in row.keys() if k and k.strip() == f"Prompt {n}"), None)
        if not body_key:
            continue
        slot = _slot_for_prompt_type(row.get(type_key))
        body = (row.get(body_key) or "").strip()
        if not body or not slot:
            if body and not slot:
                logger.debug("dropped prompt %s with unknown type %r", n, row.get(type_key))
            continue
        buckets[slot].append(body)
    return {k: "\n\n".join(v) for k, v in buckets.items() if v}


def _extract_tool_urls(row: dict[str, str]) -> list[str]:
    urls: list[str] = []
    for k, v in row.items():
        if not k:
            continue
        if re.match(r"^URL\s+Tool\s+\d+$", k.strip()):
            u = (v or "").strip()
            if u:
                urls.append(u)
    return urls


def _disambiguate_tool_names(urls: list[str]) -> list[dict[str, str]]:
    """Pair each URL with a Python-safe name, suffixing _2, _3, ... on
    duplicates so the generated `def` names stay unique inside one repo."""
    used: dict[str, int] = {}
    out: list[dict[str, str]] = []
    for u in urls:
        base = _tool_name_from_url(u)
        if base in used:
            used[base] += 1
            name = f"{base}_{used[base]}"
        else:
            used[base] = 1
            name = base
        out.append({"name": name, "source_url": u})
    return out


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    """Robust CSV read -- prompts contain embedded newlines, so we need the
    standard csv module rather than splitting lines manually."""
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        return [dict(r) for r in reader]


def _convert_repo_csv(csv_path: Path) -> dict[str, Any]:
    rows = _read_csv_rows(csv_path)
    agents: list[dict[str, Any]] = []
    for row in rows:
        name = (row.get("Name") or "").strip()
        if not name:
            continue
        # Skip rows that are actually description / definition rows leaking
        # through from the source spreadsheet (their `Name` is something like
        # "Description"; their `Agent Type` is a sentence not a label).
        if name.lower() in ("description", "definition", "header"):
            continue
        agent_types = _canon_types(row.get("Agent Type"))
        if not agent_types:
            logger.debug(
                "skipping %s/%s -- agent_type %r is not in the canonical 8",
                csv_path.name, name, row.get("Agent Type"),
            )
            continue
        prompts = _extract_prompts(row)
        tools = _disambiguate_tool_names(_extract_tool_urls(row))
        short_desc = (row.get("Short Description") or "").strip()
        source_url = (row.get("Agent in the repo") or "").strip()
        # Multi-type agents (e.g. "Patcher, Locator") get one entry per type --
        # the Topology dropdown lists the same agent under each role it fills.
        for at in agent_types:
            agents.append({
                "name":              name if len(agent_types) == 1 else f"{name} ({at})",
                "agent_type":        at,
                "short_description": short_desc,
                "source_url":        source_url,
                "prompts":           dict(prompts),
                "tools":             list(tools),
            })
    return {
        "id":         csv_path.stem,
        "source_csv": csv_path.name,
        "agents":     agents,
    }


_STUB_FILE_TEMPLATE = '''"""Auto-generated stub. See `scripts/import_agent_types.py`.

Source: {url}

Stub generated from `{csv_name}`. Port the real implementation before any
agent attempts to call this -- right now it raises NotImplementedError.
"""
from __future__ import annotations


def {func_name}(*args, **kwargs):
    """Stub generated from {csv_name}.

    Source: {url}
    """
    raise NotImplementedError(
        "{repo}.{func_name}: stub generated from {csv_name}"
    )
'''


_INIT_TEMPLATE = '''"""Auto-generated tool catalog for `{repo}` (from `{csv_name}`).

Every function in this package is a `NotImplementedError` stub. The
companion JSON at `evomas/config/agent_types/{json_name}` carries the
original tool URLs and per-agent prompts.
"""
{imports}

TOOLS = (
{tools_tuple})

__all__ = [
{all_exports}]
'''


def _write_tool_stubs(
    out_tools_root: Path,
    repo_snake: str,
    repo_label: str,
    csv_name: str,
    json_name: str,
    tool_names: list[str],
) -> None:
    pkg_dir = out_tools_root / repo_snake
    pkg_dir.mkdir(parents=True, exist_ok=True)

    # Even when the CSV has no URL Tool columns we still create the package
    # (empty TOOLS tuple) so it's discoverable.
    written: list[str] = []
    for spec in tool_names:
        name = spec["name"]
        url  = spec["source_url"]
        if name in written:
            continue  # already disambiguated upstream, but belt-and-braces
        (pkg_dir / f"{name}.py").write_text(
            _STUB_FILE_TEMPLATE.format(
                url=url, csv_name=csv_name, repo=repo_label, func_name=name,
            ),
            encoding="utf-8",
        )
        written.append(name)

    imports = "\n".join(
        f"from evomas.tools.{repo_snake}.{n} import {n}" for n in written
    )
    tools_tuple = "\n".join(f"    {n}," for n in written)
    all_exports = "\n".join(f"    \"{n}\"," for n in written)

    if not written:
        imports = "# (no tool URLs in source CSV -- TOOLS is empty)"
        tools_tuple = ""
        all_exports = ""

    (pkg_dir / "__init__.py").write_text(
        _INIT_TEMPLATE.format(
            repo=repo_label,
            csv_name=csv_name,
            json_name=json_name,
            imports=imports,
            tools_tuple=tools_tuple,
            all_exports=all_exports,
        ),
        encoding="utf-8",
    )


def main() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    default_csv = Path(
        r"C:\Users\XF\Desktop\TFG_public\First_Part_Analysis\Prompt_Analysis\agents_csv"
    )
    default_overview = Path(
        r"C:\Users\XF\Desktop\TFG_public\First_Part_Analysis"
        r"\Open-Source-Proyects-SWE-Bench - AgentType.csv"
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv-dir",     type=Path, default=default_csv)
    parser.add_argument("--overview",    type=Path, default=default_overview)
    parser.add_argument("--out-config",  type=Path, default=repo_root / "evomas" / "config" / "agent_types")
    parser.add_argument("--out-tools",   type=Path, default=repo_root / "evomas" / "tools")
    args = parser.parse_args()

    if not args.csv_dir.is_dir():
        logger.error("csv-dir not found: %s", args.csv_dir)
        sys.exit(2)

    args.out_config.mkdir(parents=True, exist_ok=True)
    args.out_tools.mkdir(parents=True, exist_ok=True)

    csv_files = sorted(p for p in args.csv_dir.glob("*.csv") if p.is_file())
    if not csv_files:
        logger.error("no *.csv files in %s", args.csv_dir)
        sys.exit(2)

    written_jsons: list[Path] = []
    for csv_path in csv_files:
        # OpenHands has a hand-written tool package + alias module in
        # `evomas/tools/openhands/`; regenerating its stubs would overwrite
        # those with NotImplementedError shells. The JSON catalog is also
        # tuned by hand to reference EvoMas tool names directly. Skip both.
        if csv_path.stem in _SKIP_REPOS:
            logger.info("skipping %s (hand-maintained, not regenerated)", csv_path.stem)
            continue
        try:
            data = _convert_repo_csv(csv_path)
        except Exception as exc:  # noqa: BLE001
            logger.warning("skipping %s: %s", csv_path.name, exc)
            continue

        json_path = args.out_config / f"{csv_path.stem}.json"
        json_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        written_jsons.append(json_path)

        # Aggregate every tool URL across agents in this repo into a single
        # package. Disambiguation is per-repo (already applied per-agent;
        # we re-run across the union to dodge cross-agent collisions).
        all_urls: list[str] = []
        for ag in data["agents"]:
            for t in ag.get("tools", []):
                u = t.get("source_url")
                if u:
                    all_urls.append(u)
        unique_tools = _disambiguate_tool_names(all_urls)

        _write_tool_stubs(
            out_tools_root=args.out_tools,
            repo_snake=_slugify_repo(csv_path.stem),
            repo_label=csv_path.stem,
            csv_name=csv_path.name,
            json_name=f"{csv_path.stem}.json",
            tool_names=unique_tools,
        )
        logger.info(
            "wrote %s  agents=%d  tools=%d",
            json_path.relative_to(repo_root),
            len(data["agents"]),
            len(unique_tools),
        )

    logger.info("Done. %d JSON files written.", len(written_jsons))


if __name__ == "__main__":
    main()
