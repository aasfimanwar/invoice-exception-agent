"""Build data/synthetic/split.json from the committed dataset (deterministic for a seed)."""

from __future__ import annotations

import argparse
import json

from invoice_agent.evalset import (
    DATA_DIR,
    DEFAULT_SPLIT_SEED,
    build_split,
    load_dataset,
    write_split,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SPLIT_SEED)
    args = parser.parse_args()
    manifest = json.loads((DATA_DIR / "manifest.json").read_text(encoding="utf-8"))
    dataset = load_dataset(DATA_DIR)
    split = build_split(dataset.labels, args.seed, manifest["sha256"])
    write_split(split, DATA_DIR / "split.json")
    print(
        f"dev={len(split.dev)} test={len(split.test)} "
        f"hand={len(split.hand_label_subset)} dev_subset={len(split.dev_subset)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
