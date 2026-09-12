import hashlib
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.enums import ExecutionStatus, RefundStatus, TicketStatus
from app.core.errors import DomainError
from app.core.types import ZERO, cents
from app.db.session import write_transaction
from app.models.entities import Order, OrderItem, Refund, Ticket, TicketSubmission, User
from app.repositories.store import Store
from app.schemas.api import TicketCreate
from app.services.calculator import LineBalance, RefundCalculator

TICKET_TRANSITIONS = {
    TicketStatus.OPEN: {
        TicketStatus.IN_PROGRESS,
        TicketStatus.WAITING_CUSTOMER,
        TicketStatus.WAITING_APPROVAL,
        TicketStatus.RESOLVED,
        TicketStatus.CLOSED,
    },
    TicketStatus.IN_PROGRESS: {
        TicketStatus.WAITING_CUSTOMER,
        TicketStatus.WAITING_APPROVAL,
        TicketStatus.RESOLVED,
        TicketStatus.CLOSED,
    },
    TicketStatus.WAITING_CUSTOMER: {
        TicketStatus.OPEN,
        TicketStatus.IN_PROGRESS,
        TicketStatus.WAITING_APPROVAL,
        TicketStatus.RESOLVED,
        TicketStatus.CLOSED,
    },
    TicketStatus.WAITING_APPROVAL: {
        TicketStatus.IN_PROGRESS,
        TicketStatus.WAITING_CUSTOMER,
        TicketStatus.RESOLVED,
        TicketStatus.CLOSED,
    },
    TicketStatus.RESOLVED: {TicketStatus.CLOSED},
    TicketStatus.CLOSED: set(),
}
REFUND_TRANSITIONS = {
    RefundStatus.PENDING: {RefundStatus.APPROVED, RefundStatus.REJECTED},
    RefundStatus.APPROVED: {RefundStatus.PROCESSING, RefundStatus.REJECTED},
    RefundStatus.PROCESSING: {RefundStatus.SUCCESS, RefundStatus.FAILED},
    RefundStatus.SUCCESS: set(),
    RefundStatus.FAILED: {RefundStatus.PROCESSING, RefundStatus.REJECTED},
    RefundStatus.REJECTED: set(),
}


def transition(entity, target, allowed) -> None:
    if entity.status == target:
        return
    if target not in allowed[entity.status]:
        raise DomainError("INVALID_TRANSITION", f"不允许从 {entity.status} 变为 {target}")
    entity.status = target


def line_balance(store: Store, item: OrderItem, exclude_request_id: int | None = None) -> LineBalance:
    refunds = store.refunds(item.order_id, reserving=True, exclude_request_id=exclude_request_id)
    line_refunds = [refund for refund in refunds if refund.order_item_id == item.id]
    replacements = store.replacements(item.order_id, exclude_request_id)
    return LineBalance(
        paid_amount=item.paid_amount,
        quantity=item.quantity,
        reserved_amount=sum((r.amount for r in line_refunds), ZERO),
        reserved_quantity=sum(r.quantity or 0 for r in line_refunds),
        replacement_quantity=sum(r.quantity or 0 for r in replacements if r.order_item_id == item.id),
    )


def create_refund_record(
    store: Store,
    *,
    order_id: int,
    amount: Decimal,
    reason: str,
    idempotency_key: str,
    order_item_id: int | None = None,
    quantity: int | None = None,
    action_request_id: int | None = None,
) -> Refund:
    """Internal helper in an existing writer transaction; never a raw public refund API."""
    cents(amount)
    if amount <= ZERO:
        raise DomainError("INVALID_AMOUNT", "退款金额必须大于零", 422)
    order = store.get(Order, order_id)
    refunds = store.refunds(order_id, reserving=True)
    if amount > order.paid_amount - sum((r.amount for r in refunds), ZERO):
        raise DomainError("REFUND_EXCEEDS_BALANCE", "退款超过订单剩余额度")
    if order_item_id is not None:
        item = store.get(OrderItem, order_item_id)
        if item.order_id != order_id:
            raise DomainError("ITEM_ORDER_MISMATCH", "商品不属于该订单", 422)
        if quantity is None:
            raise DomainError("MISSING_QUANTITY", "商品退款需要数量", 422)
        if any(r.order_item_id is None for r in refunds):
            raise DomainError("WHOLE_ORDER_REFUND_EXISTS", "订单已有整单退款")
        calculated = RefundCalculator.item_amount(line_balance(store, item), quantity)
        if amount != calculated:
            raise DomainError("AMOUNT_MISMATCH", "金额与确定性计算结果不一致")
    elif quantity is not None or refunds or store.replacements(order_id):
        raise DomainError("WHOLE_ORDER_CONFLICT", "整单退款与已有售后记录冲突")
    elif amount != order.paid_amount:
        raise DomainError("AMOUNT_MISMATCH", "整单退款必须等于订单实付金额")
    return store.add(
        Refund(
            order_id=order_id,
            order_item_id=order_item_id,
            quantity=quantity,
            amount=amount,
            reason=reason,
            idempotency_key=idempotency_key,
            action_request_id=action_request_id,
        )
    )


