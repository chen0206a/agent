from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from threading import Barrier

import pytest
from app.core.config import Settings
from app.core.enums import (
    ActionType as A,
)
from app.core.enums import (
    ApprovalStatus,
    OrderStatus,
    RefundStatus,
    TicketStatus,
)
from app.core.enums import (
    ExecutionStatus as E,
)
from app.core.enums import (
    IssueType as I,
)
from app.core.enums import (
    PolicyDecision as D,
)
from app.core.enums import (
    SimulationOutcome as S,
)
from app.core.errors import DomainError
from app.db.session import make_engine, make_sessions, write_transaction
from app.models.entities import ActionRequest, Approval, AuditEvent, Order, Refund, Shipment, Ticket
from app.repositories.store import Store
from app.schemas.api import ActionCreate, ApprovalReview, TicketCreate
from app.services.workflow import WorkflowService
from sqlalchemy import func, select

from backend.tests.conftest import NOW
from backend.tests.helpers import request_for

ACTOR = "admin:reviewer"


def approve(workflow, action):
    approval = next(row for row in workflow.list_approvals() if row.action_request_id == action.id)
    return workflow.review(approval.id, ApprovalReview(approve=True, reason="模拟证据核验通过"), actor=ACTOR)


def test_cancel_full_lifecycle_and_execution_idempotency(business, workflow):
    data = request_for(business)
    action = workflow.submit(data)
    assert (action.decision, action.execution_status, action.final_action) == (D.ALLOW, E.READY, None)
    assert business.get_order(1001).status == OrderStatus.PAID
    assert business.get_refunds(1001)[0].status == RefundStatus.APPROVED
    executed = workflow.execute(action.id, S.SUCCESS, actor=ACTOR)
    assert executed.final_action == A.CANCEL_AND_REFUND
    assert business.get_order(1001).status == OrderStatus.CANCELLED
    assert business.get_refunds(1001)[0].status == RefundStatus.SUCCESS
    events = len(workflow.events(action.id))
    assert workflow.execute(action.id, S.SUCCESS, actor=ACTOR).id == action.id
    assert workflow.submit(data).id == action.id
    assert len(workflow.events(action.id)) == events
    assert len(business.get_refunds(1001)) == 1


def test_return_cannot_refund_before_receipt_and_receipt_is_idempotent(business, workflow):
    action = workflow.submit(request_for(business, 1003, I.NO_REASON_RETURN, A.RETURN_AND_REFUND, quantity=1))
    assert action.execution_status == E.WAITING_RETURN
    with pytest.raises(DomainError, match="不能执行"):
        workflow.execute(action.id, S.SUCCESS, actor=ACTOR)
    assert workflow.receive_return(action.id, actor=ACTOR, note="模拟仓库收货").execution_status == E.READY
    workflow.receive_return(action.id, actor=ACTOR, note="重试")
    assert business.get_order_items(1003)[0].returned_quantity == 1
    workflow.execute(action.id, S.SUCCESS, actor=ACTOR)
    assert business.get_refunds(1003)[0].amount == Decimal("33.33")


def test_partial_refund_three_requests_exact_total(business, workflow):
    for _ in range(3):
        action = workflow.submit(
            request_for(business, 1003, I.NO_REASON_RETURN, A.RETURN_AND_REFUND, quantity=1)
        )
        workflow.receive_return(action.id, actor=ACTOR, note="收货")
        workflow.execute(action.id, S.SUCCESS, actor=ACTOR)
    assert [r.amount for r in business.get_refunds(1003)] == [
        Decimal("33.33"),
        Decimal("33.33"),
        Decimal("33.34"),
    ]
    blocked = workflow.submit(
        request_for(business, 1003, I.NO_REASON_RETURN, A.RETURN_AND_REFUND, quantity=1)
    )
    assert blocked.decision == D.DENY
    assert business.get_order_items(1003)[0].returned_quantity == 3


