import os
import json
import json
from typing import Dict, Any


def get_nodes_data(file_path="workflow_data.json"):
    """Reads node configuration from a JSON file."""
    if not os.path.exists(file_path):
        print(f"Warning: {file_path} not found. Falling back to empty list.")
        return []

    try:
        with open(file_path, "r") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error parsing JSON: {e}")
        return []


def load_state_from_disk(path: str) -> Dict[str, Any]:
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state_to_disk(path: str, state: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)

def merge_json_objects(json_list):
    merged = {}

    for obj in json_list:
        merged.update(obj)

    return merged