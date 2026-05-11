import argparse
import json
import logging
from pathlib import Path
from typing import Any

from evomas.core.workflow.runner import run as run_evomas_workflow
from evomas.exceptions.errors import OllamaMemoryError
from evomas.utils.weave_init import init_weave

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def load_instances(instances_path: str, limit: int | None = None) -> list[dict[str, Any]]:
    path = Path(instances_path)
    if not path.exists():
        raise FileNotFoundError(
            f"Instances file not found: {instances_path}\n"
            f"Generate it first with: evomas run instances --output {instances_path}"
        )
    instances = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                instances.append(json.loads(line))
    if limit is not None and limit > 0:
        instances = instances[:limit]
    return instances


def run_evomas(instance: dict[str, Any], config: str = "") -> str:
    return run_evomas_workflow(instance, config=config)


def build_predictions(
    instances_path: str,
    output_path: str,
    config: str = "",
    limit: int | None = None,
) -> int:
    instances = load_instances(instances_path, limit)
    logger.info("Loaded %d instances from %s", len(instances), instances_path)

    count = 0
    with open(output_path, "w") as out:
        for item in instances:
            instance_id: str = item["instance_id"]
            logger.info("Processing %s", instance_id)
            try:
                patch = run_evomas(item, config=config)
            except OllamaMemoryError as exc:
                logger.error("Ollama out of memory - aborting run: %s", exc)
                break  # model cannot load; no point trying remaining instances
            except Exception as exc:
                logger.error("run_evomas failed on %s: %s", instance_id, exc)
                patch = ""
            pred = {
                "instance_id": instance_id,
                "model_patch": patch,
                "model_name_or_path": "evomas",
                # Forward the instance's source subset/split so the
                # Evaluation page can partition by (subset, split) and run the
                # harness against the right HuggingFace dataset.
                "subset": item.get("subset", "lite"),
                "split":  item.get("split", "dev"),
            }
            out.write(json.dumps(pred) + "\n")
            out.flush()  # each prediction visible in the file immediately
            count += 1

    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--instances",
        default="swebench_instances.jsonl",
        help="Path to JSONL file produced by generate_swebench_instances.py",
    )
    parser.add_argument("--output", default="evomas_predictions.jsonl")
    parser.add_argument(
        "--config",
        default="",
        help=(
            "Unified config to run. Either a stem resolved against "
            "evomas/config/<stem>.json (e.g. 'evo-star') or a path to a config JSON."
        ),
    )
    parser.add_argument("--limit", type=int, default=None,
                        help="Process only the first N instances (smoke test)")
    args = parser.parse_args()

    # init_weave() TODO uncomment this if wanna run weave
    logger.info(
        "Generating predictions from %s (config=%s, limit=%s)",
        args.instances, args.config, args.limit,
    )
    total = build_predictions(args.instances, args.output, args.config, args.limit)
    logger.info("Generated %d predictions → %s", total, args.output)


if __name__ == "__main__":
    main()
