from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from invoice_agent.policy_file import (
    POLICY_PATH,
    PolicyDict,
    PolicyError,
    load_policy,
    load_valid_policy,
    validate_policy,
)
from invoice_agent.policy_render import render_policy_markdown


@pytest.fixture
def policy() -> PolicyDict:
    return load_policy()


def test_real_policy_file_is_consistent() -> None:
    assert validate_policy(load_policy()) == []
    assert load_valid_policy()["meta"]["synthetic"] is True


def test_confidence_threshold_is_not_set_by_hand(policy: PolicyDict) -> None:
    # Phase 4 tunes this on labelled dev data only. A hand-set value would be a leak.
    assert policy["parameters"]["confidence"]["escalation_threshold"] is None


def test_every_type_ends_with_an_unconditional_fallback(policy: PolicyDict) -> None:
    for exc_type, rules in policy["rules"].items():
        last = rules[-1]
        assert last["when"] == []
        if exc_type != "price_mismatch":
            # price_mismatch ends in a plain default action (PM-6); the rest end in policy_gap
            assert last["action"] == "escalate"
            assert last["ambiguity"] == "policy_gap"


def test_rule_ids_are_unique(policy: PolicyDict) -> None:
    ids = [rule["id"] for rules in policy["rules"].values() for rule in rules]
    assert len(ids) == len(set(ids))


def test_undefined_predicate_is_rejected(policy: PolicyDict) -> None:
    broken = copy.deepcopy(policy)
    broken["rules"]["price_mismatch"][0]["when"] = ["no_such_predicate"]
    assert any("undefined predicate" in e for e in validate_policy(broken))


def test_shadowing_rule_is_rejected(policy: PolicyDict) -> None:
    broken = copy.deepcopy(policy)
    broken["rules"]["missing_po"][0]["when"] = []
    assert any("shadows" in e for e in validate_policy(broken))


def test_auto_approve_limit_cannot_exceed_supervisor_tier(policy: PolicyDict) -> None:
    broken = copy.deepcopy(policy)
    broken["parameters"]["autonomy"]["agent_auto_approve_limit_gbp"] = 20000.0
    assert any("auto-approve" in e for e in validate_policy(broken))


def test_load_valid_policy_raises_on_inconsistent_file(tmp_path: Path, policy: PolicyDict) -> None:
    broken = copy.deepcopy(policy)
    broken["rules"]["price_mismatch"][0]["action"] = "teleport"
    path = tmp_path / "policy.yaml"
    path.write_text(yaml.safe_dump(broken), encoding="utf-8")
    with pytest.raises(PolicyError):
        load_valid_policy(path)


def test_policy_markdown_is_in_sync_with_yaml() -> None:
    target = POLICY_PATH.parents[1] / "docs" / "POLICY.md"
    rendered = render_policy_markdown(load_valid_policy())
    assert target.read_text(encoding="utf-8").replace("\r\n", "\n") == rendered
