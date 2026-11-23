from __future__ import annotations

import typing
from datetime import date, timedelta
from decimal import Decimal

import pytest

from invoice_agent import models
from invoice_agent.models import InvoiceLine, PurchaseOrderLine
from invoice_agent.policy_engine import (
    PREDICATES,
    PolicyEngine,
    name_similarity,
    normalise_invoice_number,
    normalise_name,
)
from invoice_agent.policy_file import load_valid_policy
from tests import factories as f

D = Decimal

# rule id -> (action, ambiguity)
EXPECTED: dict[str, tuple[str, str]] = {
    "PM-1": ("approve_within_tolerance", "none"),
    "PM-2": ("approve_within_tolerance", "none"),
    "PM-3": ("escalate", "conflicting_evidence"),
    "PM-4": ("route_to_buyer", "none"),
    "PM-5": ("raise_dispute", "none"),
    "PM-6": ("request_correction", "none"),
    "MP-1": ("approve_within_tolerance", "none"),
    "MP-2": ("route_to_buyer", "none"),
    "MP-3": ("escalate", "conflicting_evidence"),
    "MP-4": ("request_correction", "none"),
    "DU-1": ("raise_dispute", "none"),
    "DU-2": ("request_correction", "none"),
    "DU-3": ("escalate", "conflicting_evidence"),
    "DU-4": ("approve_within_tolerance", "none"),
    "SD-1": ("raise_dispute", "none"),
    "SD-2": ("request_correction", "none"),
    "SD-3": ("escalate", "conflicting_evidence"),
    "SD-4": ("route_to_buyer", "none"),
    "SD-5": ("approve_within_tolerance", "none"),
    "SD-9": ("escalate", "policy_gap"),
    "QM-1": ("approve_within_tolerance", "none"),
    "QM-2": ("approve_within_tolerance", "none"),
    "QM-3": ("route_to_buyer", "none"),
    "QM-4": ("request_correction", "none"),
    "PD-1": ("escalate", "conflicting_evidence"),
    "PD-2": ("approve_within_tolerance", "none"),
    "PD-3": ("route_to_buyer", "none"),
    "PD-4": ("raise_dispute", "none"),
    "PD-9": ("escalate", "policy_gap"),
    "QM-9": ("escalate", "policy_gap"),
    "PM-E1": ("escalate", "missing_evidence"),
    "PM-E2": ("escalate", "missing_evidence"),
    "MP-E1": ("escalate", "missing_evidence"),
    "DU-E1": ("escalate", "missing_evidence"),
    "SD-E1": ("escalate", "missing_evidence"),
    "QM-E1": ("escalate", "missing_evidence"),
    "QM-E2": ("escalate", "missing_evidence"),
    "PD-E1": ("escalate", "missing_evidence"),
    "PD-E2": ("escalate", "missing_evidence"),
}
# Fallback rules that no input can reach, because earlier rules already cover every case.
UNREACHABLE_BY_CONSTRUCTION = {"MP-9", "DU-9"}


@pytest.fixture(scope="module")
def engine() -> PolicyEngine:
    return PolicyEngine()


def all_rule_ids() -> set[str]:
    policy = load_valid_policy()
    return {r["id"] for rules in policy["rules"].values() for r in rules}


def test_every_rule_has_a_scenario_or_is_documented_unreachable() -> None:
    assert set(EXPECTED) | UNREACHABLE_BY_CONSTRUCTION == all_rule_ids()
    assert set(f.rule_scenarios()) == set(EXPECTED)


@pytest.mark.parametrize("rule_id", sorted(EXPECTED))
def test_rule_fires_exactly_as_specified(engine: PolicyEngine, rule_id: str) -> None:
    sc = f.rule_scenarios()[rule_id]
    result = engine.resolve(sc.case, sc.world, sc.issues)
    action, ambiguity = EXPECTED[rule_id]
    assert result.rule_id == rule_id
    assert result.action == action
    assert result.ambiguity == ambiguity
    assert result.expected_clauses[0] == rule_id
    assert result.primary_type == sc.issues[0]


