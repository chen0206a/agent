from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.enums import RESERVING_EXECUTION_STATUSES, RESERVING_REFUND_STATUSES, ActionType
from app.core.errors import not_found
from app.models.entities import (
    ActionRequest,
    Approval,
    AuditEvent,
    Base,
    Order,
    OrderItem,
    Refund,
    Shipment,
    Ticket,
)

Entity = TypeVar("Entity", bound=Base)


class Store:
    """SQL only. The calling service owns the transaction, never this repository."""

    def __init__(self, session: Session):
        self.session = session

    def get(self, model: type[Entity], identity: int) -> Entity:
        result = self.session.get(model, identity)
        if result is None:
            raise not_found(model.__tablename__, identity)
        return result

    def add(self, entity: Entity) -> Entity:
        self.session.add(entity)
        self.session.flush()
        return entity

    def orders(self, user_id: int) -> list[Order]:
        return list(self.session.scalars(select(Order).where(Order.user_id == user_id).order_by(Order.id)))

    def items(self, order_id: int) -> list[OrderItem]:
        return list(
            self.session.scalars(
                select(OrderItem).where(OrderItem.order_id == order_id).order_by(OrderItem.id)
            )
        )

    def shipment(self, order_id: int) -> Shipment | None:
        return self.session.scalar(select(Shipment).where(Shipment.order_id == order_id))

    def refunds(
        self, order_id: int, *, reserving: bool = False, exclude_request_id: int | None = None
    ) -> list[Refund]:
        query = select(Refund).where(Refund.order_id == order_id)
        if reserving:
            query = query.where(Refund.status.in_(RESERVING_REFUND_STATUSES))
        if exclude_request_id is not None:
            query = query.where(
                (Refund.action_request_id.is_(None)) | (Refund.action_request_id != exclude_request_id)
            )
        return list(self.session.scalars(query.order_by(Refund.id)))

    def replacements(self, order_id: int, exclude_request_id: int | None = None) -> list[ActionRequest]:
        query = select(ActionRequest).where(
            ActionRequest.order_id == order_id,
            ActionRequest.authorized_action == ActionType.REPLACE_ITEM,
            ActionRequest.execution_status.in_(RESERVING_EXECUTION_STATUSES),
        )
        if exclude_request_id is not None:
            query = query.where(ActionRequest.id != exclude_request_id)
        return list(self.session.scalars(query))

    def find_request(self, user_id: int, key: str) -> ActionRequest | None:
        return self.session.scalar(
            select(ActionRequest).where(
                ActionRequest.user_id == user_id,
                ActionRequest.idempotency_key == key,
            )
        )

    def request_refund(self, request_id: int) -> Refund | None:
        return self.session.scalar(select(Refund).where(Refund.action_request_id == request_id))

    def request_approval(self, request_id: int) -> Approval | None:
        return self.session.scalar(select(Approval).where(Approval.action_request_id == request_id))

    def ticket_requests(self, ticket_id: int) -> list[ActionRequest]:
        return list(
            self.session.scalars(
                select(ActionRequest).where(ActionRequest.ticket_id == ticket_id).order_by(ActionRequest.id)
            )
        )

    def tickets(self, *, user_id: int | None = None, status=None, limit: int = 50, offset: int = 0):
        query = select(Ticket)
        if user_id is not None:
            query = query.where(Ticket.user_id == user_id)
        if status is not None:
            query = query.where(Ticket.status == status)
        return list(self.session.scalars(query.order_by(Ticket.id).limit(limit).offset(offset)))

    def approvals(self, *, status=None, limit: int = 50, offset: int = 0):
        query = select(Approval)
        if status is not None:
            query = query.where(Approval.status == status)
        return list(self.session.scalars(query.order_by(Approval.id).limit(limit).offset(offset)))

    def events(self, request_id: int) -> list[AuditEvent]:
        return list(
            self.session.scalars(
                select(AuditEvent).where(AuditEvent.action_request_id == request_id).order_by(AuditEvent.id)
            )
        )
