from dataclasses import dataclass
from decimal import Decimal

from app.core.errors import DomainError
from app.core.types import ZERO, cents


def allocate_discount(line_totals: list[Decimal], discount: Decimal) -> list[Decimal]:
    """Largest remainder allocation: stable line order breaks ties, every cent is conserved."""
    totals = [cents(value) for value in line_totals]
    discount_cents = cents(discount)
    total = sum(totals)
    if not totals or any(value < 0 for value in totals) or not 0 <= discount_cents <= total:
        raise ValueError("Invalid discount allocation inputs")
    if total == 0:
        return [ZERO for _ in totals]
    shares = [discount_cents * value // total for value in totals]
    remainders = [discount_cents * value % total for value in totals]
    remaining = discount_cents - sum(shares)
    for index in sorted(range(len(totals)), key=lambda i: (-remainders[i], i))[:remaining]:
        shares[index] += 1
    return [Decimal(value) / 100 for value in shares]


@dataclass(frozen=True)
class LineBalance:
    paid_amount: Decimal
    quantity: int
    reserved_amount: Decimal = ZERO
    reserved_quantity: int = 0
    replacement_quantity: int = 0


class RefundCalculator:
    @staticmethod
    def order_amount(paid_amount: Decimal, reserved_amount: Decimal) -> Decimal:
        remaining = paid_amount - reserved_amount
        if remaining <= ZERO:
            raise DomainError("NO_REFUNDABLE_BALANCE", "订单没有剩余可退金额")
        return remaining

    @staticmethod
    def item_amount(balance: LineBalance, requested_quantity: int) -> Decimal:
        available = balance.quantity - balance.reserved_quantity - balance.replacement_quantity
        if requested_quantity <= 0 or requested_quantity > available:
            raise DomainError("QUANTITY_EXCEEDED", "申请数量超过剩余可售后数量")
        # Give indivisible remainder cents to the last units. A final partial refund
        # receives the remaining cents, so 3 × partial refunds exactly equal line paid.
        unit_cents = cents(balance.paid_amount) // balance.quantity
        refundable_quantity = balance.quantity - balance.reserved_quantity
        if requested_quantity == refundable_quantity and balance.replacement_quantity == 0:
            amount = balance.paid_amount - balance.reserved_amount
        else:
            amount = Decimal(unit_cents * requested_quantity) / 100
        if amount <= ZERO or amount + balance.reserved_amount > balance.paid_amount:
            raise DomainError("NO_REFUNDABLE_BALANCE", "商品没有足够的可退金额")
        return amount.quantize(Decimal("0.01"))
