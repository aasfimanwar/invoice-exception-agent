from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from invoice_agent.evalset import (
    DATA_DIR,
    DEFAULT_SPLIT_SEED,
    SplitDef,
    TestSetLocked,
    build_split,
    load_dataset,
    load_split,
    select,
    write_split,
)
from invoice_agent.generator import DEFAULT_SEED, build_dataset
from invoice_agent.models import Dataset


@pytest.fixture(scope="module")
def dataset() -> Dataset:
    return build_dataset(DEFAULT_SEED)


@pytest.fixture(scope="module")
def split(dataset: Dataset) -> SplitDef:
    return build_split(dataset.labels, DEFAULT_SPLIT_SEED, {})


def test_dev_and_test_partition_all_cases(dataset: Dataset, split: SplitDef) -> None:
    everything = {c.case_id for c in dataset.cases}
    assert set(split.dev) | set(split.test) == everything
    assert not set(split.dev) & set(split.test)
    assert len(split.dev) + len(split.test) == 280


def test_split_is_stratified_about_seventy_thirty(dataset: Dataset, split: SplitDef) -> None:
    assert 0.27 <= len(split.test) / 280 <= 0.33
    totals = Counter(lb.stratum for lb in dataset.labels)
    assert set(split.strata) == set(totals)
    for stratum, counts in split.strata.items():
        assert counts["total"] == totals[stratum]
        assert counts["dev"] + counts["test"] == counts["total"]
        assert counts["test"] >= 2
        assert counts["dev"] >= 2
        assert abs(counts["test"] - 0.3 * counts["total"]) <= 1.0


def test_subsets_are_nested_and_dev_only(dataset: Dataset, split: SplitDef) -> None:
    dev, hand, small = set(split.dev), set(split.hand_label_subset), set(split.dev_subset)
    assert len(hand) == 60
    assert len(small) == 30
    assert small <= hand <= dev
    assert not hand & set(split.test)
    labels = {lb.case_id: lb for lb in dataset.labels}
    assert Counter(labels[i].primary_type for i in hand) == {
        t: 10 for t in set(labels[i].primary_type for i in hand)
    }
    assert Counter(labels[i].primary_type for i in small) == {
        t: 5 for t in set(labels[i].primary_type for i in small)
    }
    assert len({labels[i].primary_type for i in hand}) == 6
    hand_ambiguous = sum(labels[i].ambiguity != "none" for i in hand) / len(hand)
    assert 0.10 <= hand_ambiguous <= 0.35


def test_split_is_deterministic(dataset: Dataset, split: SplitDef) -> None:
    assert build_split(dataset.labels, DEFAULT_SPLIT_SEED, {}) == split
    assert build_split(dataset.labels, DEFAULT_SPLIT_SEED + 1, {}) != split


def test_test_set_is_locked_by_default(
    dataset: Dataset, split: SplitDef, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "access.log"
    monkeypatch.delenv("ALLOW_TEST_SET", raising=False)
    with pytest.raises(TestSetLocked):
        select(dataset, split, "test", access_log=log)
    with pytest.raises(TestSetLocked):
        select(dataset, split, "test", final_report=True, access_log=log)  # env var missing
    monkeypatch.setenv("ALLOW_TEST_SET", "final")
    with pytest.raises(TestSetLocked):
        select(dataset, split, "test", access_log=log)  # flag missing
    assert not log.exists()


def test_unlocked_test_access_is_logged(
    dataset: Dataset, split: SplitDef, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "access.log"
    monkeypatch.setenv("ALLOW_TEST_SET", "final")
    view = select(dataset, split, "test", final_report=True, caller="unit-test", access_log=log)
    assert {c.case_id for c in view.cases} == set(split.test)
    assert len(view.labels) == len(split.test)
    assert log.read_text(encoding="utf-8").strip().endswith("unit-test")


@pytest.mark.parametrize("name", ["dev", "dev_subset", "hand"])
def test_development_views_never_contain_test_cases(
    dataset: Dataset, split: SplitDef, name: str
) -> None:
    view = select(dataset, split, name)  # type: ignore[arg-type]
    assert not {c.case_id for c in view.cases} & set(split.test)
    assert {c.case_id for c in view.cases} == {lb.case_id for lb in view.labels}


def test_write_and_load_split_round_trip(split: SplitDef, tmp_path: Path) -> None:
    path = tmp_path / "split.json"
    write_split(split, path)
    assert load_split(path) == split


def test_committed_dataset_and_split_are_current(dataset: Dataset, split: SplitDef) -> None:
    assert load_dataset(DATA_DIR) == dataset
    committed = load_split()
    import json

    manifest = json.loads((DATA_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert committed.data_sha256 == manifest["sha256"], (
        "dataset changed: rerun scripts/make_split.py"
    )
    assert committed.model_copy(update={"data_sha256": {}}) == split
