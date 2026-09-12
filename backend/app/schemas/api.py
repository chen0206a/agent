from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, model_validator

from app.core.enums import (
    ActionType,
    ApprovalStatus,
    ExecutionStatus,
    IssueType,
    OrderStatus,
    PolicyDecision,
    Priority,
    RefundStatus,
    RiskLevel,
    ShipmentStatus,
    SimulationOutcome,
    TicketStatus,
)

Amount = Annotated[Decimal, PlainSerializer(lambda v: format(v, ".2f"), return_type=str, when_used="json")]
PositiveId = Annotated[int, Field(gt=0, strict=True)]
Description = Annotated[str, Field(min_length=1, max_length=4000)]


class Schema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid", str_strip_whitespace=True)


class UserRead(Schema):
    id: int
    name: str
    email: str
    created_at: datetime


class OrderRead(Schema):
    id: int
    user_id: int
    status: OrderStatus
    currency: str
    original_amount: Amount
    discount_amount: Amount
    payable_amount: Amount
    paid_amount: Amount
    created_at: datetime
    paid_at: datetime | None
    shipped_at: datetime | None
    delivered_at: datetime | None


class ItemRead(Schema):
    id: int
    order_id: int
    product_name: str
    sku: str
    quantity: int
    unit_price: Amount
    discount_amount: Amount
    paid_amount: Amount
    category: str
    refundable: bool
    final_sale: bool
    returned_quantity: int


class ShipmentRead(Schema):
    id: int
    order_id: int
    carrier: str
    tracking_number: str
    status: ShipmentStatus
    shipped_at: datetime
    delivered_at: datetime | None
    latest_event: str
    updated_at: datetime


class RefundRead(Schema):
    id: int
    order_id: int
    order_item_id: int | None
    quantity: int | None
    action_request_id: int | None
    amount: Amount
    reason: str
    status: RefundStatus
    created_at: datetime
    updated_at: datetime


class TicketCreate(Schema):
    user_id: PositiveId
    order_id: PositiveId | None = None
    issue_type: IssueType
    description: Description


class TicketRead(TicketCreate):
    id: int
    status: TicketStatus
    priority: Priority
    created_at: datetime
    updated_at: datetime


class TicketUpdate(Schema):
    status: TicketStatus


class TicketLink(Schema):
    order_id: PositiveId


class ActionCreate(Schema):
    ticket_id: PositiveId
    proposed_action: ActionType
    order_item_id: PositiveId | None = None
    quantity: Annotated[int, Field(strict=True, gt=0, le=10000)] | None = None
    evidence_provided: bool = Field(default=False, strict=True)
    idempotency_key: Annotated[str, Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]

    @model_validator(mode="after")
    def validate_scope(self):
        if self.proposed_action in (ActionType.CANCEL_AND_REFUND, ActionType.CREATE_LOGISTICS_TICKET):
            if self.order_item_id is not None or self.quantity is not None:
                raise ValueError("Whole-order actions cannot specify item or quantity")
        elif (self.order_item_id is None) != (self.quantity is None):
            raise ValueError("Item and quantity must be supplied together")
        return self


class PolicyResult(Schema):
    decision: PolicyDecision
    authorized_action: ActionType | None = None
    amount: Amount = Decimal("0.00")
    risk_level: RiskLevel = RiskLevel.LOW
    rule_codes: list[str]
    explanation: str
    policy_version: str


class ActionRead(PolicyResult):
    id: int
    ticket_id: int
    user_id: int
    order_id: int | None
    order_item_id: int | None
    quantity: int | None
    idempotency_key: str
    proposed_action: ActionType
    final_action: ActionType | None
    execution_status: ExecutionStatus
    evidence_provided: bool
    return_received_at: datetime | None
    snapshot_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class ApprovalRead(Schema):
    id: int
    ticket_id: int
    action_request_id: int
    action_type: ActionType
    requested_amount: Amount
    status: ApprovalStatus
    reviewer: str | None
    reason: str | None
    created_at: datetime
    reviewed_at: datetime | None


class ApprovalReview(Schema):
    approve: bool = Field(strict=True)
    reason: Description


class ReturnReceipt(Schema):
    note: Description


class ExecuteRequest(Schema):
    outcome: SimulationOutcome = SimulationOutcome.SUCCESS


class AuditRead(Schema):
    id: int
    action_request_id: int
    event_type: str
    actor: str
    data_json: dict[str, Any]
    created_at: datetime


class HealthRead(Schema):
    status: Literal["ok"] = "ok"
    version: str = "0.3.0"
    mode: Literal["simulation"] = "simulation"


class ErrorBody(Schema):
    code: str
    message: str
    request_id: str


class ErrorRead(Schema):
    error: ErrorBody