def update_refund_status(refund: Refund, status: RefundStatus) -> None:
    transition(refund, status, REFUND_TRANSITIONS)


class BusinessService:
    def __init__(self, sessions: sessionmaker[Session]):
        self.sessions = sessions

    def get_user(self, user_id: int) -> User:
        with self.sessions() as session:
            return Store(session).get(User, user_id)

    def get_order(self, order_id: int) -> Order:
        with self.sessions() as session:
            return Store(session).get(Order, order_id)

    def get_order_items(self, order_id: int) -> list[OrderItem]:
        with self.sessions() as session:
            store = Store(session)
            store.get(Order, order_id)
            return store.items(order_id)

    def get_shipment(self, order_id: int):
        with self.sessions() as session:
            store = Store(session)
            store.get(Order, order_id)
            return store.shipment(order_id)

    def get_refunds(self, order_id: int) -> list[Refund]:
        with self.sessions() as session:
            store = Store(session)
            store.get(Order, order_id)
            return store.refunds(order_id)

    def get_ticket(self, ticket_id: int) -> Ticket:
        with self.sessions() as session:
            return Store(session).get(Ticket, ticket_id)

    def list_user_orders(self, user_id: int) -> list[Order]:
        with self.sessions() as session:
            store = Store(session)
            store.get(User, user_id)
            return store.orders(user_id)

    def create_ticket(self, data: TicketCreate, *, idempotency_key: str | None = None) -> Ticket:
        with write_transaction(self.sessions) as session:
            store = Store(session)
            store.get(User, data.user_id)
            payload_hash = hashlib.sha256(data.model_dump_json().encode()).hexdigest()
            if idempotency_key:
                if not 8 <= len(idempotency_key) <= 128:
                    raise DomainError("INVALID_IDEMPOTENCY_KEY", "工单幂等键长度需为 8–128", 422)
                existing = session.scalar(
                    select(TicketSubmission).where(
                        TicketSubmission.user_id == data.user_id,
                        TicketSubmission.idempotency_key == idempotency_key,
                    )
                )
                if existing:
                    if existing.payload_hash != payload_hash:
                        raise DomainError("IDEMPOTENCY_CONFLICT", "同一工单幂等键不能用于不同请求")
                    return store.get(Ticket, existing.ticket_id)
            if data.order_id is not None and store.get(Order, data.order_id).user_id != data.user_id:
                raise DomainError("ORDER_USER_MISMATCH", "订单不属于该用户", 403)
            ticket = store.add(Ticket(**data.model_dump()))
            if idempotency_key:
                store.add(
                    TicketSubmission(
                        user_id=data.user_id,
                        ticket_id=ticket.id,
                        idempotency_key=idempotency_key,
                        payload_hash=payload_hash,
                    )
                )
            return ticket

    def link_ticket_order(self, ticket_id: int, order_id: int) -> Ticket:
        with write_transaction(self.sessions) as session:
            store = Store(session)
            ticket = store.get(Ticket, ticket_id)
            if ticket.order_id is not None and ticket.order_id != order_id:
                raise DomainError("ORDER_ALREADY_LINKED", "工单已关联订单，不能改为其他订单")
            if ticket.status in (TicketStatus.RESOLVED, TicketStatus.CLOSED):
                raise DomainError("TICKET_TERMINAL", "已结束工单不能再关联订单")
            if store.get(Order, order_id).user_id != ticket.user_id:
                raise DomainError("ORDER_USER_MISMATCH", "订单不属于工单用户", 403)
            ticket.order_id = order_id
            return ticket

    def update_ticket_status(self, ticket_id: int, status: TicketStatus) -> Ticket:
        with write_transaction(self.sessions) as session:
            store = Store(session)
            ticket = store.get(Ticket, ticket_id)
            if any(
                r.execution_status
                in (
                    ExecutionStatus.WAITING_APPROVAL,
                    ExecutionStatus.WAITING_RETURN,
                    ExecutionStatus.READY,
                    ExecutionStatus.FAILED,
                )
                for r in store.ticket_requests(ticket_id)
            ):
                raise DomainError("ACTIVE_ACTION_EXISTS", "工单有未完成业务动作，需通过业务流程更新")
            if status == TicketStatus.WAITING_APPROVAL:
                raise DomainError("NO_APPROVAL", "必须由申请流程创建审批，不能手动进入等待审批状态")
            transition(ticket, status, TICKET_TRANSITIONS)
            return ticket

    def list_tickets(self, **filters):
        with self.sessions() as session:
            return Store(session).tickets(**filters)
