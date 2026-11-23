"""Deterministic policy engine (ADR-001, ADR-014).

Every predicate named in policy/policy.yaml is implemented here exactly once. The generator uses
the engine to label cases, and the runtime write gate uses it to check actions. Money is Decimal
throughout. Name similarity uses the standard library only.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from difflib import SequenceMatcher
from functools import cached_property
from typing import cast

from invoice_agent.models import (
    Action,
    Ambiguity,
    ExceptionCase,
    ExceptionType,
    Invoice,
    PurchaseOrder,
    StoredInvoice,
    Supplier,
    Urgency,
    World,
)
from invoice_agent.policy_file import PolicyDict, PolicyError, load_valid_policy

# --------------------------------------------------------------------------- parameters


def _d(value: float | int | str) -> Decimal:
    return Decimal(str(value))


@dataclass(frozen=True)
class PolicyParams:
    rounding_tolerance: Decimal
    price_pct: Decimal
    price_abs: Decimal
    price_dispute_pct: Decimal
    qty_pct: Decimal
    qty_abs: Decimal
    name_min_ratio: float
    exact_window_days: int
    near_window_days: int
    grace_days: int
    po_exempt_categories: frozenset[str]
    auto_approve_limit: Decimal
    approver_tiers: tuple[tuple[str, Decimal | None], ...]
    urgency_critical_days: int
    urgency_high_days: int
    urgency_normal_days: int

    @classmethod
    def from_policy(cls, policy: PolicyDict) -> PolicyParams:
        par = policy["parameters"]
        tiers = tuple(
            (t["tier"], None if t["up_to_gbp"] is None else _d(t["up_to_gbp"]))
            for t in par["approver_tiers"]
        )
        urgency = par["urgency_days_to_due"]
        return cls(
            rounding_tolerance=_d(par["rounding_tolerance_gbp"]),
            price_pct=_d(par["price"]["tolerance_pct_of_line"]),
            price_abs=_d(par["price"]["tolerance_abs_per_invoice_gbp"]),
            price_dispute_pct=_d(par["price"]["dispute_above_pct"]),
            qty_pct=_d(par["quantity"]["over_billing_tolerance_pct_of_received"]),
            qty_abs=_d(par["quantity"]["over_billing_tolerance_abs_per_invoice_gbp"]),
            name_min_ratio=float(par["supplier"]["name_match_min_ratio"]),
            exact_window_days=int(par["duplicate"]["exact_window_days"]),
            near_window_days=int(par["duplicate"]["near_duplicate_window_days"]),
            grace_days=int(par["partial_delivery"]["grace_days_after_promised_date"]),
            po_exempt_categories=frozenset(par["po_exempt_categories"]),
            auto_approve_limit=_d(par["autonomy"]["agent_auto_approve_limit_gbp"]),
            approver_tiers=tiers,
            urgency_critical_days=int(urgency["critical"]),
            urgency_high_days=int(urgency["high"]),
            urgency_normal_days=int(urgency["normal"]),
        )


# --------------------------------------------------------------------------- normalisation

_NAME_SUFFIXES = {
    "limited": "ltd",
    "incorporated": "inc",
    "company": "co",
    "corporation": "corp",
}


def normalise_name(name: str) -> str:
    """Lowercase, strip punctuation, unify company suffixes, drop 'the', sort tokens."""
    cleaned = re.sub(r"[^a-z0-9 ]+", " ", name.lower())
    tokens = [_NAME_SUFFIXES.get(tok, tok) for tok in cleaned.split() if tok != "the"]
    return " ".join(sorted(tokens))


def name_similarity(a: str, b: str) -> float:
    """Symmetric token-sort similarity on a 0 to 100 scale (standard library SequenceMatcher)."""
    first, second = sorted(
        (normalise_name(a), normalise_name(b))
    )  # SequenceMatcher is not symmetric
    return SequenceMatcher(None, first, second).ratio() * 100


def normalise_invoice_number(raw: str) -> str:
    """Uppercase, drop separators, drop leading zeros after the letter prefix."""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", raw).upper()
    match = re.match(r"^([A-Z]*)0*(\d.*)$", cleaned)
    return match.group(1) + match.group(2) if match else cleaned


def _compact(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value).upper()


# --------------------------------------------------------------------------- context


@dataclass(frozen=True)
class LinePriceDiff:
    line_no: int
    sku: str
    po_price: Decimal
    inv_price: Decimal
    quantity: int
    unit_diff: Decimal
    pct: Decimal
    value_diff: Decimal


@dataclass(frozen=True)
class LineQty:
    line_no: int
    ordered: int
    received: int
    invoiced: int
    unit_price: Decimal
    receipt_count: int


class CaseContext:
    """A case, its world and the policy parameters, with derived facts computed once."""

    def __init__(self, case: ExceptionCase, world: World, params: PolicyParams) -> None:
        self.case = case
        self.world = world
        self.params = params

    @property
    def invoice(self) -> Invoice:
        return self.case.invoice

    @cached_property
    def po(self) -> PurchaseOrder | None:
        ref = self.invoice.po_reference
        return None if ref is None else self.world.purchase_orders.get(ref)

    @cached_property
    def reference_supplier(self) -> Supplier | None:
        supplier_id = self.po.supplier_id if self.po is not None else self.invoice.supplier_id
        return self.world.suppliers.get(supplier_id)

    @cached_property
    def other_stored(self) -> tuple[StoredInvoice, ...]:
        own = self.invoice.invoice_id
        return tuple(s for s in self.world.invoice_store if s.invoice.invoice_id != own)

    @cached_property
    def price_diffs(self) -> tuple[LinePriceDiff, ...]:
        po = self.po
        if po is None:
            return ()
        diffs: list[LinePriceDiff] = []
        for line in self.invoice.lines:
            po_line = po.line(line.line_no)
            if po_line is None:
                continue
            unit_diff = abs(line.unit_price - po_line.unit_price)
            if po_line.unit_price == 0:
                pct = Decimal(0) if unit_diff == 0 else Decimal(1000)
            else:
                pct = unit_diff / po_line.unit_price * 100
            diffs.append(
                LinePriceDiff(
                    line_no=line.line_no,
                    sku=po_line.sku,
                    po_price=po_line.unit_price,
                    inv_price=line.unit_price,
                    quantity=line.quantity,
                    unit_diff=unit_diff,
                    pct=pct,
                    value_diff=unit_diff * line.quantity,
                )
            )
        return tuple(diffs)

    def price_sources(self, diff: LinePriceDiff) -> set[Decimal]:
        """Valid prices for a line: price list as of the order date plus approved change orders."""
        po = self.po
        if po is None:
            return set()
        entries = [
            e
            for e in self.world.price_list
            if e.supplier_id == po.supplier_id
            and e.sku == diff.sku
            and e.effective_from <= po.order_date
        ]
        prices: set[Decimal] = set()
        if entries:
            latest = max(e.effective_from for e in entries)
            prices |= {e.unit_price for e in entries if e.effective_from == latest}
        prices |= {
            c.new_unit_price
            for c in self.world.change_orders
            if c.po_id == po.po_id and c.line_no == diff.line_no and c.approved
        }
        return prices

    @cached_property
    def line_qtys(self) -> tuple[LineQty, ...]:
        po = self.po
        if po is None:
            return ()
        out: list[LineQty] = []
        for line in self.invoice.lines:
            po_line = po.line(line.line_no)
            if po_line is None:
                continue
            out.append(
                LineQty(
                    line_no=line.line_no,
                    ordered=po_line.ordered_qty,
                    received=po.received_qty(line.line_no),
                    invoiced=line.quantity,
                    unit_price=line.unit_price,
                    receipt_count=len(po.receipts_for(line.line_no)),
                )
            )
        return tuple(out)

    @cached_property
    def over_billed(self) -> tuple[LineQty, ...]:
        return tuple(ln for ln in self.line_qtys if ln.invoiced > ln.received)

    @cached_property
    def candidate_pos(self) -> tuple[PurchaseOrder, ...]:
        inv = self.invoice
        net = inv.net_total
        found: list[PurchaseOrder] = []
        for po in self.world.purchase_orders.values():
            if po.status != "open" or po.supplier_id != inv.supplier_id:
                continue
            if po.order_date > inv.invoice_date:
                continue
            value = po.open_value
            diff = abs(net - value)
            if diff <= value * self.params.price_pct / 100 and diff <= self.params.price_abs:
                found.append(po)
        return tuple(found)


# --------------------------------------------------------------------------- predicates

Predicate = Callable[[CaseContext], bool]


def _on_watchlist(ctx: CaseContext) -> bool:
    supplier = ctx.reference_supplier
    return supplier is not None and supplier.on_watchlist


def _above_limit(ctx: CaseContext) -> bool:
    return ctx.invoice.gross_total > ctx.params.auto_approve_limit


def _price_within_rounding(ctx: CaseContext) -> bool:
    diffs = ctx.price_diffs
    total = sum((d.value_diff for d in diffs), Decimal(0))
    return bool(diffs) and total <= ctx.params.rounding_tolerance


def _price_within_tolerance(ctx: CaseContext) -> bool:
    diffs = ctx.price_diffs
    total = sum((d.value_diff for d in diffs), Decimal(0))
    return (
        bool(diffs)
        and all(d.pct <= ctx.params.price_pct for d in diffs)
        and total <= ctx.params.price_abs
    )


def _price_change_evidenced(ctx: CaseContext) -> bool:
    differing = [d for d in ctx.price_diffs if d.unit_diff > 0]
    return bool(differing) and all(d.inv_price in ctx.price_sources(d) for d in differing)


def _price_evidence_conflicting(ctx: CaseContext) -> bool:
    differing = [d for d in ctx.price_diffs if d.unit_diff > 0]
    return any(len(ctx.price_sources(d)) >= 2 for d in differing)


def _price_above_dispute_limit(ctx: CaseContext) -> bool:
    over = any(d.pct > ctx.params.price_dispute_pct for d in ctx.price_diffs)
    return over and not _price_change_evidenced(ctx)


def _norm_duplicate_window(ctx: CaseContext, other: StoredInvoice, days: int) -> bool:
    return abs((ctx.invoice.invoice_date - other.invoice.invoice_date).days) <= days


def _same_supplier_and_number(ctx: CaseContext, other: StoredInvoice) -> bool:
    return other.invoice.supplier_id == ctx.invoice.supplier_id and (
        normalise_invoice_number(other.invoice.invoice_number)
        == normalise_invoice_number(ctx.invoice.invoice_number)
    )


def _exact_duplicate(ctx: CaseContext) -> bool:
    return any(
        s.status in ("approved", "paid")
        and _same_supplier_and_number(ctx, s)
        and s.invoice.gross_total == ctx.invoice.gross_total
        and _norm_duplicate_window(ctx, s, ctx.params.exact_window_days)
        for s in ctx.other_stored
    )


def _same_number_different_amount(ctx: CaseContext) -> bool:
    return any(
        s.status in ("approved", "paid")
        and _same_supplier_and_number(ctx, s)
        and s.invoice.gross_total != ctx.invoice.gross_total
        and _norm_duplicate_window(ctx, s, ctx.params.exact_window_days)
        for s in ctx.other_stored
    )


def _po_line_set(invoice: Invoice) -> frozenset[tuple[str, int]]:
    if invoice.po_reference is None:
        return frozenset()
    return frozenset((invoice.po_reference, ln.line_no) for ln in invoice.lines)


def _near_duplicate(ctx: CaseContext) -> bool:
    mine = _po_line_set(ctx.invoice)
    return bool(mine) and any(
        s.invoice.supplier_id == ctx.invoice.supplier_id
        and s.invoice.gross_total == ctx.invoice.gross_total
        and _po_line_set(s.invoice) == mine
        and not _same_supplier_and_number(ctx, s)
        and _norm_duplicate_window(ctx, s, ctx.params.near_window_days)
        for s in ctx.other_stored
    )


def _not_a_duplicate(ctx: CaseContext) -> bool:
    return not (_exact_duplicate(ctx) or _same_number_different_amount(ctx) or _near_duplicate(ctx))


def _supplier_record_unavailable(ctx: CaseContext) -> bool:
    supplier = ctx.reference_supplier
    return supplier is None or supplier.record_status == "unreadable"


def _po_record_unavailable(ctx: CaseContext) -> bool:
    return ctx.po is None


def _readable_supplier(ctx: CaseContext) -> Supplier | None:
    supplier = ctx.reference_supplier
    return None if supplier is None or supplier.record_status == "unreadable" else supplier


def _bank_mismatch(ctx: CaseContext) -> bool:
    supplier = _readable_supplier(ctx)
    return supplier is not None and _compact(ctx.invoice.supplier_bank) != _compact(
        supplier.bank_account
    )


def _vat_mismatch(ctx: CaseContext) -> bool:
    supplier = _readable_supplier(ctx)
    return supplier is not None and _compact(ctx.invoice.supplier_vat) != _compact(
        supplier.vat_number
    )


def _name_matches(ctx: CaseContext, supplier: Supplier) -> bool:
    candidates = (supplier.legal_name, *supplier.aliases)
    return any(
        name_similarity(ctx.invoice.supplier_name, c) >= ctx.params.name_min_ratio
        for c in candidates
    )


def _name_normalised_match(ctx: CaseContext) -> bool:
    supplier = ctx.reference_supplier
    return supplier is not None and _name_matches(ctx, supplier)


def _name_matches_other_record(ctx: CaseContext) -> bool:
    reference = ctx.reference_supplier
    if reference is None or _name_matches(ctx, reference):
        return False
    return any(
        _name_matches(ctx, other)
        for other in ctx.world.suppliers.values()
        if other.supplier_id != reference.supplier_id
    )


def _address_only_difference(ctx: CaseContext) -> bool:
    supplier = ctx.reference_supplier
    return (
        supplier is not None
        and _name_matches(ctx, supplier)
        and not _vat_mismatch(ctx)
        and not _bank_mismatch(ctx)
        and _compact(ctx.invoice.supplier_address) != _compact(supplier.address)
    )


def _qty_le_received(ctx: CaseContext) -> bool:
    return bool(ctx.line_qtys) and not ctx.over_billed


def _over_billing_within_tolerance(ctx: CaseContext) -> bool:
    over = ctx.over_billed
    if not over:
        return False
    pct_ok = all(
        ln.received > 0
        and Decimal(ln.invoiced - ln.received) / Decimal(ln.received) * 100 <= ctx.params.qty_pct
        for ln in over
    )
    value = sum((Decimal(ln.invoiced - ln.received) * ln.unit_price for ln in over), Decimal(0))
    return pct_ok and value <= ctx.params.qty_abs


def _over_billing_beyond(ctx: CaseContext) -> bool:
    return bool(ctx.over_billed) and not _over_billing_within_tolerance(ctx)


def _beyond_no_receipt(ctx: CaseContext) -> bool:
    return _over_billing_beyond(ctx) and any(ln.receipt_count == 0 for ln in ctx.over_billed)


def _beyond_receipt_present(ctx: CaseContext) -> bool:
    return _over_billing_beyond(ctx) and all(ln.receipt_count > 0 for ln in ctx.over_billed)


def _any_partial(ctx: CaseContext) -> bool:
    return any(0 < ln.received < ln.ordered for ln in ctx.line_qtys)


def _partial_matches_received(ctx: CaseContext) -> bool:
    """Every invoiced line equals its received quantity and at least one line is partial."""
    lines = ctx.line_qtys
    return bool(lines) and all(ln.invoiced == ln.received for ln in lines) and _any_partial(ctx)


def _full_order_while_partial(ctx: CaseContext) -> bool:
    """Every invoiced line bills the full ordered quantity and at least one line is partial."""
    lines = ctx.line_qtys
    return bool(lines) and all(ln.invoiced == ln.ordered for ln in lines) and _any_partial(ctx)


def _full_order_within_grace(ctx: CaseContext) -> bool:
    po = ctx.po
    return (
        po is not None
        and _full_order_while_partial(ctx)
        and ctx.case.case_date <= po.promised_date + timedelta(days=ctx.params.grace_days)
    )


def _full_order_beyond_grace(ctx: CaseContext) -> bool:
    po = ctx.po
    return (
        po is not None
        and _full_order_while_partial(ctx)
        and ctx.case.case_date > po.promised_date + timedelta(days=ctx.params.grace_days)
    )


def _receipt_records_conflict(ctx: CaseContext) -> bool:
    po = ctx.po
    if po is None:
        return False
    for line in ctx.invoice.lines:
        quantities: dict[str, set[int]] = {}
        for receipt in po.receipts_for(line.line_no):
            quantities.setdefault(receipt.delivery_ref, set()).add(receipt.quantity)
        if any(len(q) > 1 for q in quantities.values()):
            return True
    return False


PREDICATES: dict[str, Predicate] = {
    "is_po_exempt_category": lambda c: c.invoice.category in c.params.po_exempt_categories,
    "supplier_on_watchlist": _on_watchlist,
    "amount_above_auto_approve_limit": _above_limit,
    "supplier_record_unavailable": _supplier_record_unavailable,
    "po_record_unavailable": _po_record_unavailable,
    "price_diff_within_rounding": _price_within_rounding,
    "price_within_tolerance": _price_within_tolerance,
    "price_above_dispute_limit": _price_above_dispute_limit,
    "price_change_evidenced": _price_change_evidenced,
    "price_evidence_conflicting": _price_evidence_conflicting,
    "no_candidate_po": lambda c: len(c.candidate_pos) == 0,
    "one_candidate_po": lambda c: len(c.candidate_pos) == 1,
    "multiple_candidate_pos": lambda c: len(c.candidate_pos) > 1,
    "exact_duplicate": _exact_duplicate,
    "same_number_different_amount": _same_number_different_amount,
    "near_duplicate_different_number": _near_duplicate,
    "not_a_duplicate": _not_a_duplicate,
    "bank_details_mismatch": _bank_mismatch,
    "vat_number_mismatch": _vat_mismatch,
    "supplier_name_normalised_match": _name_normalised_match,
    "supplier_name_matches_other_master_record": _name_matches_other_record,
    "address_only_difference": _address_only_difference,
    "invoice_qty_le_received": _qty_le_received,
    "over_billing_within_tolerance": _over_billing_within_tolerance,
    "over_billing_beyond_tolerance_receipt_present": _beyond_receipt_present,
    "over_billing_beyond_tolerance_no_receipt": _beyond_no_receipt,
    "partial_invoice_matches_received": _partial_matches_received,
    "partial_invoice_for_full_order_within_grace": _full_order_within_grace,
    "partial_invoice_for_full_order_beyond_grace": _full_order_beyond_grace,
    "receipt_records_conflict": _receipt_records_conflict,
}

# --------------------------------------------------------------------------- engine


@dataclass(frozen=True)
class Resolution:
    primary_type: ExceptionType
    secondary_flags: tuple[ExceptionType, ...]
    urgency: Urgency
    rule_id: str
    action: Action
    ambiguity: Ambiguity
    requires_human_approval: bool
    approver_tier: str
    expected_clauses: tuple[str, ...]
    required_tools: tuple[str, ...]


class PolicyEngine:
    def __init__(self, policy: PolicyDict | None = None) -> None:
        self.policy: PolicyDict = policy if policy is not None else load_valid_policy()
        mismatch = set(self.policy["predicates"]) ^ set(PREDICATES)
        if mismatch:
            raise PolicyError([f"predicate registry and policy file differ: {sorted(mismatch)}"])
        self.params = PolicyParams.from_policy(self.policy)
        self._rules: dict[str, list[dict[str, object]]] = self.policy["rules"]
        self._precedence: list[ExceptionType] = list(
            self.policy["taxonomy"]["precedence_when_multiple_issues"]
        )
        self._required_tools: dict[str, list[str]] = self.policy["taxonomy"]["required_read_tools"]

    def context(self, case: ExceptionCase, world: World) -> CaseContext:
        return CaseContext(case, world, self.params)

    def evaluate_all(self, ctx: CaseContext) -> dict[str, bool]:
        """Every predicate for a case, for diagnostics and explanations."""
        return {name: fn(ctx) for name, fn in PREDICATES.items()}

    def urgency(self, case: ExceptionCase) -> Urgency:
        days = (case.invoice.due_date - case.case_date).days
        p = self.params
        if days <= p.urgency_critical_days:
            return "critical"
        if days <= p.urgency_high_days:
            return "high"
        if days <= p.urgency_normal_days:
            return "normal"
        return "low"

    def approver_tier(self, gross: Decimal) -> str:
        for tier, ceiling in self.params.approver_tiers:
            if ceiling is None or gross <= ceiling:
                return tier
        raise PolicyError(["approver tiers have no open-ended last tier"])

    def resolve(
        self, case: ExceptionCase, world: World, issues: Sequence[ExceptionType]
    ) -> Resolution:
        """Expected resolution for a case whose injected issue types are `issues`."""
        if not issues:
            raise ValueError("at least one issue type is required")
        ctx = self.context(case, world)
        bank_mismatch = _bank_mismatch(ctx)
        declared = set(issues)
        if bank_mismatch:
            declared.add("wrong_supplier_details")  # G-3 makes this the primary issue
        ordered = [t for t in self._precedence if t in declared]
        primary, secondary = ordered[0], tuple(ordered[1:])

        rule = self._match_rule(primary, ctx)
        action = cast(Action, rule["action"])
        ambiguity = cast(Ambiguity, rule.get("ambiguity", "none"))

        clauses = [cast(str, rule["id"])]
        human = action in ("raise_dispute", "escalate")
        if action == "raise_dispute":
            clauses.append("G-2")
        if action == "approve_within_tolerance" and (_above_limit(ctx) or _on_watchlist(ctx)):
            human = True
            clauses.append("G-1")
        if bank_mismatch:
            human = True
            clauses.append("G-3")

        return Resolution(
            primary_type=primary,
            secondary_flags=secondary,
            urgency=self.urgency(case),
            rule_id=cast(str, rule["id"]),
            action=action,
            ambiguity=ambiguity,
            requires_human_approval=human,
            approver_tier=self.approver_tier(case.invoice.gross_total),
            expected_clauses=tuple(clauses),
            required_tools=tuple(self._required_tools[primary]),
        )

    def _match_rule(self, exc_type: str, ctx: CaseContext) -> dict[str, object]:
        for rule in self._rules[exc_type]:
            names = cast(list[str], rule["when"])
            if all(PREDICATES[name](ctx) for name in names):
                return rule
        raise PolicyError([f"{exc_type}: no rule matched and no fallback exists"])
