from decimal import Decimal

import pytest
from app.core.errors import DomainError
from app.services.calculator import LineBalance, RefundCalculator, allocate_discount


def test_discount_largest_remainder_conserves_cents():
    assert allocate_discount([Decimal("1.00")] * 3, Decimal("0.02")) == [
        Decimal("0.01"),
        Decimal("0.01"),
        Decimal("0.00"),
    ]
    for discount in range(0, 301):
        result = allocate_discount([Decimal("1.00")] * 3, Decimal(discount) / 100)
        assert sum(result) == Decimal(discount) / 100
        assert all(Decimal("0.00") <= value <= Decimal("1.00") for value in result)


@pytest.mark.parametrize("partition", [[1, 1, 1], [2, 1], [1, 2], [3]])
def test_partial_refund_partitions_preserve_total(partition):
    used_amount, used_qty, amounts = Decimal("0.00"), 0, []
    for quantity in partition:
        balance = LineBalance(Decimal("100.00"), 3, used_amount, used_qty)
        amount = RefundCalculator.item_amount(balance, quantity)
        amounts.append(amount)
        used_amount += amount
        used_qty += quantity
    assert sum(amounts) == Decimal("100.00")
    if partition == [1, 1, 1]:
        assert amounts == [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")]


def test_reserved_refunds_and_replacements_reduce_available_quantity():
    with pytest.raises(DomainError, match="数量"):
        RefundCalculator.item_amount(LineBalance(Decimal("100.00"), 3, Decimal("33.33"), 1, 1), 2)
    assert RefundCalculator.item_amount(LineBalance(Decimal("100.00"), 3, ZERO, 0, 1), 2) == Decimal("66.66")


def test_invalid_discount_and_empty_refund_balance():
    with pytest.raises(ValueError):
        allocate_discount([Decimal("1.00")], Decimal("1.01"))
    with pytest.raises(DomainError):
        RefundCalculator.order_amount(Decimal("1.00"), Decimal("1.00"))


ZERO = Decimal("0.00")
