#!/usr/bin/env python3
"""
generate_sessions.py
For every *_layout.js in layouts/, write config/session_<name>.json
embedding the script in Gephi Lite's session format.
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
LAYOUTS_DIR = HERE / "layouts"
CONFIG_DIR = HERE / "config"
BASE_SESSION = CONFIG_DIR / "session.json"


def main():
    if BASE_SESSION.exists():
        with open(BASE_SESSION, encoding="utf-8") as f:
            base = json.load(f)
    else:
        base = {"metrics": {}}

    for js_file in sorted(LAYOUTS_DIR.glob("*_layout.js")):
        stem = js_file.stem
        name = stem[:-7] if stem.endswith("_layout") else stem
        raw = js_file.read_text(encoding="utf-8")
        # Strip leading JSDoc / block comments to match session.json format
        script_text = re.sub(r'^\s*/\*[\s\S]*?\*/\s*', '', raw).rstrip()

        session = {
            **base,
            "layoutsParameters": {
                **base.get("layoutsParameters", {}),
                "script": {"script": ["<<Function", script_text, "Function>>"]},
            },
        }

        out_path = CONFIG_DIR / f"session_{name}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)
        print(f"  Written: {out_path.name}")

    print("Done.")


if __name__ == "__main__":
    main()
