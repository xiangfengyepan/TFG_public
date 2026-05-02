#!/usr/bin/env python3
"""
generate_filters.py
For every subfolder in filters/ that contains node.js and edge.js,
write config/filters_<folder>.json in Gephi Lite script-filter format.

Usage:
  py -3 generate_filters.py
"""

import json
import re
from pathlib import Path

HERE = Path(__file__).parent
FILTERS_DIR = HERE / "filters"
CONFIG_DIR = HERE / "config"


def strip_jsdoc(text: str) -> str:
    """Remove leading JSDoc / block comments, matching generate_sessions.py style."""
    return re.sub(r'^\s*/\*[\s\S]*?\*/\s*', '', text).rstrip()


def main():
    CONFIG_DIR.mkdir(exist_ok=True)

    if not FILTERS_DIR.exists():
        print(f"Error: filters/ directory not found at {FILTERS_DIR}")
        return

    generated = 0
    for folder in sorted(FILTERS_DIR.iterdir()):
        if not folder.is_dir():
            continue

        node_js = folder / "node.js"
        edge_js = folder / "edge.js"

        if not node_js.exists() or not edge_js.exists():
            print(f"  [warn] Skipping '{folder.name}': missing node.js or edge.js")
            continue

        node_script = strip_jsdoc(node_js.read_text(encoding="utf-8"))
        edge_script = strip_jsdoc(edge_js.read_text(encoding="utf-8"))

        filters_data = {
            "filters": [
                {
                    "type": "script",
                    "itemType": "nodes",
                    "script": ["<<Function", node_script, "Function>>"],
                },
                {
                    "type": "script",
                    "itemType": "edges",
                    "script": ["<<Function", edge_script, "Function>>"],
                },
            ]
        }

        out_path = CONFIG_DIR / f"filters_{folder.name}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(filters_data, f, ensure_ascii=False, indent=2)
        print(f"  Written: {out_path.name}")
        generated += 1

    print(f"Done. {generated} filter file(s) generated.")


if __name__ == "__main__":
    main()
