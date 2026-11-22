"""Load and validate policy/policy.yaml, the single source of truth (ADR-001)."""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / "policy" / "policy.yaml"

# Predicates the policy gate evaluates directly (global controls), not through a rule.
GATE_ONLY_PREDICATES = frozenset({"supplier_on_watchlist", "amount_above_auto_approve_limit"})

PolicyDict = dict[str, Any]


class PolicyError(ValueError):
    """Raised when the policy file is internally inconsistent."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def load_policy(path: Path = POLICY_PATH) -> PolicyDict:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise PolicyError(["policy file must contain a mapping at the top level"])
    return loaded


def validate_policy(policy: PolicyDict) -> list[str]:
    """Return a list of problems. An empty list means the policy is consistent."""
    errors: list[str] = []
    preds: set[str] = set(policy["predicates"])
    types: list[str] = policy["taxonomy"]["exception_types"]
    actions: set[str] = set(policy["taxonomy"]["actions"])
    ambiguity_kinds: list[str] = policy["taxonomy"]["ambiguity_kinds"]
    used: set[str] = set()
    seen_ids: set[str] = set()

    if set(policy["rules"]) != set(types):
        errors.append("rule types do not match taxonomy exception types")
    if sorted(policy["taxonomy"]["precedence_when_multiple_issues"]) != sorted(types):
        errors.append("precedence list must cover exactly the exception types")

    for exc_type, rules in policy["rules"].items():
        if rules[-1]["when"]:
            errors.append(f"{exc_type}: last rule must be an unconditional fallback")
        for index, rule in enumerate(rules):
            rid: str = rule["id"]
            if rid in seen_ids:
                errors.append(f"duplicate rule id {rid}")
            seen_ids.add(rid)
            if rule["action"] not in actions:
                errors.append(f"{rid}: unknown action {rule['action']}")
            for predicate in rule["when"]:
                used.add(predicate)
                if predicate not in preds:
                    errors.append(f"{rid}: undefined predicate {predicate}")
            is_escalation = rule["action"] == "escalate"
            if is_escalation and rule.get("ambiguity") not in ambiguity_kinds:
                errors.append(f"{rid}: escalate rule needs a valid ambiguity kind")
            if not is_escalation and "ambiguity" in rule:
                errors.append(f"{rid}: ambiguity is only valid on escalate rules")
            if not rule["when"] and index != len(rules) - 1:
                errors.append(f"{exc_type}: unconditional rule {rid} shadows later rules")

    unused = preds - used - GATE_ONLY_PREDICATES
    if unused:
        errors.append(f"predicates never used by a rule: {sorted(unused)}")

    params = policy["parameters"]
    ceilings = [tier["up_to_gbp"] for tier in params["approver_tiers"]]
    finite = ceilings[:-1]
    if ceilings[-1] is not None or any(c is None for c in finite):
        errors.append("only the last approver tier may be open ended")
    elif any(a >= b for a, b in itertools.pairwise(finite)):
        errors.append("approver tier ceilings must be strictly increasing")
    elif params["autonomy"]["agent_auto_approve_limit_gbp"] > finite[1]:
        errors.append("auto-approve limit must not exceed the ap_supervisor tier")

    return errors


def load_valid_policy(path: Path = POLICY_PATH) -> PolicyDict:
    policy = load_policy(path)
    errors = validate_policy(policy)
    if errors:
        raise PolicyError(errors)
    return policy