def test_base_invoice_has_no_open_issue_flags(engine: PolicyEngine) -> None:
    sc = f.scenario("price_mismatch")
    ctx = engine.context(sc.case, sc.world)
    flags = engine.evaluate_all(ctx)
    assert flags["price_diff_within_rounding"]  # zero difference is within rounding
    assert not flags["bank_details_mismatch"]
    assert not flags["vat_number_mismatch"]
    assert not flags["exact_duplicate"]


def test_predicate_registry_matches_policy_file() -> None:
    assert set(PREDICATES) == set(load_valid_policy()["predicates"])


def test_models_literals_match_policy_taxonomy() -> None:
    tax = load_valid_policy()["taxonomy"]
    assert set(typing.get_args(models.ExceptionType)) == set(tax["exception_types"])
    assert set(typing.get_args(models.Action)) == set(tax["actions"])
    assert set(typing.get_args(models.Ambiguity)) == set(tax["ambiguity_kinds"])
    assert set(typing.get_args(models.Urgency)) == set(tax["urgency_levels"])


def test_every_ambiguity_kind_is_reachable(engine: PolicyEngine) -> None:
    seen = {
        engine.resolve(sc.case, sc.world, sc.issues).ambiguity for sc in f.rule_scenarios().values()
    }
    assert seen == set(typing.get_args(models.Ambiguity))


def test_unreadable_supplier_record_cannot_trigger_bank_mismatch(engine: PolicyEngine) -> None:
    sc = f.rule_scenarios()["SD-E1"]
    result = engine.resolve(sc.case, sc.world, sc.issues)
    assert result.rule_id == "SD-E1"
    assert "G-3" not in result.expected_clauses  # cannot verify a bank mismatch without the record
    assert result.requires_human_approval


def test_missing_supplier_record_is_missing_evidence(engine: PolicyEngine) -> None:
    sc = f.scenario("price_mismatch", world=f.world_with(suppliers={"S2": f.supplier_two()}))
    result = engine.resolve(sc.case, sc.world, sc.issues)
    assert result.rule_id == "PM-E1"
    assert result.ambiguity == "missing_evidence"


# ------------------------------------------------------------------ global controls


def test_g1_above_auto_approve_limit_needs_human(engine: PolicyEngine) -> None:
    sc = f.scenario("duplicate_invoice", invoice=f.with_prices(f.base_invoice(), "30.00"))
    result = engine.resolve(sc.case, sc.world, sc.issues)
    assert result.rule_id == "DU-4"
    assert result.action == "approve_within_tolerance"
    assert sc.case.invoice.gross_total > D("2500")
    assert result.requires_human_approval
    assert "G-1" in result.expected_clauses


def test_g1_watchlist_supplier_needs_human(engine: PolicyEngine) -> None:
    flagged = f.supplier_one().model_copy(update={"on_watchlist": True})
    world = f.world_with(suppliers={"S1": flagged, "S2": f.supplier_two()})
    sc = f.scenario("duplicate_invoice", world=world)
    result = engine.resolve(sc.case, sc.world, sc.issues)
    assert result.action == "approve_within_tolerance"
    assert result.requires_human_approval
    assert "G-1" in result.expected_clauses


def test_clean_approval_under_limit_needs_no_human(engine: PolicyEngine) -> None:
    sc = f.scenario("duplicate_invoice")
    result = engine.resolve(sc.case, sc.world, sc.issues)
    assert result.action == "approve_within_tolerance"
    assert not result.requires_human_approval
    assert result.expected_clauses == ("DU-4",)


