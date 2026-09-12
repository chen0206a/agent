from typing import Annotated

from fastapi import APIRouter, Header, Query, Request
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.dependencies import Admin, Business, Current, Workflow
from app.core.enums import ApprovalStatus, TicketStatus
from app.core.errors import DomainError
from app.schemas.api import (
    ActionCreate,
    ActionRead,
    ApprovalRead,
    ApprovalReview,
    AuditRead,
    ErrorRead,
    ExecuteRequest,
    HealthRead,
    ItemRead,
    OrderRead,
    PolicyResult,
    RefundRead,
    ReturnReceipt,
    ShipmentRead,
    TicketCreate,
    TicketLink,
    TicketRead,
    TicketUpdate,
    UserRead,
)

router = APIRouter(responses={code: {"model": ErrorRead} for code in (401, 403, 404, 409, 422, 500, 503)})
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.get("/health", response_model=HealthRead, tags=["system"])
def health(request: Request):
    try:
        with request.app.state.sessions() as session:
            session.execute(text("SELECT id FROM users LIMIT 1"))
    except SQLAlchemyError as error:
        raise DomainError("DATABASE_NOT_READY", "数据库未就绪，请先执行 init-db", 503) from error
    return HealthRead()


@router.get("/users/{user_id}", response_model=UserRead, tags=["stage1"])
def get_user(user_id: int, identity: Current, service: Business):
    identity.require_owner(user_id)
    return service.get_user(user_id)


@router.get("/users/{user_id}/orders", response_model=list[OrderRead], tags=["stage1"])
def user_orders(user_id: int, identity: Current, service: Business):
    identity.require_owner(user_id)
    return service.list_user_orders(user_id)


@router.get("/orders/{order_id}", response_model=OrderRead, tags=["stage1"])
def get_order(order_id: int, identity: Current, service: Business):
    order = service.get_order(order_id)
    identity.require_owner(order.user_id)
    return order


@router.get("/orders/{order_id}/items", response_model=list[ItemRead], tags=["stage1"])
def items(order_id: int, identity: Current, service: Business):
    identity.require_owner(service.get_order(order_id).user_id)
    return service.get_order_items(order_id)


@router.get("/orders/{order_id}/shipment", response_model=ShipmentRead | None, tags=["stage1"])
def shipment(order_id: int, identity: Current, service: Business):
    identity.require_owner(service.get_order(order_id).user_id)
    return service.get_shipment(order_id)


@router.get("/orders/{order_id}/refunds", response_model=list[RefundRead], tags=["stage1"])
def refunds(order_id: int, identity: Current, service: Business):
    identity.require_owner(service.get_order(order_id).user_id)
    return service.get_refunds(order_id)


@router.get("/tickets", response_model=list[TicketRead], tags=["stage1"])
def tickets(
    identity: Current,
    service: Business,
    status: TicketStatus | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
):
    return service.list_tickets(
        user_id=None if identity.role == "admin" else identity.user_id,
        status=status,
        limit=limit,
        offset=offset,
    )


@router.get("/tickets/{ticket_id}", response_model=TicketRead, tags=["stage1"])
def get_ticket(ticket_id: int, identity: Current, service: Business):
    ticket = service.get_ticket(ticket_id)
    identity.require_owner(ticket.user_id)
    return ticket


@router.post("/tickets", response_model=TicketRead, status_code=201, tags=["stage1"])
def create_ticket(
    data: TicketCreate,
    identity: Current,
    service: Business,
    idempotency_key: Annotated[str | None, Header(min_length=8, max_length=128)] = None,
):
    identity.require_owner(data.user_id)
    return service.create_ticket(data, idempotency_key=idempotency_key)


@router.patch("/tickets/{ticket_id}/order", response_model=TicketRead, tags=["stage2"])
def link_order(ticket_id: int, data: TicketLink, identity: Current, service: Business):
    identity.require_owner(service.get_ticket(ticket_id).user_id)
    return service.link_ticket_order(ticket_id, data.order_id)


@router.patch("/tickets/{ticket_id}/status", response_model=TicketRead, tags=["stage2"])
def ticket_status(ticket_id: int, data: TicketUpdate, identity: Admin, service: Business):
    return service.update_ticket_status(ticket_id, data.status)


@router.post("/policy/evaluate", response_model=PolicyResult, tags=["stage2"])
def evaluate(data: ActionCreate, identity: Current, service: Business, flows: Workflow):
    identity.require_owner(service.get_ticket(data.ticket_id).user_id)
    return flows.preview(data)


@router.post("/actions", response_model=ActionRead, tags=["stage2"])
def submit(data: ActionCreate, identity: Current, service: Business, flows: Workflow):
    identity.require_owner(service.get_ticket(data.ticket_id).user_id)
    return flows.submit(data)


@router.get("/actions/{action_id}", response_model=ActionRead, tags=["stage2"])
def action(action_id: int, identity: Current, flows: Workflow):
    result = flows.get_action(action_id)
    identity.require_owner(result.user_id)
    return result


@router.get("/tickets/{ticket_id}/actions", response_model=list[ActionRead], tags=["stage2"])
def ticket_actions(ticket_id: int, identity: Current, service: Business, flows: Workflow):
    identity.require_owner(service.get_ticket(ticket_id).user_id)
    return flows.ticket_actions(ticket_id)


@router.get("/approvals", response_model=list[ApprovalRead], tags=["stage2-admin"])
def approvals(
    identity: Admin,
    flows: Workflow,
    status: ApprovalStatus | None = None,
    limit: Limit = 50,
    offset: Offset = 0,
):
    return flows.list_approvals(status=status, limit=limit, offset=offset)


@router.get("/approvals/{approval_id}", response_model=ApprovalRead, tags=["stage2-admin"])
def approval(approval_id: int, identity: Admin, flows: Workflow):
    return flows.get_approval(approval_id)


@router.post("/approvals/{approval_id}/review", response_model=ApprovalRead, tags=["stage2-admin"])
def review(approval_id: int, data: ApprovalReview, identity: Admin, flows: Workflow):
    return flows.review(approval_id, data, actor=identity.actor)


@router.post("/actions/{action_id}/return-receipt", response_model=ActionRead, tags=["stage2-admin"])
def receive_return(action_id: int, data: ReturnReceipt, identity: Admin, flows: Workflow):
    return flows.receive_return(action_id, actor=identity.actor, note=data.note)


@router.post("/actions/{action_id}/simulate-execution", response_model=ActionRead, tags=["stage2-admin"])
def execute(action_id: int, data: ExecuteRequest, identity: Admin, flows: Workflow):
    return flows.execute(action_id, data.outcome, actor=identity.actor)


@router.get("/actions/{action_id}/audit", response_model=list[AuditRead], tags=["stage2-admin"])
def audit(action_id: int, identity: Admin, flows: Workflow):
    return flows.events(action_id)
