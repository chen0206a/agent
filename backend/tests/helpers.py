from app.core.enums import ActionType, IssueType
from app.schemas.api import ActionCreate, TicketCreate


def request_for(
    business,
    order_id=1001,
    issue=IssueType.CANCEL,
    action=ActionType.CANCEL_AND_REFUND,
    *,
    quantity=None,
    evidence=False,
    key=None,
):
    order = business.get_order(order_id)
    ticket = business.create_ticket(
        TicketCreate(user_id=order.user_id, order_id=order.id, issue_type=issue, description="测试售后申请")
    )
    return ActionCreate(
        ticket_id=ticket.id,
        proposed_action=action,
        order_item_id=order_id * 10 + 1 if quantity is not None else None,
        quantity=quantity,
        evidence_provided=evidence,
        idempotency_key=key or f"test-{ticket.id:08}",
    )