def test_g2_raise_dispute_always_needs_human(engine: PolicyEngine) -> None:
    sc = f.rule_scenarios()["PD-4"]
    result = engine.resolve(sc.case, sc.world, sc.issues)
    assert result.action == "raise_dispute"
    assert result.requires_human_approval
    assert "G-2" in result.expected_clauses


def test_g3_bank_mismatch_overrides_declared_type(engine: PolicyEngine) -> None:
    bad_bank = f.base_invoice().model_copy(update={"supplier_bank": "99-99-99 11111111"})
    sc = f.scenario("price_mismatch", invoice=bad_bank)
    result = engine.resolve(sc.case, sc.world, sc.issues)
    assert result.primary_type == "wrong_supplier_details"
    assert result.secondary_flags == ("price_mismatch",)
    assert result.rule_id == "SD-1"
    assert result.requires_human_approval
    assert "G-3" in result.expected_clauses


def test_precedence_picks_highest_issue(engine: PolicyEngine) -> None:
    sc = f.rule_scenarios()["DU-1"]
    result = engine.resolve(sc.case, sc.world, ("price_mismatch", "duplicate_invoice"))
    assert result.primary_type == "duplicate_invoice"
    assert result.secondary_flags == ("price_mismatch",)
    assert result.rule_id == "DU-1"


def test_resolve_requires_an_issue(engine: PolicyEngine) -> None:
    sc = f.scenario("price_mismatch")
    with pytest.raises(ValueError, match="at least one"):
        engine.resolve(sc.case, sc.world, ())


# ------------------------------------------------------------------ boundaries


def test_price_tolerance_percentage_boundary(engine: PolicyEngine) -> None:
    at_limit = f.scenario("price_mismatch", invoice=f.with_prices(f.base_invoice(), "10.20"))
    over = f.scenario("price_mismatch", invoice=f.with_prices(f.base_invoice(), "10.21"))
    assert engine.resolve(at_limit.case, at_limit.world, at_limit.issues).rule_id == "PM-2"
    assert engine.resolve(over.case, over.world, over.issues).rule_id == "PM-6"


def test_price_tolerance_absolute_boundary(engine: PolicyEngine) -> None:
    big_line = PurchaseOrderLine(
        line_no=1, sku="FST-100", description="bulk", ordered_qty=5000, unit_price=D("10.00")
    )
    po = f.purchase_order().model_copy(update={"lines": (big_line,)})
    world = f.world_with(pos={"PO1": po})

    def run(price: str) -> str:
        inv = f.base_invoice().model_copy(
            update={
                "lines": (
                    InvoiceLine(line_no=1, sku="FST-100", quantity=5000, unit_price=D(price)),
                )
            }
        )
        sc = f.scenario("price_mismatch", invoice=inv, world=world)
        return engine.resolve(sc.case, sc.world, sc.issues).rule_id

    assert run("10.01") == "PM-2"  # 50.00 exactly
    assert run("10.0101") == "PM-6"  # 50.50


def test_over_billing_percentage_boundary(engine: PolicyEngine) -> None:
    at = f.scenario("quantity_mismatch", invoice=f.with_qty(f.base_invoice(), 102))
    over = f.scenario("quantity_mismatch", invoice=f.with_qty(f.base_invoice(), 103))
    assert engine.resolve(at.case, at.world, at.issues).rule_id == "QM-2"
    assert engine.resolve(over.case, over.world, over.issues).rule_id == "QM-4"


def test_grace_period_boundary(engine: PolicyEngine) -> None:
    partial = {"PO1": f.purchase_order(rcpts=f.receipts(qty1=60))}
    last_day = date(2026, 1, 20) + timedelta(days=14)
    on = f.scenario("partial_delivery", world=f.world_with(pos=partial), case_date=last_day)
    after = f.scenario(
        "partial_delivery",
        world=f.world_with(pos=partial),
        case_date=last_day + timedelta(days=1),
    )
    assert engine.resolve(on.case, on.world, on.issues).rule_id == "PD-3"
    assert engine.resolve(after.case, after.world, after.issues).rule_id == "PD-4"


