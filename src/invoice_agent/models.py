"""Typed domain models for the synthetic invoice exception world. All data is synthetic."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

ExceptionType = Literal[
    "price_mismatch",
    "missing_po",
    "duplicate_invoice",
    "wrong_supplier_details",
    "quantity_mismatch",
    "partial_delivery",
]
Action = Literal[
    "approve_within_tolerance",
    "request_correction",
    "route_to_buyer",
    "raise_dispute",
    "escalate",
]
Ambiguity = Literal["none", "conflicting_evidence", "missing_evidence", "policy_gap"]
Urgency = Literal["critical", "high", "normal", "low"]
InvoiceStatus = Literal["pending", "approved", "paid"]
PurchaseOrderStatus = Literal["open", "closed"]
SupplierRecordStatus = Literal["ok", "unreadable"]

CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    """Round to pence, half up."""
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Supplier(Frozen):
    supplier_id: str
    legal_name: str
    aliases: tuple[str, ...] = ()
    vat_number: str
    bank_account: str
    address: str
    on_watchlist: bool = False
    record_status: SupplierRecordStatus = "ok"  # "unreadable" simulates a corrupt master record


class GoodsReceipt(Frozen):
    receipt_id: str
    po_id: str
    line_no: int
    delivery_ref: str
    quantity: int
    received_date: date


class PurchaseOrderLine(Frozen):
    line_no: int
    sku: str
    description: str
    ordered_qty: int
    unit_price: Decimal


class PurchaseOrder(Frozen):
    po_id: str
    supplier_id: str
    order_date: date
    promised_date: date
    status: PurchaseOrderStatus = "open"
    lines: tuple[PurchaseOrderLine, ...]
    receipts: tuple[GoodsReceipt, ...] = ()

    def line(self, line_no: int) -> PurchaseOrderLine | None:
        return next((ln for ln in self.lines if ln.line_no == line_no), None)

    def receipts_for(self, line_no: int) -> tuple[GoodsReceipt, ...]:
        return tuple(r for r in self.receipts if r.line_no == line_no)

    def received_qty(self, line_no: int) -> int:
        return sum(r.quantity for r in self.receipts_for(line_no))

    @property
    def open_value(self) -> Decimal:
        total = sum((Decimal(ln.ordered_qty) * ln.unit_price for ln in self.lines), Decimal(0))
        return money(total)


class PriceListEntry(Frozen):
    supplier_id: str
    sku: str
    unit_price: Decimal
    effective_from: date


class ChangeOrder(Frozen):
    po_id: str
    line_no: int
    new_unit_price: Decimal
    approved: bool


class InvoiceLine(Frozen):
    line_no: int
    sku: str
    quantity: int
    unit_price: Decimal


class Invoice(Frozen):
    invoice_id: str
    supplier_id: str  # vendor account the invoice was booked to in the AP system
    invoice_number: str
    invoice_date: date
    due_date: date
    category: str
    po_reference: str | None = None
    supplier_name: str
    supplier_vat: str
    supplier_bank: str
    supplier_address: str
    supplier_note: str | None = None  # free text from the supplier: data, never instructions
    vat_rate: Decimal = Decimal("0.20")
    lines: tuple[InvoiceLine, ...]

    @property
    def net_total(self) -> Decimal:
        total = sum((Decimal(ln.quantity) * ln.unit_price for ln in self.lines), Decimal(0))
        return money(total)

    @property
    def vat_amount(self) -> Decimal:
        return money(self.net_total * self.vat_rate)

    @property
    def gross_total(self) -> Decimal:
        return self.net_total + self.vat_amount


class StoredInvoice(Frozen):
    invoice: Invoice
    status: InvoiceStatus


class ExceptionCase(Frozen):
    case_id: str
    case_date: date
    invoice: Invoice
    system_message: str  # vague message from the matching system, sometimes misleading


class World(Frozen):
    """Everything the mock APIs can see. Built by the generator, read by tools and the engine."""

    suppliers: dict[str, Supplier]
    purchase_orders: dict[str, PurchaseOrder]
    invoice_store: tuple[StoredInvoice, ...] = ()
    price_list: tuple[PriceListEntry, ...] = ()
    change_orders: tuple[ChangeOrder, ...] = ()


class CaseLabels(Frozen):
    """Ground truth for one case. Kept in a separate file from the case the agent sees."""

    case_id: str
    issues: tuple[ExceptionType, ...]
    primary_type: ExceptionType
    secondary_flags: tuple[ExceptionType, ...]
    urgency: Urgency
    expected_action: Action
    requires_human_approval: bool
    required_approver_tier: str
    ambiguity: Ambiguity
    expected_clauses: tuple[str, ...]
    required_tools: tuple[str, ...]
    intended_rule: str
    stratum: str
    tags: tuple[str, ...]
    label_source: Literal["generator", "hand"] = "generator"


class Dataset(Frozen):
    world: World
    cases: tuple[ExceptionCase, ...]
    labels: tuple[CaseLabels, ...]