def test_high_amount_approval_is_not_payment_and_cannot_be_reversed(business, workflow):
    action = workflow.submit(request_for(business, 1006))
    assert action.execution_status == E.WAITING_APPROVAL
    with pytest.raises(DomainError):
        workflow.execute(action.id, S.SUCCESS, actor=ACTOR)
    with pytest.raises(DomainError):
        workflow.receive_return(action.id, actor=ACTOR, note="不能越过审批")
    approval = approve(workflow, action)
    assert approval.status == ApprovalStatus.APPROVED
    assert workflow.get_action(action.id).final_action is None
    assert business.get_refunds(1006)[0].status == RefundStatus.APPROVED
    assert approve(workflow, action).id == approval.id
    with pytest.raises(DomainError):
        workflow.review(approval.id, ApprovalReview(approve=False, reason="改变决定"), actor=ACTOR)
    workflow.execute(action.id, S.SUCCESS, actor=ACTOR)
    assert business.get_refunds(1006)[0].status == RefundStatus.SUCCESS


def test_rejection_releases_money_and_quantity(business, workflow):
    action = workflow.submit(
        request_for(business, 1011, I.DAMAGED, A.RETURN_AND_REFUND, quantity=2, evidence=True)
    )
    second = workflow.submit(
        request_for(business, 1011, I.DAMAGED, A.RETURN_AND_REFUND, quantity=1, evidence=True)
    )
    assert second.decision == D.DENY
    approval = workflow.list_approvals()[0]
    workflow.review(approval.id, ApprovalReview(approve=False, reason="证据不符"), actor=ACTOR)
    assert workflow.get_action(action.id).execution_status == E.REJECTED
    third = workflow.submit(
        request_for(business, 1011, I.DAMAGED, A.RETURN_AND_REFUND, quantity=2, evidence=True)
    )
    assert third.decision == D.REQUIRE_APPROVAL
    assert [r.status for r in business.get_refunds(1011)] == [RefundStatus.REJECTED, RefundStatus.PENDING]


def test_failure_retains_reservation_and_retry_uses_same_refund(business, workflow):
    action = workflow.submit(request_for(business, 1003, I.NO_REASON_RETURN, A.RETURN_AND_REFUND, quantity=3))
    workflow.receive_return(action.id, actor=ACTOR, note="已收三件")
    failed = workflow.execute(action.id, S.FAILURE, actor=ACTOR)
    assert failed.execution_status == E.FAILED
    assert failed.final_action is None
    assert business.get_refunds(1003)[0].status == RefundStatus.FAILED
    other = workflow.submit(request_for(business, 1003, I.NO_REASON_RETURN, A.RETURN_AND_REFUND, quantity=1))
    assert other.decision == D.DENY
    events = len(workflow.events(action.id))
    workflow.execute(action.id, S.FAILURE, actor=ACTOR)
    assert len(workflow.events(action.id)) == events
    assert workflow.execute(action.id, S.SUCCESS, actor=ACTOR).execution_status == E.SUCCESS
    assert len(business.get_refunds(1003)) == 1
    assert business.get_order_items(1003)[0].returned_quantity == 3


def test_same_key_different_payload_conflicts(business, workflow):
    data = request_for(business)
    workflow.submit(data)
    with pytest.raises(DomainError) as error:
        workflow.submit(data.model_copy(update={"evidence_provided": True}))
    assert error.value.code == "IDEMPOTENCY_CONFLICT"


def test_active_ticket_cannot_be_closed_or_have_second_action(business, workflow):
    data = request_for(business)
    workflow.submit(data)
    with pytest.raises(DomainError, match="未完成"):
        business.update_ticket_status(data.ticket_id, TicketStatus.CLOSED)
    with pytest.raises(DomainError, match="已有"):
        workflow.submit(data.model_copy(update={"idempotency_key": "another-key"}))


def test_missing_order_then_link_and_resubmit(business, workflow):
    ticket = business.create_ticket(TicketCreate(user_id=1, issue_type=I.CANCEL, description="取消但缺订单"))
    data = ActionCreate(
        ticket_id=ticket.id, proposed_action=A.CANCEL_AND_REFUND, idempotency_key="missing-order"
    )
    action = workflow.submit(data)
    assert action.decision == D.NEED_MORE_INFO
    business.link_ticket_order(ticket.id, 1001)
    retry = workflow.submit(data.model_copy(update={"idempotency_key": "with-order"}))
    assert retry.execution_status == E.READY
    assert workflow.get_action(action.id).snapshot_json["order"] is None


