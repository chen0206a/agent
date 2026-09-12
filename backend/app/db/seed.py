from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.enums import (
    IssueType,
    OrderStatus,
    RefundStatus,
    ShipmentStatus,
    TicketStatus,
)
from app.core.errors import DomainError
from app.core.types import ZERO, utcnow
from app.db.session import write_transaction
from app.models.entities import Order, OrderItem, Shipment, Ticket, User
from app.repositories.store import Store
from app.services.business import create_refund_record, update_refund_status
from app.services.calculator import allocate_discount

# Stable IDs make examples and evaluation cases easy to reproduce.
SCENARIOS = [
    (1001, "未发货取消退款", OrderStatus.PAID, None),
    (1002, "已发货取消转物流拦截", OrderStatus.SHIPPED, None),
    (1003, "三件商品部分退款与尾差", OrderStatus.DELIVERED, 3),
    (1004, "超过七天无理由期限", OrderStatus.DELIVERED, 9),
    (1005, "final_sale 无理由退货", OrderStatus.DELIVERED, 2),
    (1006, "高金额未发货退款审批", OrderStatus.PAID, None),
    (1007, "商品已退款成功", OrderStatus.DELIVERED, 3),
    (1008, "商品退款处理中", OrderStatus.DELIVERED, 3),
    (1009, "运输异常与已有物流工单", OrderStatus.SHIPPED, None),
    (1010, "物流签收但用户未收到", OrderStatus.DELIVERED, 1),
    (1011, "破损商品需证据与审批", OrderStatus.DELIVERED, 2),
    (1012, "错发商品换货", OrderStatus.DELIVERED, 2),
    (1013, "少件按数量退款", OrderStatus.DELIVERED, 2),
    (1014, "待支付订单", OrderStatus.PENDING_PAYMENT, None),
    (1015, "已完成订单仍在售后期", OrderStatus.COMPLETED, 4),
    (1016, "有优惠的未发货订单", OrderStatus.PAID, None),
    (1017, "final_sale 质量问题仍可送审", OrderStatus.DELIVERED, 4),
    (1018, "高金额退货退款", OrderStatus.DELIVERED, 2),
    (1019, "质量售后恰好三十天", OrderStatus.DELIVERED, 30),
    (1020, "质量售后超过三十天", OrderStatus.DELIVERED, 31),
    (1021, "整单取消且退款成功", OrderStatus.CANCELLED, None),
    (1022, "正常运输中", OrderStatus.SHIPPED, None),
    (1023, "无理由申请恰好七天", OrderStatus.DELIVERED, 7),
    (1024, "商品标记不可无理由退货", OrderStatus.DELIVERED, 0),
]


