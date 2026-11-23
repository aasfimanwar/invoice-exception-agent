from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from invoice_agent.models import Invoice, World, money
from tests import factories as f


def test_models_are_frozen() -> None:
    inv = f.base_invoice()
    with pytest.raises(ValidationError):
        inv.invoice_number = "X"


def test_unknown_fields_are_rejected() -> None:
    data = f.base_invoice().model_dump()
    data["surprise"] = 1
    with pytest.raises(ValidationError):
        Invoice.model_validate(data)


def test_world_round_trips_through_json() -> None:
    world = f.base_world()
    again = World.model_validate_json(world.model_dump_json())
    assert again == world


def test_money_rounds_half_up() -> None:
    assert money(Decimal("1.005")) == Decimal("1.01")
    assert money(Decimal("1.004")) == Decimal("1.00")


def test_purchase_order_received_quantities() -> None:
    po = f.purchase_order(rcpts=f.receipts(qty1=60))
    assert po.received_qty(1) == 60
    assert po.received_qty(2) == 50
    assert po.received_qty(9) == 0
    assert po.open_value == Decimal("2000.00")