@pytest.mark.parametrize("order_id,issue", [(1002, I.CANCEL), (1010, I.NOT_RECEIVED)])
def test_logistics_redirect_does_not_refund_or_resolve_investigation(business, workflow, order_id, issue):
    action = workflow.submit(request_for(business, order_id, issue, A.CANCEL_AND_REFUND))
    assert action.proposed_action == A.CANCEL_AND_REFUND
    assert action.authorized_action == A.CREATE_LOGISTICS_TICKET
    workflow.execute(action.id, S.SUCCESS, actor=ACTOR)
    assert business.get_refunds(order_id) == []
    assert business.get_ticket(action.ticket_id).status == TicketStatus.IN_PROGRESS


def test_replacement_reserves_quantity_without_creating_refund(business, workflow):
    action = workflow.submit(
        request_for(business, 1012, I.WRONG_ITEM, A.REPLACE_ITEM, quantity=2, evidence=True)
    )
    assert business.get_refunds(1012) == []
    blocked = workflow.submit(
        request_for(business, 1012, I.NO_REASON_RETURN, A.RETURN_AND_REFUND, quantity=1)
    )
    assert blocked.decision == D.DENY
    approve(workflow, action)
    workflow.execute(action.id, S.SUCCESS, actor=ACTOR)
    assert workflow.get_action(action.id).final_action == A.REPLACE_ITEM
    assert business.get_refunds(1012) == []


def test_missing_item_refund_does_not_require_return(business, workflow):
    action = workflow.submit(
        request_for(business, 1013, I.MISSING_ITEM, A.REFUND_MISSING_ITEM, quantity=1, evidence=True)
    )
    approve(workflow, action)
    assert workflow.get_action(action.id).execution_status == E.READY
    workflow.execute(action.id, S.SUCCESS, actor=ACTOR)
    assert business.get_order_items(1013)[0].returned_quantity == 0
    assert business.get_refunds(1013)[0].status == RefundStatus.SUCCESS


def mark_shipped(sessions, order_id):
    with write_transaction(sessions) as session:
        order = session.get(Order, order_id)
        order.status, order.shipped_at = OrderStatus.SHIPPED, NOW
        session.add(
            Shipment(
                order_id=order_id,
                carrier="模拟",
                tracking_number="STALE-TEST",
                status="IN_TRANSIT",
                shipped_at=NOW,
                latest_event="刚发货",
            )
        )


def test_execution_rechecks_current_order_state(business, workflow, sessions):
    action = workflow.submit(request_for(business))
    mark_shipped(sessions, 1001)
    result = workflow.execute(action.id, S.SUCCESS, actor=ACTOR)
    assert result.execution_status == E.BLOCKED
    assert "STALE_DECISION" in result.rule_codes
    assert business.get_refunds(1001)[0].status == RefundStatus.REJECTED
    assert business.get_order(1001).status == OrderStatus.SHIPPED


def test_approval_cannot_override_changed_order(business, workflow, sessions):
    action = workflow.submit(request_for(business, 1006))
    mark_shipped(sessions, 1006)
    approval = approve(workflow, action)
    assert approval.status == ApprovalStatus.REJECTED
    assert workflow.get_action(action.id).execution_status == E.BLOCKED


def test_policy_version_change_invalidates_existing_authorization(business, workflow, sessions):
    action = workflow.submit(request_for(business))
    changed = WorkflowService(
        sessions, Settings(high_amount_threshold=Decimal("50.00"), _env_file=None), clock=lambda: NOW
    )
    assert changed.execute(action.id, S.SUCCESS, actor=ACTOR).execution_status == E.BLOCKED
    assert business.get_refunds(1001)[0].status == RefundStatus.REJECTED


