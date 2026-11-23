"""Seeded synthetic data generator (ADR-001, ADR-002, ADR-012). All data is synthetic.

Each case is built from a randomised base (supplier, PO, receipts, invoice) and a recipe that
bends it toward one policy rule. Labels always come from the policy engine, never from the
recipe, and every case is verified against the final shared world: if the engine does not return
the rule the recipe intended (for example because another case's PO became a candidate), that
case is regenerated with a different random draw.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from invoice_agent.models import (
    CaseLabels,
    ChangeOrder,
    Dataset,
    ExceptionCase,
    ExceptionType,
    GoodsReceipt,
    Invoice,
    InvoiceLine,
    InvoiceStatus,
    PriceListEntry,
    PurchaseOrder,
    PurchaseOrderLine,
    StoredInvoice,
    Supplier,
    World,
)
from invoice_agent.policy_engine import PolicyEngine, name_similarity, normalise_invoice_number

GENERATOR_VERSION = "1.0.0"
DEFAULT_SEED = 20260122

# Planned case mix: rule id -> number of cases (ADR-002, docs/TAXONOMY.md section 9).
TARGETS: dict[str, int] = {
    "PM-1": 8, "PM-2": 14, "PM-3": 6, "PM-4": 8, "PM-5": 8, "PM-6": 12, "PM-E1": 2, "PM-E2": 2,
    "MP-1": 8, "MP-2": 14, "MP-3": 8, "MP-4": 13, "MP-E1": 2,
    "DU-1": 13, "DU-2": 8, "DU-3": 9, "DU-4": 13, "DU-E1": 2,
    "SD-1": 9, "SD-2": 7, "SD-3": 6, "SD-4": 6, "SD-5": 9, "SD-9": 5, "SD-E1": 3,
    "QM-1": 8, "QM-2": 8, "QM-3": 8, "QM-4": 10, "QM-9": 3, "QM-E1": 1, "QM-E2": 2,
    "PD-1": 6, "PD-2": 11, "PD-3": 10, "PD-4": 10, "PD-9": 5, "PD-E1": 1, "PD-E2": 2,
}  # fmt: skip
TYPE_BY_PREFIX: dict[str, ExceptionType] = {
    "PM": "price_mismatch",
    "MP": "missing_po",
    "DU": "duplicate_invoice",
    "SD": "wrong_supplier_details",
    "QM": "quantity_mismatch",
    "PD": "partial_delivery",
}

POOL_SIZE = 100
MAX_LOCAL_TRIES = 80
MAX_ROUNDS = 25
EPOCH = date(2026, 1, 5)

_WORDS_A = [
    "Acme", "Birch", "Cedar", "Delta", "Elm", "Falcon", "Granite", "Harbour", "Iron", "Juniper",
    "Kestrel", "Linden", "Meridian", "Northern", "Oakley", "Pioneer", "Quarry", "Ridge", "Summit",
    "Tidal", "Union", "Vertex", "Willow", "Yardley", "Zenith", "Albion", "Beacon", "Corvus",
]  # fmt: skip
_WORDS_B = [
    "Fasteners", "Packaging", "Logistics", "Components", "Tooling", "Plastics", "Textiles",
    "Hydraulics", "Electrical", "Chemicals", "Fixings", "Cables", "Bearings", "Castings", "Pumps",
    "Coatings", "Fabrication", "Supplies",
]  # fmt: skip
_STREETS = ["Mill Road", "Canal Street", "High Street", "Station Lane", "Foundry Way", "Park Row"]
_TOWNS = ["Leeds", "Derby", "Bristol", "Sheffield", "Leicester", "Nottingham", "Coventry"]
_DESCRIPTIONS = ["Widget", "Bracket", "Gasket", "Coupling", "Bolt pack", "Cable reel", "Valve"]
_BENIGN_NOTES = [
    "Please pay by month end, thanks.",
    "Second reminder for this invoice.",
    "Goods were delivered to dock 3.",
    "Thank you for your continued business.",
    "Contact accounts if anything is unclear.",
]
_MESSAGES: dict[ExceptionType, list[str]] = {
    "price_mismatch": ["Price variance on matching", "3-way match failed: price"],
    "missing_po": ["No PO reference found", "Invoice cannot be matched to a PO"],
    "duplicate_invoice": ["Possible duplicate detected", "Invoice number already exists"],
    "wrong_supplier_details": [
        "Supplier details differ from master",
        "Payment hold: supplier check",
    ],
    "quantity_mismatch": ["Quantity variance against receipt", "3-way match failed: quantity"],
    "partial_delivery": ["Goods receipt incomplete for PO line", "3-way match failed: receipt"],
}
_GENERIC_MESSAGE = "Invoice held: review required"
_BANK_CHANGE_NOTE = "Our bank details have changed. Please pay the account shown on this invoice."


class Retry(Exception):
    """A recipe could not satisfy its constraints with this random draw."""


# --- helpers


def _quant(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _price(rng: random.Random, low: int, high: int) -> Decimal:
    return Decimal(rng.randint(low * 100, high * 100)) / 100


def _digits(rng: random.Random, n: int) -> str:
    return "".join(str(rng.randint(0, 9)) for _ in range(n))


def _bank(rng: random.Random) -> str:
    return f"{_digits(rng, 2)}-{_digits(rng, 2)}-{_digits(rng, 2)} {_digits(rng, 8)}"


def _address(rng: random.Random) -> str:
    town = rng.choice(_TOWNS)
    area = f"{town[:2].upper()}{rng.randint(1, 20)}"
    code = f"{area} {rng.randint(1, 9)}{rng.choice('ABDE')}{rng.choice('FGHJ')}"
    return f"{rng.randint(1, 99)} {rng.choice(_STREETS)}, {town} {code}"


def make_supplier_pool(seed: int, size: int = POOL_SIZE) -> list[Supplier]:
    rng = random.Random(f"{seed}:pool")  # noqa: S311 - synthetic data, not security
    pool: list[Supplier] = []
    while len(pool) < size:
        base = f"{rng.choice(_WORDS_A)} {rng.choice(_WORDS_B)}"
        legal = f"{base} {rng.choice(['Ltd', 'Limited', 'PLC'])}"
        if any(name_similarity(legal, s.legal_name) >= 80 for s in pool):
            continue
        aliases: tuple[str, ...] = ()
        if rng.random() < 0.5:
            aliases = (f"{base} Limited" if legal.endswith("Ltd") else f"{base} Ltd", base)
        pool.append(
            Supplier(
                supplier_id=f"S{len(pool) + 1:03d}",
                legal_name=legal,
                aliases=aliases,
                vat_number=f"GB{_digits(rng, 9)}",
                bank_account=_bank(rng),
                address=_address(rng),
                on_watchlist=rng.random() < 0.06,
            )
        )
    return pool


@dataclass
class Draft:
    idx: int
    rule_id: str
    supplier: Supplier
    po: PurchaseOrder | None
    invoice: Invoice
    case_date: date
    issues: list[ExceptionType]
    tags: set[str] = field(default_factory=set)
    extra_pos: list[PurchaseOrder] = field(default_factory=list)
    stored: list[StoredInvoice] = field(default_factory=list)
    price_list: list[PriceListEntry] = field(default_factory=list)
    change_orders: list[ChangeOrder] = field(default_factory=list)
    new_suppliers: list[Supplier] = field(default_factory=list)


@dataclass(frozen=True)
class Bundle:
    """Everything one case contributes to the shared world."""

    rule_id: str
    case: ExceptionCase
    issues: tuple[ExceptionType, ...]
    tags: tuple[str, ...]
    pos: tuple[PurchaseOrder, ...]
    stored: tuple[StoredInvoice, ...]
    price_list: tuple[PriceListEntry, ...]
    change_orders: tuple[ChangeOrder, ...]
    new_suppliers: tuple[Supplier, ...]


@dataclass(frozen=True)
class GenContext:
    pool: list[Supplier]
    exempt_categories: tuple[str, ...]


Recipe = Callable[[Draft, random.Random, GenContext], None]


_URGENCY_RANGES = {"critical": (-15, 2), "high": (3, 5), "normal": (6, 14), "low": (15, 45)}
_URGENCY_WEIGHTS = [22, 20, 28, 30]


def _draw_days_to_due(rng: random.Random, terms: int) -> int:
    """Pick days from case date to due date, balanced across the four urgency levels."""
    for _ in range(20):
        low, high = _URGENCY_RANGES[rng.choices(list(_URGENCY_RANGES), _URGENCY_WEIGHTS)[0]]
        days = rng.randint(low, high)
        if 1 <= terms - days <= 75:  # the case arrives 1 to 75 days after the invoice date
            return days
    return 10


def _draw_qty_price(
    rng: random.Random, qty_range: tuple[int, int] | None, price_range: tuple[int, int] | None
) -> tuple[int, Decimal]:
    """Quantity and unit price. By default the line value is log-uniform from 30 to 10,000 GBP."""
    if qty_range is not None and price_range is not None:
        return rng.randint(*qty_range), _price(rng, *price_range)
    value = math.exp(rng.uniform(math.log(30), math.log(10000)))
    qty = int(math.exp(rng.uniform(math.log(5), math.log(400))))
    return qty, max(Decimal("0.50"), _quant(Decimal(str(value)) / qty))


def _make_base(
    rng: random.Random,
    idx: int,
    rule_id: str,
    ctx: GenContext,
    *,
    qty_range: tuple[int, int] | None = None,
    price_range: tuple[int, int] | None = None,
) -> Draft:
    supplier = rng.choice(ctx.pool)
    order_date = EPOCH + timedelta(days=rng.randint(0, 150))
    promised = order_date + timedelta(days=rng.randint(10, 30))
    po_id = f"PO-{idx:04d}"
    gap = (promised - order_date).days
    po_lines: list[PurchaseOrderLine] = []
    receipts: list[GoodsReceipt] = []
    inv_lines: list[InvoiceLine] = []
    for line_no in range(1, rng.choice([1, 2, 2, 3]) + 1):
        sku = f"SKU-{idx:04d}-{line_no}"
        qty, unit = _draw_qty_price(rng, qty_range, price_range)
        po_lines.append(
            PurchaseOrderLine(
                line_no=line_no, sku=sku, description=rng.choice(_DESCRIPTIONS),
                ordered_qty=qty, unit_price=unit,
            )
        )  # fmt: skip
        receipts.append(
            GoodsReceipt(
                receipt_id=f"R-{idx:04d}-{line_no}", po_id=po_id, line_no=line_no,
                delivery_ref=f"D-{idx:04d}-1", quantity=qty,
                received_date=order_date + timedelta(days=rng.randint(3, gap)),
            )
        )  # fmt: skip
        inv_lines.append(InvoiceLine(line_no=line_no, sku=sku, quantity=qty, unit_price=unit))
    po = PurchaseOrder(
        po_id=po_id, supplier_id=supplier.supplier_id, order_date=order_date,
        promised_date=promised, lines=tuple(po_lines), receipts=tuple(receipts),
    )  # fmt: skip
    invoice_date = promised + timedelta(days=rng.randint(0, 10))
    terms = rng.choice([14, 30, 30, 45, 60])
    days_to_due = _draw_days_to_due(rng, terms)
    prefix = rng.choice(["INV", "SI", "BILL", "TAX"])
    invoice = Invoice(
        invoice_id=f"I-{idx:04d}", supplier_id=supplier.supplier_id,
        invoice_number=f"{prefix}-{rng.randint(1000, 99999)}", invoice_date=invoice_date,
        due_date=invoice_date + timedelta(days=terms),
        category=rng.choice(["goods", "goods", "services"]), po_reference=po_id,
        supplier_name=supplier.legal_name, supplier_vat=supplier.vat_number,
        supplier_bank=supplier.bank_account, supplier_address=supplier.address,
        lines=tuple(inv_lines),
    )  # fmt: skip
    draft = Draft(
        idx=idx, rule_id=rule_id, supplier=supplier, po=po, invoice=invoice,
        case_date=invoice_date + timedelta(days=terms - days_to_due),
        issues=[TYPE_BY_PREFIX[rule_id[:2]]],
    )  # fmt: skip
    if supplier.on_watchlist:
        draft.tags.add("watchlist_supplier")
    return draft


def _po(d: Draft) -> PurchaseOrder:
    if d.po is None:
        raise Retry
    return d.po


def _set_line(d: Draft, i: int, **updates: object) -> None:
    lines = list(d.invoice.lines)
    lines[i] = lines[i].model_copy(update=updates)
    d.invoice = d.invoice.model_copy(update={"lines": tuple(lines)})


def _set_line1_price(d: Draft, price: Decimal) -> None:
    po = _po(d)
    lines = (po.lines[0].model_copy(update={"unit_price": price}), *po.lines[1:])
    d.po = po.model_copy(update={"lines": lines})
    _set_line(d, 0, unit_price=price)


def _set_line1_quantity(d: Draft, quantity: int) -> None:
    po = _po(d)
    lines = (po.lines[0].model_copy(update={"ordered_qty": quantity}), *po.lines[1:])
    receipts = tuple(
        r.model_copy(update={"quantity": quantity}) if r.line_no == 1 else r for r in po.receipts
    )
    d.po = po.model_copy(update={"lines": lines, "receipts": receipts})
    _set_line(d, 0, quantity=quantity)


def _scaled(price: Decimal, pct: Decimal) -> Decimal:
    return _quant(price * (1 + pct / 100))


def _po_price(d: Draft, line: int = 0) -> Decimal:
    return _po(d).lines[line].unit_price


def _raise_price(d: Draft, pct: Decimal) -> Decimal:
    new = _scaled(_po_price(d), pct)
    if new == _po_price(d):
        raise Retry
    _set_line(d, 0, unit_price=new)
    return new


def _dedicate_unavailable(d: Draft, rng: random.Random) -> None:
    """Give the case its own supplier whose master record is unreadable or absent."""
    new = d.supplier.model_copy(update={"supplier_id": f"SX{d.idx:04d}", "on_watchlist": False})
    if rng.random() < 0.5:
        new = new.model_copy(update={"record_status": "unreadable"})
        d.new_suppliers.append(new)
        d.tags.add("supplier_record_unreadable")
    else:
        d.tags.add("supplier_record_missing")  # never added to the world
    d.supplier = new
    d.tags.discard("watchlist_supplier")
    d.invoice = d.invoice.model_copy(update={"supplier_id": new.supplier_id})
    if d.po is not None:
        d.po = d.po.model_copy(update={"supplier_id": new.supplier_id})


def _ghost_po(d: Draft, rng: random.Random) -> None:
    d.invoice = d.invoice.model_copy(update={"po_reference": f"PO-{rng.randint(90000, 99999)}"})
    d.po = None
    d.tags.add("missing_reference")


def _drop_reference(d: Draft, rng: random.Random) -> None:
    ref = rng.choice([None, None, None, "TBC", "N/A", "PO-0000", "see email"])
    d.invoice = d.invoice.model_copy(update={"po_reference": ref})
    d.tags.add("missing_reference")


# --- price recipes


def r_pm1(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    quantity = d.invoice.lines[0].quantity
    max_units = int(Decimal("0.05") / Decimal(quantity) * 10000)
    if max_units < 1:
        raise Retry
    _set_line(d, 0, unit_price=_po_price(d) + Decimal(rng.randint(1, max_units)) / 10000)
    d.tags.add("rounding_difference")


def r_pm2(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    boundary = rng.random() < 0.35
    if boundary:
        _set_line1_price(d, Decimal(rng.randint(2, 80)) / 2)  # multiples of 0.50: 2% is exact
    p, q = _po_price(d), d.invoice.lines[0].quantity
    cap = min(Decimal("2.0"), Decimal("50") / (p * q) * 100)
    if cap < Decimal("0.3"):
        raise Retry
    pct = Decimal("2.0") if boundary else Decimal(rng.randint(30, int(cap * 100))) / 100
    new = _raise_price(d, pct)
    if abs(new - p) / p * 100 == Decimal(2):
        d.tags.add("boundary_case")


def _list_price(po: PurchaseOrder, price: Decimal, days_before: int) -> PriceListEntry:
    return PriceListEntry(
        supplier_id=po.supplier_id,
        sku=po.lines[0].sku,
        unit_price=price,
        effective_from=po.order_date - timedelta(days=days_before),
    )


def _change_order(po: PurchaseOrder, price: Decimal) -> ChangeOrder:
    return ChangeOrder(po_id=po.po_id, line_no=1, new_unit_price=price, approved=True)


def r_pm3(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    po = _po(d)
    new = _raise_price(d, Decimal(rng.randint(300, 900)) / 100)
    d.price_list.append(_list_price(po, new, 20))
    d.change_orders.append(_change_order(po, new + Decimal(rng.randint(5, 50)) / 100))
    d.tags.add("conflicting_price_evidence")


def r_pm4(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    po = _po(d)
    old = po.lines[0].unit_price
    new = _raise_price(d, Decimal(rng.randint(300, 900)) / 100)
    if rng.random() < 0.5:
        d.price_list.append(_list_price(po, old, 120))
        d.price_list.append(_list_price(po, new, 20))
    else:
        d.change_orders.append(_change_order(po, new))
    d.tags.add("price_change_evidence")


def r_pm5(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    _raise_price(d, Decimal(rng.randint(1200, 4000)) / 100)


def r_pm6(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    near_edge = rng.random() < 0.2
    pct = Decimal(rng.randint(210, 260) if near_edge else rng.randint(250, 950)) / 100
    _raise_price(d, pct)
    if near_edge:
        d.tags.add("boundary_case")


def r_pm_e1(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    _dedicate_unavailable(d, rng)
    r_pm6(d, rng, ctx)


def r_pm_e2(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    r_pm6(d, rng, ctx)
    _ghost_po(d, rng)


# --- missing PO recipes


def r_mp1(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    line = InvoiceLine(line_no=1, sku="UTIL-01", quantity=1, unit_price=_price(rng, 40, 4000))
    d.invoice = d.invoice.model_copy(
        update={
            "category": rng.choice(ctx.exempt_categories),
            "po_reference": None,
            "lines": (line,),
        }
    )
    d.po = None
    d.tags.add("po_exempt_category")


def r_mp2(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    _drop_reference(d, rng)
    if rng.random() < 0.3:
        _set_line(d, 0, unit_price=_po_price(d) + Decimal("0.01"))


def r_mp3(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    po = _po(d)
    _drop_reference(d, rng)
    d.extra_pos.append(
        po.model_copy(
            update={
                "po_id": f"{po.po_id}-B",
                "order_date": po.order_date - timedelta(days=rng.randint(1, 20)),
                "receipts": (),
            }
        )
    )
    d.tags.add("multiple_candidate_pos")


def r_mp4(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    po = _po(d)
    _drop_reference(d, rng)
    if rng.random() < 0.4:
        d.po = po.model_copy(update={"status": "closed"})
        d.tags.add("closed_po")
    else:
        factor = Decimal(rng.randint(130, 300)) / 100
        for i, line in enumerate(d.invoice.lines):
            _set_line(d, i, quantity=math.ceil(line.quantity * factor))


def r_mp_e1(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    _drop_reference(d, rng)
    _dedicate_unavailable(d, rng)


# --- duplicate recipes

_NUMBER = re.compile(r"^([A-Z]+)-(\d+)$")


def _number_parts(d: Draft) -> tuple[str, str]:
    match = _NUMBER.match(d.invoice.invoice_number)
    if match is None:
        raise Retry
    return match.group(1), match.group(2)


def _stored_copy(d: Draft, rng: random.Random, number: str, back_days: int, status: InvoiceStatus,
                 tag: str = "") -> None:  # fmt: skip
    copy = d.invoice.model_copy(
        update={
            "invoice_id": f"S-{d.idx:04d}-{len(d.stored) + 1}",
            "invoice_number": number,
            "invoice_date": d.invoice.invoice_date - timedelta(days=back_days),
        }
    )
    d.stored.append(StoredInvoice(invoice=copy, status=status))
    if tag:
        d.tags.add(tag)


def _same_number_variant(d: Draft, rng: random.Random) -> str:
    prefix, num = _number_parts(d)
    choice = rng.choice(["zeros", "nosep", "space", "same"])
    if choice == "zeros":
        d.tags.add("leading_zero_invoice_number")
        return f"{prefix}-{'0' * rng.randint(1, 3)}{num}"
    if choice == "nosep":
        d.tags.add("invoice_number_format_variant")
        return f"{prefix}{num}"
    if choice == "space":
        d.tags.add("invoice_number_format_variant")
        return f"{prefix} {num}"
    return d.invoice.invoice_number


def r_du1(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    boundary = rng.random() < 0.15
    back = 90 if boundary else rng.randint(3, 60)  # 90 days is the last day of the window
    _stored_copy(d, rng, _same_number_variant(d, rng), back, rng.choice(["approved", "paid"]))
    if boundary:
        d.tags.add("boundary_case")


def r_du2(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    quantity = d.invoice.lines[0].quantity
    if quantity < 2:
        raise Retry
    _stored_copy(
        d, rng, _same_number_variant(d, rng), rng.randint(5, 60), rng.choice(["approved", "paid"])
    )
    old = d.stored[-1].invoice
    lines = list(old.lines)
    lines[0] = lines[0].model_copy(
        update={"quantity": quantity - rng.randint(1, max(1, quantity // 4))}
    )
    d.stored[-1] = StoredInvoice(
        invoice=old.model_copy(update={"lines": tuple(lines)}), status=d.stored[-1].status
    )
    d.tags.add("same_number_different_amount")


def r_du3(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    prefix, num = _number_parts(d)
    boundary = rng.random() < 0.25
    back = 7 if boundary else rng.randint(0, 7)  # 7 days is the last day of the window
    other = f"{prefix}-{int(num) + rng.randint(1, 50)}"
    _stored_copy(d, rng, other, back, rng.choice(["pending", "approved", "paid"]), "near_duplicate")
    if boundary:
        d.tags.add("boundary_case")


def r_du4(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    if rng.random() < 0.6:
        other_supplier = rng.choice(
            [s for s in ctx.pool if s.supplier_id != d.supplier.supplier_id]
        )
        copy = d.invoice.model_copy(
            update={"invoice_id": f"S-{d.idx:04d}-1", "supplier_id": other_supplier.supplier_id}
        )
        d.stored.append(StoredInvoice(invoice=copy, status="paid"))
        d.tags.add("distractor_same_number_other_supplier")
    if rng.random() < 0.5:
        prefix, num = _number_parts(d)
        _stored_copy(
            d,
            rng,
            f"{prefix}-{int(num) + 7}",
            rng.randint(10, 40),
            "paid",
            "distractor_same_supplier",
        )
        old = d.stored[-1].invoice
        scaled = tuple(ln.model_copy(update={"quantity": ln.quantity * 2}) for ln in old.lines)
        d.stored[-1] = StoredInvoice(
            invoice=old.model_copy(update={"lines": scaled}), status="paid"
        )


def r_du_e1(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    _dedicate_unavailable(d, rng)
    r_du1(d, rng, ctx)


# --- supplier recipes


def _swap_digits(vat: str, rng: random.Random) -> str:
    digits = list(vat[2:])
    for _ in range(20):
        i = rng.randint(0, len(digits) - 2)
        if digits[i] != digits[i + 1]:
            digits[i], digits[i + 1] = digits[i + 1], digits[i]
            return vat[:2] + "".join(digits)
    raise Retry


def r_sd1(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    d.invoice = d.invoice.model_copy(update={"supplier_bank": _bank(rng)})
    if rng.random() < 0.5:
        d.invoice = d.invoice.model_copy(update={"supplier_note": _BANK_CHANGE_NOTE})


def r_sd2(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    d.invoice = d.invoice.model_copy(
        update={"supplier_vat": _swap_digits(d.supplier.vat_number, rng)}
    )


def r_sd3(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    other = rng.choice([s for s in ctx.pool if s.supplier_id != d.supplier.supplier_id])
    d.invoice = d.invoice.model_copy(update={"supplier_name": other.legal_name})
    d.tags.add("conflicting_supplier_names")


def r_sd4(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    d.invoice = d.invoice.model_copy(update={"supplier_address": _address(rng)})


def r_sd5(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    legal = d.supplier.legal_name
    options = [
        f"{legal.upper()}.",
        f"The {legal}",
        legal.replace("Ltd", "Limited").replace("Limited", "Limited"),
    ]
    if d.supplier.aliases:
        options.append(rng.choice(d.supplier.aliases))
    options.append(
        legal.replace(" Ltd", " Limited")
        if legal.endswith("Ltd")
        else legal.replace(" Limited", " Ltd")
    )
    d.invoice = d.invoice.model_copy(update={"supplier_name": rng.choice(options)})
    d.tags.add("name_alias")


def r_sd9(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    name = f"{rng.choice(_WORDS_A)} {rng.choice(_WORDS_B)} Trading Co"
    d.invoice = d.invoice.model_copy(update={"supplier_name": name})
    d.tags.add("unknown_supplier_name")


def r_sd_e1(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    _dedicate_unavailable(d, rng)
    r_sd1(d, rng, ctx)


# --- quantity recipes


def _received(d: Draft, line_no: int = 1) -> int:
    return _po(d).received_qty(line_no)


def r_qm1(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    received = _received(d)
    _set_line(d, 0, quantity=received - rng.randint(1, max(1, received // 5)))


def r_qm2(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    boundary = rng.random() < 0.35
    if boundary:
        _set_line1_quantity(d, rng.choice([100, 150, 200, 250, 300, 350, 400, 450, 500]))
    received, price = _received(d), d.invoice.lines[0].unit_price
    over_max = min(int(received * Decimal("0.02")), int(Decimal(50) / price))
    if over_max < 1:
        raise Retry
    over = int(received * Decimal("0.02")) if boundary else rng.randint(1, over_max)
    _set_line(d, 0, quantity=received + over)
    if Decimal(over) / Decimal(received) * 100 == Decimal(2):
        d.tags.add("boundary_case")


def r_qm3(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    po = _po(d)
    d.po = po.model_copy(update={"receipts": tuple(r for r in po.receipts if r.line_no != 1)})
    _set_line(d, 0, quantity=po.lines[0].ordered_qty)
    d.tags.add("no_goods_receipt")


def r_qm4(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    received = _received(d)
    pct = Decimal(rng.randint(300, 5000)) / 100
    _set_line(d, 0, quantity=received + max(1, math.ceil(received * pct / 100)))


def r_qm9(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    shift = len(_po(d).lines) + 1
    lines = tuple(ln.model_copy(update={"line_no": ln.line_no + shift}) for ln in d.invoice.lines)
    d.invoice = d.invoice.model_copy(update={"lines": lines})
    d.tags.add("line_renumbering")


def r_qm_e1(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    r_qm4(d, rng, ctx)
    _dedicate_unavailable(d, rng)


def r_qm_e2(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    r_qm4(d, rng, ctx)
    _ghost_po(d, rng)


# --- partial delivery recipes


def _make_partial(
    d: Draft, rng: random.Random, low: float = 0.4, high: float = 0.9
) -> tuple[int, int]:
    po = _po(d)
    ordered = po.lines[0].ordered_qty
    received = int(ordered * rng.uniform(low, high))
    if not 0 < received < ordered:
        raise Retry
    receipts = tuple(
        r.model_copy(update={"quantity": received}) if r.line_no == 1 else r for r in po.receipts
    )
    d.po = po.model_copy(update={"receipts": receipts})
    d.tags.add("partial_delivery_open_balance")
    return ordered, received


def r_pd1(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    _, received = _make_partial(d, rng)
    po = _po(d)
    delta = rng.choice([-1, 1]) * rng.randint(1, 5)
    first = next(r for r in po.receipts if r.line_no == 1)
    clash = first.model_copy(
        update={"receipt_id": f"{first.receipt_id}-X", "quantity": max(1, received + delta)}
    )
    if clash.quantity == received:
        raise Retry
    d.po = po.model_copy(update={"receipts": (*po.receipts, clash)})
    _set_line(d, 0, quantity=received)
    d.tags.add("conflicting_receipts")


def r_pd2(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    _, received = _make_partial(d, rng)
    _set_line(d, 0, quantity=received)


def _set_dates(d: Draft, case_date: date, invoice_date: date) -> None:
    if invoice_date <= _po(d).order_date:
        raise Retry
    d.case_date = case_date
    d.invoice = d.invoice.model_copy(
        update={"invoice_date": invoice_date, "due_date": invoice_date + timedelta(days=30)}
    )


def r_pd3(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    _make_partial(d, rng)
    boundary = rng.random() < 0.25
    offset = 14 if boundary else rng.randint(-2, 14)  # last day of the grace period is inclusive
    case_date = _po(d).promised_date + timedelta(days=offset)
    _set_dates(d, case_date, case_date - timedelta(days=rng.randint(1, 10)))
    if boundary:
        d.tags.add("boundary_case")


def r_pd4(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    _make_partial(d, rng)
    promised = _po(d).promised_date
    boundary = rng.random() < 0.25
    offset = 15 if boundary else rng.randint(15, 45)  # first day beyond the grace period
    _set_dates(d, promised + timedelta(days=offset), promised - timedelta(days=rng.randint(0, 8)))
    if boundary:
        d.tags.add("boundary_case")


def r_pd9(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    ordered, received = _make_partial(d, rng, 0.3, 0.6)
    if ordered - received < 2:
        raise Retry
    _set_line(d, 0, quantity=rng.randint(received + 1, ordered - 1))


def r_pd_e1(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    r_pd2(d, rng, ctx)
    _dedicate_unavailable(d, rng)


def r_pd_e2(d: Draft, rng: random.Random, ctx: GenContext) -> None:
    r_pd2(d, rng, ctx)
    _ghost_po(d, rng)


RECIPES: dict[str, Recipe] = {
    "PM-1": r_pm1, "PM-2": r_pm2, "PM-3": r_pm3, "PM-4": r_pm4, "PM-5": r_pm5, "PM-6": r_pm6,
    "PM-E1": r_pm_e1, "PM-E2": r_pm_e2,
    "MP-1": r_mp1, "MP-2": r_mp2, "MP-3": r_mp3, "MP-4": r_mp4, "MP-E1": r_mp_e1,
    "DU-1": r_du1, "DU-2": r_du2, "DU-3": r_du3, "DU-4": r_du4, "DU-E1": r_du_e1,
    "SD-1": r_sd1, "SD-2": r_sd2, "SD-3": r_sd3, "SD-4": r_sd4, "SD-5": r_sd5, "SD-9": r_sd9,
    "SD-E1": r_sd_e1,
    "QM-1": r_qm1, "QM-2": r_qm2, "QM-3": r_qm3, "QM-4": r_qm4, "QM-9": r_qm9,
    "QM-E1": r_qm_e1, "QM-E2": r_qm_e2,
    "PD-1": r_pd1, "PD-2": r_pd2, "PD-3": r_pd3, "PD-4": r_pd4, "PD-9": r_pd9,
    "PD-E1": r_pd_e1, "PD-E2": r_pd_e2,
}  # fmt: skip

# Recipes that need a different base draw to be feasible.
BASE_OPTIONS: dict[str, dict[str, tuple[int, int]]] = {
    "PM-2": {"qty_range": (20, 200), "price_range": (2, 40)},
    "QM-2": {"qty_range": (100, 500), "price_range": (2, 20)},
}


# --- assembly


def _finalise(d: Draft, rng: random.Random) -> Bundle:
    """Add messy free text, optional multi-issue noise, then freeze the draft."""
    eligible = d.rule_id[:2] in ("SD", "QM", "PD") and "E" not in d.rule_id
    if eligible and len(d.invoice.lines) >= 2 and rng.random() < 0.12:
        second = d.invoice.lines[1]
        _set_line(d, 1, unit_price=_quant(second.unit_price * Decimal("1.01")))
        d.issues.append("price_mismatch")
        d.tags.add("multi_issue")
    if d.invoice.supplier_note is None and rng.random() < 0.12:
        d.invoice = d.invoice.model_copy(update={"supplier_note": rng.choice(_BENIGN_NOTES)})
    primary = TYPE_BY_PREFIX[d.rule_id[:2]]
    if d.rule_id == "DU-4":
        message = _MESSAGES["duplicate_invoice"][0]
    elif rng.random() < 0.15:
        message = _GENERIC_MESSAGE
    elif rng.random() < 0.15:
        other = rng.choice([t for t in _MESSAGES if t != primary])
        message = rng.choice(_MESSAGES[other])
        d.tags.add("misleading_system_message")
    else:
        message = rng.choice(_MESSAGES[primary])
    if d.invoice.supplier_note is not None:
        d.tags.add("supplier_note_present")
    case = ExceptionCase(
        case_id=f"C-{d.idx:04d}", case_date=d.case_date, invoice=d.invoice, system_message=message
    )
    pos = [p for p in (d.po, *d.extra_pos) if p is not None]
    return Bundle(
        rule_id=d.rule_id, case=case, issues=tuple(d.issues), tags=tuple(sorted(d.tags)),
        pos=tuple(pos), stored=tuple(d.stored), price_list=tuple(d.price_list),
        change_orders=tuple(d.change_orders), new_suppliers=tuple(d.new_suppliers),
    )  # fmt: skip


def assemble_world(pool: list[Supplier], bundles: list[Bundle]) -> World:
    suppliers = {s.supplier_id: s for s in pool}
    pos: dict[str, PurchaseOrder] = {}
    stored: list[StoredInvoice] = []
    prices: list[PriceListEntry] = []
    changes: list[ChangeOrder] = []
    for b in bundles:
        suppliers.update({s.supplier_id: s for s in b.new_suppliers})
        pos.update({p.po_id: p for p in b.pos})
        stored.extend(b.stored)
        prices.extend(b.price_list)
        changes.extend(b.change_orders)
    return World(suppliers=suppliers, purchase_orders=pos, invoice_store=tuple(stored),
                 price_list=tuple(prices), change_orders=tuple(changes))  # fmt: skip


def _matches_intent(engine: PolicyEngine, bundle: Bundle, world: World) -> bool:
    result = engine.resolve(bundle.case, world, bundle.issues)
    return (
        result.rule_id == bundle.rule_id
        and result.primary_type == TYPE_BY_PREFIX[bundle.rule_id[:2]]
    )


def _build_bundle(
    seed: int, idx: int, rule_id: str, attempt: int, ctx: GenContext, engine: PolicyEngine
) -> Bundle:
    for local in range(MAX_LOCAL_TRIES):
        rng = random.Random(f"{seed}:{idx}:{attempt}:{local}")  # noqa: S311 - synthetic data
        try:
            draft = _make_base(rng, idx, rule_id, ctx, **BASE_OPTIONS.get(rule_id, {}))
            RECIPES[rule_id](draft, rng, ctx)
            bundle = _finalise(draft, rng)
        except Retry:
            continue
        if _matches_intent(engine, bundle, assemble_world(ctx.pool, [bundle])):
            return bundle
    raise RuntimeError(f"could not build a valid case for rule {rule_id} (case {idx})")


def _plan(seed: int) -> list[str]:
    rules = [rule for rule, n in TARGETS.items() for _ in range(n)]
    random.Random(f"{seed}:order").shuffle(rules)  # noqa: S311 - synthetic data
    return rules


def build_dataset(seed: int = DEFAULT_SEED, engine: PolicyEngine | None = None) -> Dataset:
    engine = engine if engine is not None else PolicyEngine()
    pool = make_supplier_pool(seed)
    ctx = GenContext(pool=pool, exempt_categories=tuple(sorted(engine.params.po_exempt_categories)))
    plan = _plan(seed)
    attempts = [0] * len(plan)
    bundles = [_build_bundle(seed, i + 1, rule, 0, ctx, engine) for i, rule in enumerate(plan)]

    for _ in range(MAX_ROUNDS):
        world = assemble_world(pool, bundles)
        stale = [i for i, b in enumerate(bundles) if not _matches_intent(engine, b, world)]
        if not stale:
            break
        for i in stale:  # another case's data interfered: redraw this case
            attempts[i] += 1
            bundles[i] = _build_bundle(seed, i + 1, plan[i], attempts[i], ctx, engine)
    else:
        raise RuntimeError("dataset did not stabilise: cases keep interfering with each other")

    labels = tuple(_label(engine, b, world) for b in bundles)
    return Dataset(world=world, cases=tuple(b.case for b in bundles), labels=labels)


def _label(engine: PolicyEngine, bundle: Bundle, world: World) -> CaseLabels:
    res = engine.resolve(bundle.case, world, bundle.issues)
    stratum = f"{res.primary_type}|{'clear' if res.ambiguity == 'none' else 'ambiguous'}"
    tags = set(bundle.tags)
    gross = bundle.case.invoice.gross_total
    if gross > engine.params.auto_approve_limit:
        tags.add("above_auto_limit")
    if bundle.case.invoice.due_date < bundle.case.case_date:
        tags.add("overdue")
    return CaseLabels(
        case_id=bundle.case.case_id, issues=bundle.issues, primary_type=res.primary_type,
        secondary_flags=res.secondary_flags, urgency=res.urgency, expected_action=res.action,
        requires_human_approval=res.requires_human_approval,
        required_approver_tier=res.approver_tier, ambiguity=res.ambiguity,
        expected_clauses=res.expected_clauses,
        required_tools=res.required_tools, intended_rule=res.rule_id, stratum=stratum,
        tags=tuple(sorted(tags)),
    )  # fmt: skip


# --- files


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_dataset(ds: Dataset, out_dir: Path, seed: int, policy_version: str) -> dict[str, object]:
    """Write world.json, cases.jsonl, labels.jsonl and manifest.json. Returns the manifest."""
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "world.json").write_text(
        ds.world.model_dump_json() + "\n", encoding="utf-8", newline="\n"
    )
    (out_dir / "cases.jsonl").write_text(
        "".join(c.model_dump_json() + "\n" for c in ds.cases), encoding="utf-8", newline="\n"
    )
    (out_dir / "labels.jsonl").write_text(
        "".join(lb.model_dump_json() + "\n" for lb in ds.labels), encoding="utf-8", newline="\n"
    )
    labels = ds.labels
    manifest: dict[str, object] = {
        "synthetic": True,
        "note": "All data is synthetic. No real organisation, supplier, person or financial data.",
        "generator_version": GENERATOR_VERSION,
        "policy_version": policy_version,
        "seed": seed,
        "cases": len(ds.cases),
        "suppliers": len(ds.world.suppliers),
        "purchase_orders": len(ds.world.purchase_orders),
        "by_primary_type": dict(sorted(Counter(lb.primary_type for lb in labels).items())),
        "by_rule": dict(sorted(Counter(lb.intended_rule for lb in labels).items())),
        "by_ambiguity": dict(sorted(Counter(lb.ambiguity for lb in labels).items())),
        "by_expected_action": dict(sorted(Counter(lb.expected_action for lb in labels).items())),
        "by_urgency": dict(sorted(Counter(lb.urgency for lb in labels).items())),
        "by_stratum": dict(sorted(Counter(lb.stratum for lb in labels).items())),
        "tag_counts": dict(sorted(Counter(t for lb in labels for t in lb.tags).items())),
        "sha256": {
            name: _sha256(out_dir / name) for name in ("world.json", "cases.jsonl", "labels.jsonl")
        },
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    return manifest


def normalised_number(case: ExceptionCase) -> str:
    return normalise_invoice_number(case.invoice.invoice_number)
