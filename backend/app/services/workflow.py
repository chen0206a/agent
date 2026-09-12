import hashlib
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.core.enums import (
    ActionType,
    ApprovalStatus,
    ExecutionStatus,
    OrderStatus,
    PolicyDecision,
    Priority,
    RefundStatus,
    RiskLevel,
    SimulationOutcome,
    TicketStatus,
)
from app.core.errors import DomainError
from app.core.types import ZERO, utcnow
from app.db.session import write_transaction
from app.models.entities import ActionRequest, Approval, AuditEvent, Order, OrderItem, Ticket
from app.repositories.store import Store
from app.schemas.api import ActionCreate, ApprovalReview, ItemRead, OrderRead, PolicyResult, ShipmentRead
from app.services.business import create_refund_record, line_balance, update_refund_status
from app.services.policy import PolicyContext, PolicyEngine

MONEY_ACTIONS = {
    ActionType.CANCEL_AND_REFUND,
    ActionType.RETURN_AND_REFUND,
    ActionType.REFUND_MISSING_ITEM,
}
ACTIVE = {
    ExecutionStatus.WAITING_APPROVAL,
    ExecutionStatus.WAITING_RETURN,
    ExecutionStatus.READY,
    ExecutionStatus.FAILED,
}


class WorkflowService:
    def __init__(
        self, sessions: sessionmaker[Session], settings: Settings, clock: Callable[[], datetime] = utcnow
    ):
        self.sessions, self.policy, self.clock = sessions, PolicyEngine(settings), clock

    def _context(
        self, store: Store, ticket: Ticket, request: ActionCreate, exclude_request_id: int | None = None
    ) -> PolicyContext:
        order = store.get(Order, ticket.order_id) if ticket.order_id else None
        item = store.get(OrderItem, request.order_item_id) if request.order_item_id else None
        if order is not None and order.user_id != ticket.user_id:
            raise DomainError("ORDER_USER_MISMATCH", "订单归属不一致", 403)
        if item is not None and (order is None or item.order_id != order.id):
            raise DomainError("ITEM_ORDER_MISMATCH", "商品不属于工单订单", 422)
        shipment = store.shipment(order.id) if order else None
        refunds = (
            store.refunds(order.id, reserving=True, exclude_request_id=exclude_request_id) if order else []
        )
        return PolicyContext(
            issue_type=ticket.issue_type,
            order=OrderRead.model_validate(order) if order else None,
            item=ItemRead.model_validate(item) if item else None,
            shipment=ShipmentRead.model_validate(shipment) if shipment else None,
            line_balance=line_balance(store, item, exclude_request_id) if item else None,
            reserved_amount=sum((r.amount for r in refunds), ZERO),
            whole_refund_exists=any(r.order_item_id is None for r in refunds),
            replacement_exists=bool(order and store.replacements(order.id, exclude_request_id)),
        )

    @staticmethod
    def _snapshot(context: PolicyContext, now: datetime) -> dict:
        balance = asdict(context.line_balance) if context.line_balance else None
        if balance:
            balance = {key: str(value) if key.endswith("amount") else value for key, value in balance.items()}
        return {
            "evaluated_at": now.isoformat(),
            "issue_type": context.issue_type.value,
            "order": context.order.model_dump(mode="json") if context.order else None,
            "item": context.item.model_dump(mode="json") if context.item else None,
            "shipment": context.shipment.model_dump(mode="json") if context.shipment else None,
            "line_balance": balance,
            "reserved_amount": str(context.reserved_amount),
            "whole_refund_exists": context.whole_refund_exists,
            "replacement_exists": context.replacement_exists,
        }

    def _event(self, store: Store, action: ActionRequest, kind: str, actor: str, **data) -> None:
        store.add(
            AuditEvent(
                action_request_id=action.id,
                event_type=kind,
                actor=actor,
                data_json=data,
                created_at=self.clock(),
            )
        )

    def preview(self, data: ActionCreate) -> PolicyResult:
        with self.sessions() as session:
            store = Store(session)
            ticket = store.get(Ticket, data.ticket_id)
            return self.policy.evaluate(data, self._context(store, ticket, data), now=self.clock())

    def submit(self, data: ActionCreate) -> ActionRequest:
        payload_hash = hashlib.sha256(data.model_dump_json().encode()).hexdigest()
        with write_transaction(self.sessions) as session:
            store = Store(session)
            ticket = store.get(Ticket, data.ticket_id)
            existing = store.find_request(ticket.user_id, data.idempotency_key)
            if existing:
                if existing.payload_hash != payload_hash:
                    raise DomainError("IDEMPOTENCY_CONFLICT", "同一幂等键不能用于不同请求")
                return existing
            if ticket.status in (TicketStatus.CLOSED, TicketStatus.RESOLVED):
                raise DomainError("TICKET_TERMINAL", "已结束工单不能提交新动作")
            if any(r.execution_status in ACTIVE for r in store.ticket_requests(ticket.id)):
                raise DomainError("ACTIVE_ACTION_EXISTS", "此工单已有待完成动作")
            now = self.clock()
            context = self._context(store, ticket, data)
            result = self.policy.evaluate(data, context, now=now)
            action = store.add(
                ActionRequest(
                    ticket_id=ticket.id,
                    user_id=ticket.user_id,
                    order_id=ticket.order_id,
                    order_item_id=data.order_item_id,
                    quantity=data.quantity,
                    idempotency_key=data.idempotency_key,
                    payload_hash=payload_hash,
                    proposed_action=data.proposed_action,
                    evidence_provided=data.evidence_provided,
                    **result.model_dump(),
                    execution_status=ExecutionStatus.BLOCKED,
                    snapshot_json=self._snapshot(context, now),
                    created_at=now,
                    updated_at=now,
                )
            )
            if result.decision in (PolicyDecision.ALLOW, PolicyDecision.REQUIRE_APPROVAL):
                if result.authorized_action in MONEY_ACTIONS:
                    refund = create_refund_record(
                        store,
                        order_id=ticket.order_id,
                        amount=result.amount,
                        reason=ticket.issue_type.value,
                        idempotency_key=f"action:{action.id}",
                        order_item_id=data.order_item_id,
                        quantity=data.quantity,
                        action_request_id=action.id,
                    )
                    if result.decision == PolicyDecision.ALLOW:
                        update_refund_status(refund, RefundStatus.APPROVED)
                if result.decision == PolicyDecision.REQUIRE_APPROVAL:
                    store.add(
                        Approval(
                            ticket_id=ticket.id,
                            action_request_id=action.id,
                            action_type=result.authorized_action,
                            requested_amount=result.amount,
                            created_at=now,
                        )
                    )
                    action.execution_status = ExecutionStatus.WAITING_APPROVAL
                    ticket.status = TicketStatus.WAITING_APPROVAL
                else:
                    self._ready(action, ticket)
                ticket.priority = Priority.HIGH if result.risk_level == RiskLevel.HIGH else Priority.NORMAL
            else:
                ticket.status = (
                    TicketStatus.WAITING_CUSTOMER
                    if result.decision == PolicyDecision.NEED_MORE_INFO
                    else TicketStatus.IN_PROGRESS
                )
            self._event(
                store,
                action,
                "POLICY_EVALUATED",
                f"user:{ticket.user_id}",
                result=result.model_dump(mode="json"),
                snapshot=action.snapshot_json,
            )
            return action

    @staticmethod
    def _ready(action: ActionRequest, ticket: Ticket) -> None:
        if action.authorized_action == ActionType.RETURN_AND_REFUND and not action.return_received_at:
            action.execution_status = ExecutionStatus.WAITING_RETURN
            ticket.status = TicketStatus.WAITING_CUSTOMER
        else:
            action.execution_status = ExecutionStatus.READY
            ticket.status = TicketStatus.IN_PROGRESS

    @staticmethod
    def _data(action: ActionRequest) -> ActionCreate:
        return ActionCreate(
            ticket_id=action.ticket_id,
            proposed_action=action.proposed_action,
            order_item_id=action.order_item_id,
            quantity=action.quantity,
            evidence_provided=action.evidence_provided,
            idempotency_key=action.idempotency_key,
        )

    def _revalidate(self, store: Store, action: ActionRequest, actor: str) -> bool:
        ticket = store.get(Ticket, action.ticket_id)
        data = self._data(action)
        context = self._context(store, ticket, data, action.id)
        # Eligibility is assessed at submission time; warehouse/approval delays do
        # not consume a customer's application window. Current balances/status still apply.
        result = self.policy.evaluate(data, context, now=action.created_at)
        valid = (
            result.decision in (PolicyDecision.ALLOW, PolicyDecision.REQUIRE_APPROVAL)
            and result.authorized_action == action.authorized_action
            and result.amount == action.amount
            and result.policy_version == action.policy_version
        )
        self._event(
            store,
            action,
            "POLICY_REVALIDATED",
            actor,
            valid=valid,
            result=result.model_dump(mode="json"),
            snapshot=self._snapshot(context, self.clock()),
        )
        if valid:
            return True
        action.decision = PolicyDecision.DENY
        action.execution_status = ExecutionStatus.BLOCKED
        action.rule_codes = ["STALE_DECISION", *result.rule_codes]
        action.explanation = "业务数据或政策已变化，原授权作废，请重新申请"
        refund = store.request_refund(action.id)
        if refund:
            update_refund_status(refund, RefundStatus.REJECTED)
        approval = store.request_approval(action.id)
        if approval and approval.status == ApprovalStatus.PENDING:
            approval.status, approval.reviewer = ApprovalStatus.REJECTED, actor
            approval.reason, approval.reviewed_at = action.explanation, self.clock()
        ticket.status = TicketStatus.IN_PROGRESS
        self._event(store, action, "AUTHORIZATION_INVALIDATED", actor, reason=action.explanation)
        return False

    def review(self, approval_id: int, data: ApprovalReview, *, actor: str) -> Approval:
        with write_transaction(self.sessions) as session:
            store = Store(session)
            approval = store.get(Approval, approval_id)
            desired = ApprovalStatus.APPROVED if data.approve else ApprovalStatus.REJECTED
            if approval.status != ApprovalStatus.PENDING:
                if approval.status != desired:
                    raise DomainError("APPROVAL_ALREADY_REVIEWED", "审批已处理，不能改变结果")
                return approval
            action = store.get(ActionRequest, approval.action_request_id)
            ticket = store.get(Ticket, approval.ticket_id)
            if data.approve and not self._revalidate(store, action, actor):
                return approval
            approval.status, approval.reviewer = desired, actor
            approval.reason, approval.reviewed_at = data.reason, self.clock()
            refund = store.request_refund(action.id)
            if data.approve:
                if refund:
                    update_refund_status(refund, RefundStatus.APPROVED)
                # decision remains REQUIRE_APPROVAL as historical policy output.
                self._ready(action, ticket)
            else:
                action.execution_status = ExecutionStatus.REJECTED
                if refund:
                    update_refund_status(refund, RefundStatus.REJECTED)
                ticket.status = TicketStatus.RESOLVED
            self._event(store, action, "APPROVAL_REVIEWED", actor, status=desired.value, reason=data.reason)
            return approval

    def receive_return(self, request_id: int, *, actor: str, note: str) -> ActionRequest:
        with write_transaction(self.sessions) as session:
            store = Store(session)
            action = store.get(ActionRequest, request_id)
            if action.return_received_at:
                return action
            if action.execution_status != ExecutionStatus.WAITING_RETURN:
                raise DomainError("RETURN_NOT_EXPECTED", "动作尚未获准退货或不需要退货")
            if not self._revalidate(store, action, actor):
                return action
            item = store.get(OrderItem, action.order_item_id)
            if item.returned_quantity + action.quantity > item.quantity:
                raise DomainError("RETURN_QUANTITY_EXCEEDED", "实收退货数量超过订单商品数量")
            item.returned_quantity += action.quantity
            action.return_received_at = self.clock()
            self._ready(action, store.get(Ticket, action.ticket_id))
            self._event(store, action, "RETURN_RECEIVED", actor, note=note, quantity=action.quantity)
            return action

    def execute(self, request_id: int, outcome: SimulationOutcome, *, actor: str) -> ActionRequest:
        with write_transaction(self.sessions) as session:
            store = Store(session)
            action = store.get(ActionRequest, request_id)
            if action.execution_status == ExecutionStatus.SUCCESS:
                return action
            if action.execution_status == ExecutionStatus.FAILED and outcome == SimulationOutcome.FAILURE:
                return action
            if action.execution_status not in (ExecutionStatus.READY, ExecutionStatus.FAILED):
                raise DomainError("ACTION_NOT_READY", "动作仍需审批、收货或补充信息，不能执行")
            approval = store.request_approval(action.id)
            if action.decision == PolicyDecision.REQUIRE_APPROVAL and (
                approval is None or approval.status != ApprovalStatus.APPROVED
            ):
                raise DomainError("APPROVAL_REQUIRED", "缺少有效的人工批准")
            if not self._revalidate(store, action, actor):
                return action
            ticket = store.get(Ticket, action.ticket_id)
            refund = store.request_refund(action.id)
            if refund:
                update_refund_status(refund, RefundStatus.PROCESSING)
            if outcome == SimulationOutcome.FAILURE:
                if refund:
                    update_refund_status(refund, RefundStatus.FAILED)
                action.execution_status = ExecutionStatus.FAILED
                ticket.status = TicketStatus.IN_PROGRESS
                # Failed simulation retains the reservation. Retry this same action;
                # no second refund record or return-receipt confirmation is needed.
                self._event(store, action, "SIMULATION_FAILED", actor, reservation_retained=True)
                return action
            if refund:
                update_refund_status(refund, RefundStatus.SUCCESS)
            if action.authorized_action == ActionType.CANCEL_AND_REFUND:
                store.get(Order, action.order_id).status = OrderStatus.CANCELLED
            action.execution_status = ExecutionStatus.SUCCESS
            action.final_action = action.authorized_action
            # Creating a logistics work item completes the action, not the investigation.
            ticket.status = (
                TicketStatus.IN_PROGRESS
                if action.final_action == ActionType.CREATE_LOGISTICS_TICKET
                else TicketStatus.RESOLVED
            )
            self._event(
                store,
                action,
                "SIMULATION_SUCCEEDED",
                actor,
                action_type=action.final_action.value,
                amount=str(action.amount),
                payment_provider="local-simulator",
                result="replacement_dispatched" if action.final_action == ActionType.REPLACE_ITEM else "done",
            )
            return action

    def get_action(self, request_id: int) -> ActionRequest:
        with self.sessions() as session:
            return Store(session).get(ActionRequest, request_id)

    def get_approval(self, approval_id: int) -> Approval:
        with self.sessions() as session:
            return Store(session).get(Approval, approval_id)

    def list_approvals(self, **filters):
        with self.sessions() as session:
            return Store(session).approvals(**filters)

    def events(self, request_id: int):
        with self.sessions() as session:
            store = Store(session)
            store.get(ActionRequest, request_id)
            return store.events(request_id)

    def ticket_actions(self, ticket_id: int):
        with self.sessions() as session:
            store = Store(session)
            store.get(Ticket, ticket_id)
            return store.ticket_requests(ticket_id)
