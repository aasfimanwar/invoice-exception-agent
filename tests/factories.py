"""Scenario builders for engine tests. All data is synthetic.

The base world holds a clean, fully matched invoice. Each scenario changes one thing so a
single rule fires. Dates: PO ordered 2026-01-05, promised 2026-01-20, grace ends 2026-02-03.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from invoice_agent.models import (
    ChangeOrder,
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

D = Decimal


@dataclass(frozen=True)
class Scenario:
    case: ExceptionCase
    world: World
    issues: tuple[ExceptionType, ...]


def supplier_one() -> Supplier:
    return Supplier(
        supplier_id="S1",
        legal_name="Acme Fasteners Ltd",
        aliases=("Acme Fasteners Limited", "Acme Fixings"),
        vat_number="GB123456789",
        bank_account="20-00-00 12345678",
        address="1 Mill Road, Leeds LS1 1AA",
    )


def supplier_two() -> Supplier:
    return Supplier(
        supplier_id="S2",
        legal_name="Birch Packaging Ltd",
        vat_number="GB987654321",
        bank_account="30-00-00 87654321",
        address="9 Canal Street, Derby DE1 2AB",
    )


def receipts(qty1: int = 100, qty2: int = 50) -> tuple[GoodsReceipt, ...]:
    out: list[GoodsReceipt] = []
    if qty1:
        out.append(
            GoodsReceipt(
                receipt_id="R1",
                po_id="PO1",
                line_no=1,
                delivery_ref="D1",
                quantity=qty1,
                received_date=date(2026, 1, 18),
            )
        )
    if qty2:
        out.append(
            GoodsReceipt(
                receipt_id="R2",
                po_id="PO1",
                line_no=2,
                delivery_ref="D2",
                quantity=qty2,
                received_date=date(2026, 1, 18),
            )
        )
    return tuple(out)


def purchase_order(
    po_id: str = "PO1", rcpts: tuple[GoodsReceipt, ...] | None = None
) -> PurchaseOrder:
    return PurchaseOrder(
        po_id=po_id,
        supplier_id="S1",
        order_date=date(2026, 1, 5),
        promised_date=date(2026, 1, 20),
        lines=(
            PurchaseOrderLine(
                line_no=1,
                sku="FST-100",
                description="M8 bolts",
                ordered_qty=100,
                unit_price=D("10.00"),
            ),
            PurchaseOrderLine(
                line_no=2,
                sku="FST-200",
                description="M10 bolts",
                ordered_qty=50,
                unit_price=D("20.00"),
            ),
        ),
        receipts=receipts() if rcpts is None else rcpts,
    )


def base_invoice() -> Invoice:
    return Invoice(
        invoice_id="I-1",
        supplier_id="S1",
        invoice_number="INV-1001",
        invoice_date=date(2026, 2, 1),
        due_date=date(2026, 2, 28),
        category="goods",
        po_reference="PO1",
        supplier_name="Acme Fasteners Ltd",
        supplier_vat="GB123456789",
        supplier_bank="20-00-00 12345678",
        supplier_address="1 Mill Road, Leeds LS1 1AA",
        lines=(
            InvoiceLine(line_no=1, sku="FST-100", quantity=100, unit_price=D("10.00")),
            InvoiceLine(line_no=2, sku="FST-200", quantity=50, unit_price=D("20.00")),
        ),
    )


def base_world() -> World:
    return World(
        suppliers={"S1": supplier_one(), "S2": supplier_two()},
        purchase_orders={"PO1": purchase_order()},
    )


def scenario(
    issue: ExceptionType,
    *,
    invoice: Invoice | None = None,
    world: World | None = None,
    case_date: date = date(2026, 2, 10),
) -> Scenario:
    inv = invoice if invoice is not None else base_invoice()
    case = ExceptionCase(case_id="C-1", case_date=case_date, invoice=inv, system_message="x")
    return Scenario(case=case, world=world if world is not None else base_world(), issues=(issue,))


def with_prices(inv: Invoice, price1: str, price2: str | None = None) -> Invoice:
    lines = list(inv.lines)
    lines[0] = lines[0].model_copy(update={"unit_price": D(price1)})
    if price2 is not None:
        lines[1] = lines[1].model_copy(update={"unit_price": D(price2)})
    return inv.model_copy(update={"lines": tuple(lines)})


def with_qty(inv: Invoice, qty1: int, qty2: int | None = None) -> Invoice:
    lines = list(inv.lines)
    lines[0] = lines[0].model_copy(update={"quantity": qty1})
    if qty2 is not None:
        lines[1] = lines[1].model_copy(update={"quantity": qty2})
    return inv.model_copy(update={"lines": tuple(lines)})


def unreadable_suppliers() -> dict[str, Supplier]:
    broken = supplier_one().model_copy(update={"record_status": "unreadable"})
    return {"S1": broken, "S2": supplier_two()}


def stored(inv: Invoice, status: InvoiceStatus = "paid") -> StoredInvoice:
    return StoredInvoice(invoice=inv, status=status)


def world_with(
    *,
    pos: dict[str, PurchaseOrder] | None = None,
    store: tuple[StoredInvoice, ...] = (),
    price_list: tuple[PriceListEntry, ...] = (),
    change_orders: tuple[ChangeOrder, ...] = (),
    suppliers: dict[str, Supplier] | None = None,
) -> World:
    return World(
        suppliers=suppliers
        if suppliers is not None
        else {"S1": supplier_one(), "S2": supplier_two()},
        purchase_orders=pos if pos is not None else {"PO1": purchase_order()},
        invoice_store=store,
        price_list=price_list,
        change_orders=change_orders,
    )


# --------------------------------------------------------------------------- one scenario per rule


def rule_scenarios() -> dict[str, Scenario]:
    base = base_invoice()
    s: dict[str, Scenario] = {}

    # price_mismatch
    s["PM-1"] = scenario("price_mismatch", invoice=with_prices(base, "10.0004"))
    s["PM-2"] = scenario("price_mismatch", invoice=with_prices(base, "10.15"))
    s["PM-3"] = scenario(
        "price_mismatch",
        invoice=with_prices(base, "10.50"),
        world=world_with(
            price_list=(
                PriceListEntry(
                    supplier_id="S1",
                    sku="FST-100",
                    unit_price=D("10.50"),
                    effective_from=date(2026, 1, 1),
                ),
            ),
            change_orders=(
                ChangeOrder(po_id="PO1", line_no=1, new_unit_price=D("10.60"), approved=True),
            ),
        ),
    )
    s["PM-4"] = scenario(
        "price_mismatch",
        invoice=with_prices(base, "10.50"),
        world=world_with(
            price_list=(
                PriceListEntry(
                    supplier_id="S1",
                    sku="FST-100",
                    unit_price=D("10.50"),
                    effective_from=date(2026, 1, 1),
                ),
            ),
        ),
    )
    s["PM-5"] = scenario("price_mismatch", invoice=with_prices(base, "12.00"))
    s["PM-6"] = scenario("price_mismatch", invoice=with_prices(base, "10.50"))

    # missing_po
    no_po = base.model_copy(update={"po_reference": None})
    s["MP-1"] = scenario("missing_po", invoice=no_po.model_copy(update={"category": "utilities"}))
    s["MP-2"] = scenario("missing_po", invoice=no_po)
    s["MP-3"] = scenario(
        "missing_po",
        invoice=no_po,
        world=world_with(pos={"PO1": purchase_order("PO1"), "PO2": purchase_order("PO2")}),
    )
    s["MP-4"] = scenario("missing_po", invoice=no_po, world=world_with(pos={}))

    # duplicate_invoice
    earlier = base.model_copy(
        update={
            "invoice_id": "I-0",
            "invoice_number": "INV-01001",
            "invoice_date": date(2026, 1, 25),
        }
    )
    s["DU-1"] = scenario("duplicate_invoice", world=world_with(store=(stored(earlier, "paid"),)))
    s["DU-2"] = scenario(
        "duplicate_invoice",
        world=world_with(store=(stored(with_qty(earlier, 90), "paid"),)),
    )
    near = base.model_copy(
        update={
            "invoice_id": "I-2",
            "invoice_number": "INV-2002",
            "invoice_date": date(2026, 1, 29),
        }
    )
    s["DU-3"] = scenario("duplicate_invoice", world=world_with(store=(stored(near, "pending"),)))
    s["DU-4"] = scenario("duplicate_invoice")

    # wrong_supplier_details
    s["SD-1"] = scenario(
        "wrong_supplier_details",
        invoice=base.model_copy(update={"supplier_bank": "99-99-99 11111111"}),
    )
    s["SD-2"] = scenario(
        "wrong_supplier_details", invoice=base.model_copy(update={"supplier_vat": "GB000000000"})
    )
    s["SD-3"] = scenario(
        "wrong_supplier_details",
        invoice=base.model_copy(update={"supplier_name": "Birch Packaging Ltd"}),
    )
    s["SD-4"] = scenario(
        "wrong_supplier_details",
        invoice=base.model_copy(update={"supplier_address": "12 New Street, Leeds LS2 9ZZ"}),
    )
    s["SD-5"] = scenario(
        "wrong_supplier_details",
        invoice=base.model_copy(update={"supplier_name": "ACME FASTENERS LIMITED."}),
    )
    s["SD-9"] = scenario(
        "wrong_supplier_details",
        invoice=base.model_copy(update={"supplier_name": "Totally Different Trading Co"}),
    )

    # quantity_mismatch
    s["QM-1"] = scenario("quantity_mismatch", invoice=with_qty(base, 90))
    s["QM-2"] = scenario("quantity_mismatch", invoice=with_qty(base, 102))
    s["QM-3"] = scenario(
        "quantity_mismatch",
        invoice=with_qty(base, 110),
        world=world_with(pos={"PO1": purchase_order(rcpts=receipts(qty1=0))}),
    )
    s["QM-4"] = scenario("quantity_mismatch", invoice=with_qty(base, 110))

    # partial_delivery (line 1 received 60 of 100)
    partial_pos = {"PO1": purchase_order(rcpts=receipts(qty1=60))}
    conflict_receipts = (
        *receipts(qty1=60),
        GoodsReceipt(
            receipt_id="R3",
            po_id="PO1",
            line_no=1,
            delivery_ref="D1",
            quantity=55,
            received_date=date(2026, 1, 19),
        ),
    )
    s["PD-1"] = scenario(
        "partial_delivery",
        invoice=with_qty(base, 60),
        world=world_with(pos={"PO1": purchase_order(rcpts=conflict_receipts)}),
    )
    s["PD-2"] = scenario(
        "partial_delivery", invoice=with_qty(base, 60), world=world_with(pos=partial_pos)
    )
    s["PD-3"] = scenario(
        "partial_delivery",
        invoice=base.model_copy(update={"invoice_date": date(2026, 1, 22)}),
        world=world_with(pos=partial_pos),
        case_date=date(2026, 1, 25),
    )
    s["PD-4"] = scenario("partial_delivery", world=world_with(pos=partial_pos))
    s["PD-9"] = scenario(
        "partial_delivery", invoice=with_qty(base, 80), world=world_with(pos=partial_pos)
    )

    # missing_evidence: unreadable supplier record, or a PO reference that cannot be found
    bad = world_with(suppliers=unreadable_suppliers())
    ghost_po = base.model_copy(update={"po_reference": "PO-MISSING"})
    s["PM-E1"] = scenario("price_mismatch", invoice=with_prices(base, "10.50"), world=bad)
    s["PM-E2"] = scenario("price_mismatch", invoice=with_prices(ghost_po, "10.50"))
    s["MP-E1"] = scenario("missing_po", invoice=no_po, world=bad)
    s["DU-E1"] = scenario(
        "duplicate_invoice",
        world=world_with(store=(stored(earlier, "paid"),), suppliers=unreadable_suppliers()),
    )
    s["SD-E1"] = scenario(
        "wrong_supplier_details",
        invoice=base.model_copy(update={"supplier_bank": "99-99-99 11111111"}),
        world=bad,
    )
    s["QM-E1"] = scenario("quantity_mismatch", invoice=with_qty(base, 110), world=bad)
    s["QM-E2"] = scenario("quantity_mismatch", invoice=with_qty(ghost_po, 110))
    s["PD-E1"] = scenario(
        "partial_delivery",
        invoice=with_qty(base, 60),
        world=world_with(pos=partial_pos, suppliers=unreadable_suppliers()),
    )
    s["PD-E2"] = scenario("partial_delivery", invoice=with_qty(ghost_po, 60))

    # a quantity case whose invoice lines are not on the PO at all: nothing to compare
    off_po = InvoiceLine(line_no=3, sku="FST-999", quantity=10, unit_price=D("5.00"))
    s["QM-9"] = scenario("quantity_mismatch", invoice=base.model_copy(update={"lines": (off_po,)}))
    return s
