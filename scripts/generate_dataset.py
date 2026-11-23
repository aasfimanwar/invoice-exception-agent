"""Generate the synthetic dataset into data/synthetic (deterministic for a given seed)."""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from invoice_agent.generator import DEFAULT_SEED, build_dataset, write_dataset
from invoice_agent.policy_engine import PolicyEngine
from invoice_agent.policy_file import REPO_ROOT


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "data" / "synthetic")
    args = parser.parse_args()
    engine = PolicyEngine()
    start = time.perf_counter()
    dataset = build_dataset(args.seed, engine)
    manifest = write_dataset(dataset, args.out, args.seed, str(engine.policy["meta"]["version"]))
    print(f"Wrote {manifest['cases']} cases to {args.out} in {time.perf_counter() - start:.1f}s")
    for key in ("by_primary_type", "by_ambiguity", "by_expected_action", "by_urgency"):
        print(f"{key}: {manifest[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