@pytest.mark.parametrize(
    ("gross", "tier"),
    [
        ("0.01", "ap_clerk"),
        ("1000.00", "ap_clerk"),
        ("1000.01", "ap_supervisor"),
        ("10000.00", "ap_supervisor"),
        ("10000.01", "finance_manager"),
        ("50000.00", "finance_manager"),
        ("50000.01", "finance_director"),
    ],
)
def test_approver_tier_boundaries(engine: PolicyEngine, gross: str, tier: str) -> None:
    assert engine.approver_tier(D(gross)) == tier


@pytest.mark.parametrize(
    ("days_to_due", "urgency"),
    [
        (-30, "critical"),
        (0, "critical"),
        (2, "critical"),
        (3, "high"),
        (5, "high"),
        (6, "normal"),
        (14, "normal"),
        (15, "low"),
        (90, "low"),
    ],
)
def test_urgency_boundaries(engine: PolicyEngine, days_to_due: int, urgency: str) -> None:
    case_date = date(2026, 2, 10)
    inv = f.base_invoice().model_copy(update={"due_date": case_date + timedelta(days=days_to_due)})
    sc = f.scenario("price_mismatch", invoice=inv, case_date=case_date)
    assert engine.urgency(sc.case) == urgency


def test_required_tools_follow_primary_type(engine: PolicyEngine) -> None:
    sc = f.rule_scenarios()["DU-1"]
    result = engine.resolve(sc.case, sc.world, sc.issues)
    assert result.required_tools == ("search_invoices", "retrieve_policy")


# ------------------------------------------------------------------ normalisation helpers


def test_invoice_number_normalisation() -> None:
    assert normalise_invoice_number("INV-01001") == "INV1001"
    assert normalise_invoice_number("inv 1001") == "INV1001"
    assert normalise_invoice_number("00123") == "123"
    assert normalise_invoice_number("INV-0") == "INV0"
    assert normalise_invoice_number("INV-1000") == "INV1000"


def test_name_normalisation_and_similarity() -> None:
    assert normalise_name("The Acme Fasteners Limited.") == normalise_name("ACME FASTENERS LTD")
    assert name_similarity("Acme Fasteners Ltd", "ACME FASTENERS LIMITED.") == pytest.approx(100.0)
    assert name_similarity("Acme Fasteners Ltd", "Birch Packaging Ltd") < 90


def test_money_properties_round_half_up() -> None:
    inv = f.with_prices(f.base_invoice(), "10.0050", "20.00")
    assert inv.net_total == D("2000.50")  # 100 x 10.0050 = 1000.50, plus 1000.00
    assert inv.vat_amount == D("400.10")
    assert inv.gross_total == D("2400.60")


def test_auto_approve_limit_boundary(engine: PolicyEngine) -> None:
    def run(unit_price: str) -> tuple[Decimal, bool]:
        line = InvoiceLine(line_no=1, sku="FST-100", quantity=1, unit_price=D(unit_price))
        inv = f.base_invoice().model_copy(update={"lines": (line,)})
        sc = f.scenario("duplicate_invoice", invoice=inv)
        result = engine.resolve(sc.case, sc.world, sc.issues)
        assert result.rule_id == "DU-4"
        return inv.gross_total, result.requires_human_approval

    assert run("2083.33") == (D("2500.00"), False)  # exactly at the limit: no human needed
    assert run("2083.34") == (D("2500.01"), True)  # one penny over: human approval (G-1)


def test_name_similarity_is_symmetric() -> None:
    from itertools import combinations

    from invoice_agent.generator import DEFAULT_SEED, make_supplier_pool

    pool = make_supplier_pool(DEFAULT_SEED)
    for a, b in combinations(pool, 2):
        assert name_similarity(a.legal_name, b.legal_name) == name_similarity(
            b.legal_name, a.legal_name
        )
