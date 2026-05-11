import argparse
import json
import logging
from pathlib import Path

from datasets import load_dataset

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Three SWE-bench subsets supported by the frontend's nested instance picker.
SUBSET_DATASETS: dict[str, str] = {
    "lite":     "SWE-bench/SWE-bench_Lite",
    "full":     "SWE-bench/SWE-bench",
    "verified": "SWE-bench/SWE-bench_Verified",
}


def build_instances(
    split_name: str,
    output_path: str,
    limit: int | None = None,
    subset: str = "lite",
    append: bool = False,
) -> int:
    """Pull instances from HuggingFace and write one JSONL line per item.

    Each line is annotated with its source `subset` and `split` so the UI can
    group them. When `append=True`, existing lines for *other* (subset, split)
    pairs are preserved and only the matching pair is replaced.
    """
    if subset not in SUBSET_DATASETS:
        raise ValueError(
            f"unknown subset {subset!r}; expected one of {sorted(SUBSET_DATASETS)}"
        )
    ds = load_dataset(SUBSET_DATASETS[subset])
    if split_name not in ds:
        raise ValueError(f"split {split_name!r} not in dataset {SUBSET_DATASETS[subset]!r}")
    instances = ds[split_name]
    if limit is not None and limit > 0:
        instances = instances.select(range(min(limit, len(instances))))

    out = Path(output_path)
    surviving: list[str] = []
    if append and out.exists():
        # Drop any pre-existing lines for the same (subset, split) — those are
        # the ones we are about to re-fetch — and keep everything else.
        for raw in out.read_text(encoding="utf-8").splitlines():
            if not raw.strip():
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                surviving.append(raw)
                continue
            same_subset = (obj.get("subset", "lite") == subset)
            same_split = (obj.get("split", "dev") == split_name)
            if same_subset and same_split:
                continue
            surviving.append(raw)

    with out.open("w", encoding="utf-8") as f:
        for raw in surviving:
            f.write(raw + "\n")
        for item in instances:
            obj = dict(item)
            obj["subset"] = subset
            obj["split"] = split_name
            f.write(json.dumps(obj) + "\n")

    return len(instances)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subset", choices=list(SUBSET_DATASETS), default="lite",
                        help="SWE-bench subset to pull (default: lite)")
    parser.add_argument("--split", choices=["dev", "test"], default="dev")
    parser.add_argument("--output", default="swebench_instances.jsonl")
    parser.add_argument("--limit", type=int, default=None,
                        help="Process only the first N instances (smoke test)")
    parser.add_argument("--append", action="store_true",
                        help="Keep existing lines for other (subset, split) pairs.")
    args = parser.parse_args()

    logger.info(
        "Generating instances subset=%s split=%s limit=%s append=%s",
        args.subset, args.split, args.limit, args.append,
    )
    total = build_instances(args.split, args.output, args.limit,
                            subset=args.subset, append=args.append)
    logger.info("Generated %d instances → %s", total, args.output)


if __name__ == "__main__":
    main()