def seed(sessions: sessionmaker[Session], *, now: datetime | None = None) -> dict:
    now = now or utcnow()
    with write_transaction(sessions) as session:
        # Never reset or silently merge into a database with a user's work.
        if session.scalar(select(func.count()).select_from(User)):
            return {"status": "skipped", "reason": "Database already contains users; nothing changed"}
        store = Store(session)
        for user_id in range(1, 11):
            store.add(
                User(
                    id=user_id,
                    name=f"演示用户{user_id:02}",
                    email=f"customer{user_id:02}@example.invalid",
                    created_at=now - timedelta(days=90),
                )
            )
        for order_id, label, status, age in SCENARIOS:
            user_id = (order_id - 1001) % 10 + 1
            delivered = now - timedelta(days=age) if age is not None else None
            shipped = (
                delivered - timedelta(days=2)
                if delivered
                else (now - timedelta(days=2) if status == OrderStatus.SHIPPED else None)
            )
            created = (shipped or now) - timedelta(days=3)
            paid_at = None if status == OrderStatus.PENDING_PAYMENT else created + timedelta(hours=1)
            prices, quantities, discount = [Decimal("49.99"), Decimal("20.00")], [2, 1], Decimal("7.01")
            if order_id in (1006, 1018):
                prices[0], quantities[0] = Decimal("2499.99"), 1
            if order_id == 1003:
                prices[0], quantities[0], discount = Decimal("33.34"), 3, Decimal("0.02")
            totals = [price * quantity for price, quantity in zip(prices, quantities, strict=True)]
            shares = allocate_discount(totals, discount)
            paid = sum(totals, ZERO) - discount if paid_at else ZERO
            store.add(
                Order(
                    id=order_id,
                    user_id=user_id,
                    status=status,
                    original_amount=sum(totals, ZERO),
                    discount_amount=discount,
                    paid_amount=paid,
                    currency="CNY",
                    created_at=created,
                    paid_at=paid_at,
                    shipped_at=shipped,
                    delivered_at=delivered,
                )
            )
            for index, (price, quantity, total, share) in enumerate(
                zip(prices, quantities, totals, shares, strict=True), start=1
            ):
                store.add(
                    OrderItem(
                        id=order_id * 10 + index,
                        order_id=order_id,
                        product_name=f"{label} / 商品{index}",
                        sku=f"DEMO-{order_id}-{index}",
                        quantity=quantity,
                        unit_price=price,
                        discount_amount=share,
                        paid_amount=total - share if paid_at else ZERO,
                        category="家居" if index == 1 else "配件",
                        refundable=order_id != 1024,
                        final_sale=order_id in (1005, 1017) and index == 1,
                    )
                )
            if shipped:
                shipment_status = (
                    ShipmentStatus.DELIVERED
                    if delivered
                    else ShipmentStatus.EXCEPTION
                    if order_id == 1009
                    else ShipmentStatus.IN_TRANSIT
                )
                store.add(
                    Shipment(
                        order_id=order_id,
                        carrier="模拟快递",
                        tracking_number=f"SIM-{order_id}",
                        status=shipment_status,
                        shipped_at=shipped,
                        delivered_at=delivered,
                        latest_event="已签收" if delivered else "转运延误" if order_id == 1009 else "运输中",
                        updated_at=delivered or now,
                    )
                )
        for order_id in (1007, 1008, 1021):
            item = store.get(OrderItem, order_id * 10 + 1)
            whole = order_id == 1021
            refund = create_refund_record(
                store,
                order_id=order_id,
                order_item_id=None if whole else item.id,
                quantity=None if whole else item.quantity,
                amount=store.get(Order, order_id).paid_amount if whole else item.paid_amount,
                reason="演示历史退款",
                idempotency_key=f"seed-refund-{order_id}",
            )
            refund.created_at = now - timedelta(hours=2)
            update_refund_status(refund, RefundStatus.APPROVED)
            update_refund_status(refund, RefundStatus.PROCESSING)
            if order_id != 1008:
                update_refund_status(refund, RefundStatus.SUCCESS)
            if not whole:
                item.returned_quantity = item.quantity
        for ticket_id, user_id, order_id, issue, status in (
            (1, 9, 1009, IssueType.NOT_RECEIVED, TicketStatus.IN_PROGRESS),
            (2, 1, 1011, IssueType.DAMAGED, TicketStatus.OPEN),
            (3, 10, None, IssueType.OTHER, TicketStatus.WAITING_CUSTOMER),
        ):
            store.add(
                Ticket(
                    id=ticket_id,
                    user_id=user_id,
                    order_id=order_id,
                    issue_type=issue,
                    description="演示已有工单，等待后续处理",
                    status=status,
                    created_at=now,
                    updated_at=now,
                )
            )
        issues = validate_seed(session)
        if issues:
            raise DomainError("SEED_INCONSISTENT", "; ".join(issues))
    return {
        "status": "created",
        "users": 10,
        "orders": 24,
        "order_items": 48,
        "refunds": 3,
        "tickets": 3,
        "base_time": now.isoformat(),
    }


def validate_seed(session: Session) -> list[str]:
    """Cross-table invariants which SQLite row CHECK constraints cannot express."""
    store, issues = Store(session), []
    for order in session.scalars(select(Order)):
        items = store.items(order.id)
        if sum((item.unit_price * item.quantity for item in items), ZERO) != order.original_amount:
            issues.append(f"order {order.id}: original total mismatch")
        if sum((item.discount_amount for item in items), ZERO) != order.discount_amount:
            issues.append(f"order {order.id}: discount mismatch")
        if sum((item.paid_amount for item in items), ZERO) != order.paid_amount:
            issues.append(f"order {order.id}: paid amount mismatch")
        shipment = store.shipment(order.id)
        if order.status in (OrderStatus.DELIVERED, OrderStatus.COMPLETED):
            if shipment is None or shipment.delivered_at != order.delivered_at:
                issues.append(f"order {order.id}: delivery mismatch")
        if order.status in (OrderStatus.PENDING_PAYMENT, OrderStatus.PAID) and shipment is not None:
            issues.append(f"order {order.id}: unexpected shipment")
        refunds = store.refunds(order.id, reserving=True)
        if sum((refund.amount for refund in refunds), ZERO) > order.paid_amount:
            issues.append(f"order {order.id}: refund exceeds paid")
    return issues