def test_return_eligibility_uses_original_application_time(business, workflow, sessions):
    action = workflow.submit(request_for(business, 1023, I.NO_REASON_RETURN, A.RETURN_AND_REFUND, quantity=1))
    delayed = WorkflowService(sessions, Settings(_env_file=None), clock=lambda: NOW + timedelta(days=10))
    assert delayed.receive_return(action.id, actor=ACTOR, note="仓库十天后收货").execution_status == E.READY
    assert delayed.execute(action.id, S.SUCCESS, actor=ACTOR).execution_status == E.SUCCESS


def test_submit_rolls_back_request_reservation_and_approval_on_audit_failure(
    business, workflow, sessions, monkeypatch
):
    data = request_for(business, 1006)

    def fail(*args, **kwargs):
        raise RuntimeError("audit storage failed")

    monkeypatch.setattr(workflow, "_event", fail)
    with pytest.raises(RuntimeError):
        workflow.submit(data)
    with sessions() as session:
        for model in (ActionRequest, Approval, AuditEvent):
            assert session.scalar(select(func.count()).select_from(model)) == 0
        assert session.scalar(select(func.count()).select_from(Refund)) == 3
        assert session.get(Ticket, data.ticket_id).status == TicketStatus.OPEN


@pytest.mark.parametrize("same_key", [True, False])
def test_concurrent_submissions_use_database_writer_lock(business, application, same_key):
    first = request_for(business)
    second = first if same_key else request_for(business)
    barrier = Barrier(2)

    def submit(data):
        # Independent engines/connections model separate workers; no Python lock.
        engine = make_engine(application.state.settings.resolved_database_url)
        try:
            flows = WorkflowService(make_sessions(engine), application.state.settings, clock=lambda: NOW)
            barrier.wait(timeout=10)
            return flows.submit(data)
        finally:
            engine.dispose()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(submit, data) for data in (first, second)]
        results = [future.result(timeout=25) for future in futures]
    assert len(business.get_refunds(1001)) == 1
    if same_key:
        assert results[0].id == results[1].id
    else:
        assert {result.decision for result in results} == {D.ALLOW, D.DENY}


def test_preview_is_read_only(business, workflow, sessions):
    data = request_for(business)
    result = workflow.preview(data)
    assert result.decision == D.ALLOW
    with sessions() as session:
        assert Store(session).ticket_requests(data.ticket_id) == []
        assert Store(session).refunds(1001) == []


def test_execution_audit_failure_rolls_back_payment_and_order(business, workflow, monkeypatch):
    action = workflow.submit(request_for(business))
    original_event = workflow._event

    def fail_on_success(store, request, kind, actor, **data):
        if kind == "SIMULATION_SUCCEEDED":
            raise RuntimeError("audit failed after payment status changed")
        return original_event(store, request, kind, actor, **data)

    monkeypatch.setattr(workflow, "_event", fail_on_success)
    with pytest.raises(RuntimeError):
        workflow.execute(action.id, S.SUCCESS, actor=ACTOR)
    assert business.get_order(1001).status == OrderStatus.PAID
    assert business.get_refunds(1001)[0].status == RefundStatus.APPROVED
    assert workflow.get_action(action.id).execution_status == E.READY
    assert len(workflow.events(action.id)) == 1


def test_concurrent_execution_records_single_success(business, workflow, application):
    action = workflow.submit(request_for(business))
    barrier = Barrier(2)

    def execute_once():
        engine = make_engine(application.state.settings.resolved_database_url)
        try:
            flows = WorkflowService(make_sessions(engine), application.state.settings, clock=lambda: NOW)
            barrier.wait(timeout=10)
            return flows.execute(action.id, S.SUCCESS, actor=ACTOR).execution_status
        finally:
            engine.dispose()

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(execute_once) for _ in range(2)]
        assert [future.result(timeout=25) for future in futures] == [E.SUCCESS, E.SUCCESS]
    assert (
        len([event for event in workflow.events(action.id) if event.event_type == "SIMULATION_SUCCEEDED"])
        == 1
    )
    assert len(business.get_refunds(1001)) == 1
