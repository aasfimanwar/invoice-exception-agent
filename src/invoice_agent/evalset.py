"""Evaluation sets: stratified dev/test split, nested dev subsets and the test-set lock.

ADR-002: stratified 70/30 split, test set locked until the final report.
ADR-013: the 60 hand-labelled cases are drawn from the dev split only, and the 30-case dev
subset used during development is nested inside them, so every day-to-day result can be audited.
"""

from __future__ import annotations

import json
import math
import os
import random
from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from invoice_agent.models import CaseLabels, Dataset, ExceptionCase, Frozen, World
from invoice_agent.policy_file import REPO_ROOT

SPLIT_VERSION = "1.0.0"
DEFAULT_SPLIT_SEED = 20260123
TEST_FRACTION = 0.30
MIN_TEST_PER_STRATUM = 2
HAND_PER_TYPE = 10
DEV_SUBSET_PER_TYPE = 5

DATA_DIR = REPO_ROOT / "data" / "synthetic"
SplitName = Literal["dev", "dev_subset", "hand", "test"]


class TestSetLocked(PermissionError):
    """Raised when code asks for the locked test set outside the final report."""

    __test__ = False  # not a pytest class, despite the name


class SplitDef(Frozen):
    split_version: str
    seed: int
    data_sha256: dict[str, str]
    dev: tuple[str, ...]
    test: tuple[str, ...]
    dev_subset: tuple[str, ...]
    hand_label_subset: tuple[str, ...]
    strata: dict[str, dict[str, int]]


def _round_half_up(value: float) -> int:
    return math.floor(value + 0.5)


def build_split(labels: Sequence[CaseLabels], seed: int, data_sha256: dict[str, str]) -> SplitDef:
    by_stratum: dict[str, list[str]] = defaultdict(list)
    for label in labels:
        by_stratum[label.stratum].append(label.case_id)

    dev: list[str] = []
    test: list[str] = []
    strata: dict[str, dict[str, int]] = {}
    for stratum in sorted(by_stratum):
        ids = sorted(by_stratum[stratum])
        random.Random(f"{seed}:split:{stratum}").shuffle(ids)  # noqa: S311 - synthetic data
        n_test = max(MIN_TEST_PER_STRATUM, _round_half_up(TEST_FRACTION * len(ids)))
        test.extend(ids[:n_test])
        dev.extend(ids[n_test:])
        strata[stratum] = {"total": len(ids), "dev": len(ids) - n_test, "test": n_test}

    dev_set = set(dev)
    label_by_id = {lb.case_id: lb for lb in labels}
    hand: list[str] = []
    dev_subset: list[str] = []
    for primary in sorted({lb.primary_type for lb in labels}):
        pool = sorted(i for i in dev_set if label_by_id[i].primary_type == primary)
        ambiguous = [i for i in pool if label_by_id[i].ambiguity != "none"]
        clear = [i for i in pool if label_by_id[i].ambiguity == "none"]
        rng = random.Random(f"{seed}:hand:{primary}")  # noqa: S311 - synthetic data
        rng.shuffle(ambiguous)
        rng.shuffle(clear)
        n_amb = min(
            len(ambiguous), max(1, _round_half_up(HAND_PER_TYPE * len(ambiguous) / len(pool)))
        )
        picked = ambiguous[:n_amb] + clear[: HAND_PER_TYPE - n_amb]
        hand.extend(picked)
        # the dev subset keeps one ambiguous case per type (if any) and fills with clear ones
        amb_picked = [i for i in picked if label_by_id[i].ambiguity != "none"][:1]
        clear_picked = [i for i in picked if label_by_id[i].ambiguity == "none"]
        dev_subset.extend(amb_picked + clear_picked[: DEV_SUBSET_PER_TYPE - len(amb_picked)])

    return SplitDef(
        split_version=SPLIT_VERSION,
        seed=seed,
        data_sha256=data_sha256,
        dev=tuple(sorted(dev)),
        test=tuple(sorted(test)),
        dev_subset=tuple(sorted(dev_subset)),
        hand_label_subset=tuple(sorted(hand)),
        strata=strata,
    )


def write_split(split: SplitDef, path: Path) -> None:
    text = json.dumps(split.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8", newline="\n")


def load_split(path: Path = DATA_DIR / "split.json") -> SplitDef:
    return SplitDef.model_validate_json(path.read_text(encoding="utf-8"))


def load_dataset(data_dir: Path = DATA_DIR) -> Dataset:
    world = World.model_validate_json((data_dir / "world.json").read_text(encoding="utf-8"))
    cases = tuple(
        ExceptionCase.model_validate_json(line)
        for line in (data_dir / "cases.jsonl").read_text(encoding="utf-8").splitlines()
    )
    labels = tuple(
        CaseLabels.model_validate_json(line)
        for line in (data_dir / "labels.jsonl").read_text(encoding="utf-8").splitlines()
    )
    return Dataset(world=world, cases=cases, labels=labels)


def _unlock_test_set(final_report: bool, caller: str, access_log: Path) -> None:
    if not final_report or os.environ.get("ALLOW_TEST_SET") != "final":
        raise TestSetLocked(
            "The test set is locked until the final report (ADR-002). "
            "It needs final_report=True and ALLOW_TEST_SET=final, and every access is logged."
        )
    stamp = datetime.now(UTC).isoformat(timespec="seconds")
    with access_log.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"{stamp} {caller}\n")


def select(
    dataset: Dataset,
    split: SplitDef,
    name: SplitName,
    *,
    final_report: bool = False,
    caller: str = "unknown",
    access_log: Path = DATA_DIR / "test_access.log",
) -> Dataset:
    """Cases and labels for one named split. The test split is locked and its use is logged."""
    ids = {
        "dev": split.dev,
        "dev_subset": split.dev_subset,
        "hand": split.hand_label_subset,
        "test": split.test,
    }[name]
    if name == "test":
        _unlock_test_set(final_report, caller, access_log)
    wanted = set(ids)
    return Dataset(
        world=dataset.world,
        cases=tuple(c for c in dataset.cases if c.case_id in wanted),
        labels=tuple(lb for lb in dataset.labels if lb.case_id in wanted),
    )
