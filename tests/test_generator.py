from __future__ import annotations

import json
from collections import Counter
from itertools import combinations
from pathlib import Path

import pytest

from invoice_agent.generator import (
    DEFAULT_SEED,
    RECIPES,
    TARGETS,
    TYPE_BY_PREFIX,
    build_dataset,
    make_supplier_pool,
    write_dataset,
)
from invoice_agent.models import Dataset, World
from invoice_agent.policy_engine import PolicyEngine, name_similarity
from invoice_agent.policy_file import REPO_ROOT, load_valid_policy

UNREACHABLE_RULES = {"MP-9", "DU-9"}


@pytest.fixture(scope="module")
def engine() -> PolicyEngine:
    return PolicyEngine()


@pytest.fixture(scope="module")
def dataset(engine: PolicyEngine) -> Dataset:
    return build_dataset(DEFAULT_SEED, engine)


def test_plan_totals() -> None:
    assert sum(TARGETS.values()) == 280
    by_type = Counter(TYPE_BY_PREFIX[rule[:2]] for rule, n in TARGETS.items() for _ in range(n))
    assert by_type == {
        "price_mismatch": 60,
        "missing_po": 45,
        "duplicate_invoice": 45,
        "wrong_supplier_details": 45,
        "quantity_mismatch": 40,
        "partial_delivery": 45,
    }


def test_every_policy_rule_is_planned_and_has_a_recipe() -> None:
    policy = load_valid_policy()
    rule_ids = {r["id"] for rules in policy["rules"].values() for r in rules}
    assert set(TARGETS) | UNREACHABLE_RULES == rule_ids
    assert set(RECIPES) == set(TARGETS)


def test_supplier_names_are_distinct() -> None:
    pool = make_supplier_pool(DEFAULT_SEED)
    assert len({s.supplier_id for s in pool}) == len(pool)
    assert all(name_similarity(a.legal_name, b.legal_name) < 80 for a, b in combinations(pool, 2))


def test_case_counts_match_the_plan(dataset: Dataset) -> None:
    assert len(dataset.cases) == len(dataset.labels) == 280
    assert Counter(lb.intended_rule for lb in dataset.labels) == TARGETS


def test_labels_match_the_engine_on_the_final_world(dataset: Dataset, engine: PolicyEngine) -> None:
    for case, label in zip(dataset.cases, dataset.labels, strict=True):
        assert case.case_id == label.case_id
        result = engine.resolve(case, dataset.world, label.issues)
        assert result.rule_id == label.intended_rule
        assert result.action == label.expected_action
        assert result.primary_type == label.primary_type
        assert result.ambiguity == label.ambiguity
        assert result.urgency == label.urgency
        assert result.requires_human_approval == label.requires_human_approval
        assert result.approver_tier == label.required_approver_tier
        assert result.expected_clauses == label.expected_clauses


def test_case_ids_are_unique_and_references_resolve(dataset: Dataset) -> None:
    ids = [c.case_id for c in dataset.cases]
    assert len(ids) == len(set(ids))
    tags = {lb.case_id: set(lb.tags) for lb in dataset.labels}
    for case in dataset.cases:
        inv = case.invoice
        if "supplier_record_missing" not in tags[case.case_id]:
            assert inv.supplier_id in dataset.world.suppliers
        if inv.po_reference and "missing_reference" not in tags[case.case_id]:
            assert inv.po_reference in dataset.world.purchase_orders


def test_ambiguous_share_is_about_a_fifth(dataset: Dataset) -> None:
    share = sum(lb.ambiguity != "none" for lb in dataset.labels) / len(dataset.labels)
    assert 0.15 <= share <= 0.30


def test_all_urgency_levels_are_well_represented(dataset: Dataset) -> None:
    counts = Counter(lb.urgency for lb in dataset.labels)
    assert set(counts) == {"critical", "high", "normal", "low"}
    assert min(counts.values()) >= 30


def test_messiness_and_edge_case_tags_are_present(dataset: Dataset) -> None:
    counts = Counter(t for lb in dataset.labels for t in lb.tags)
    minimums = {
        "rounding_difference": 5, "missing_reference": 10, "conflicting_supplier_names": 3,
        "name_alias": 5, "leading_zero_invoice_number": 3, "partial_delivery_open_balance": 20,
        "multi_issue": 5, "watchlist_supplier": 5, "above_auto_limit": 60,
        "supplier_note_present": 10, "boundary_case": 10, "overdue": 20,
        "supplier_record_unreadable": 2, "supplier_record_missing": 2,
    }  # fmt: skip
    for tag, minimum in minimums.items():
        assert counts[tag] >= minimum, f"{tag}: {counts[tag]} < {minimum}"


def test_automation_is_actually_possible(dataset: Dataset) -> None:
    approvals = [lb for lb in dataset.labels if lb.expected_action == "approve_within_tolerance"]
    needs_human = sum(lb.requires_human_approval for lb in approvals)
    assert needs_human >= 10
    assert len(approvals) - needs_human >= 10  # otherwise the gate would hide any benefit


def test_agent_visible_case_contains_no_labels(dataset: Dataset) -> None:
    for case in dataset.cases:
        text = case.model_dump_json()
        for leaked in ("expected_action", "intended_rule", "primary_type", "stratum", "ambiguity"):
            assert leaked not in text


def test_generation_is_deterministic(dataset: Dataset, engine: PolicyEngine) -> None:
    again = build_dataset(DEFAULT_SEED, engine)
    assert again.model_dump_json() == dataset.model_dump_json()
    other = build_dataset(DEFAULT_SEED + 1, engine)
    assert other.model_dump_json() != dataset.model_dump_json()


def test_written_files_round_trip_and_hash(dataset: Dataset, tmp_path: Path) -> None:
    manifest = write_dataset(dataset, tmp_path, DEFAULT_SEED, "x")
    assert manifest["synthetic"] is True
    assert manifest["cases"] == 280
    assert World.model_validate_json((tmp_path / "world.json").read_text("utf-8")) == dataset.world
    on_disk = json.loads((tmp_path / "manifest.json").read_text("utf-8"))
    assert on_disk["sha256"] == manifest["sha256"]
    assert len((tmp_path / "cases.jsonl").read_text("utf-8").splitlines()) == 280


def test_committed_dataset_is_current(
    dataset: Dataset, engine: PolicyEngine, tmp_path: Path
) -> None:
    committed = json.loads((REPO_ROOT / "data" / "synthetic" / "manifest.json").read_text("utf-8"))
    assert committed["policy_version"] == engine.policy["meta"]["version"], "regenerate the dataset"
    fresh = write_dataset(dataset, tmp_path, DEFAULT_SEED, str(engine.policy["meta"]["version"]))
    assert fresh["sha256"] == committed["sha256"], "run: uv run python scripts/generate_dataset.py"
