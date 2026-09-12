from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

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
    RunStatus,
    ShipmentStatus,
    TicketStatus,
)
from app.core.types import ZERO, Money, UTCDateTime, utcnow


class Base(DeclarativeBase):
    pass


def enum_type(cls):
    # SQLite has no native enum; CHECK also protects writes outside Pydantic.
    return Enum(cls, native_enum=False, create_constraint=True, validate_strings=True)


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("id", "user_id"),
        CheckConstraint("currency = 'CNY'"),
        CheckConstraint("original_amount >= 0 AND discount_amount >= 0 AND paid_amount >= 0"),
        CheckConstraint("discount_amount <= original_amount"),
        CheckConstraint("paid_amount = 0 OR paid_amount = original_amount - discount_amount"),
        CheckConstraint("status != 'PENDING_PAYMENT' OR (paid_amount = 0 AND paid_at IS NULL)"),
        CheckConstraint("status NOT IN ('PAID','SHIPPED','DELIVERED','COMPLETED') OR paid_at IS NOT NULL"),
        CheckConstraint(
            "status NOT IN ('PENDING_PAYMENT','PAID') OR (shipped_at IS NULL AND delivered_at IS NULL)"
        ),
        CheckConstraint("status NOT IN ('SHIPPED','DELIVERED','COMPLETED') OR shipped_at IS NOT NULL"),
        CheckConstraint("status NOT IN ('DELIVERED','COMPLETED') OR delivered_at IS NOT NULL"),
        CheckConstraint("status != 'SHIPPED' OR delivered_at IS NULL"),
        CheckConstraint("paid_at IS NULL OR paid_at >= created_at"),
        CheckConstraint("shipped_at IS NULL OR (paid_at IS NOT NULL AND shipped_at >= paid_at)"),
        CheckConstraint("delivered_at IS NULL OR (shipped_at IS NOT NULL AND delivered_at >= shipped_at)"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[OrderStatus] = mapped_column(enum_type(OrderStatus))
    currency: Mapped[str] = mapped_column(String(3), default="CNY")
    original_amount: Mapped[Decimal] = mapped_column(Money())
    discount_amount: Mapped[Decimal] = mapped_column(Money(), default=ZERO)
    paid_amount: Mapped[Decimal] = mapped_column(Money())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    paid_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    shipped_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    @property
    def payable_amount(self) -> Decimal:
        return self.original_amount - self.discount_amount


class OrderItem(Base):
    __tablename__ = "order_items"
    __table_args__ = (
        UniqueConstraint("id", "order_id"),
        CheckConstraint("quantity > 0 AND returned_quantity >= 0 AND returned_quantity <= quantity"),
        CheckConstraint("unit_price >= 0 AND discount_amount >= 0 AND paid_amount >= 0"),
        CheckConstraint("discount_amount <= unit_price * quantity"),
        CheckConstraint("paid_amount = 0 OR paid_amount = unit_price * quantity - discount_amount"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), index=True)
    product_name: Mapped[str] = mapped_column(String(200))
    sku: Mapped[str] = mapped_column(String(80))
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price: Mapped[Decimal] = mapped_column(Money())
    discount_amount: Mapped[Decimal] = mapped_column(Money(), default=ZERO)
    paid_amount: Mapped[Decimal] = mapped_column(Money())
    category: Mapped[str] = mapped_column(String(80))
    refundable: Mapped[bool] = mapped_column(Boolean(create_constraint=True), default=True)
    final_sale: Mapped[bool] = mapped_column(Boolean(create_constraint=True), default=False)
    returned_quantity: Mapped[int] = mapped_column(default=0)


class Shipment(Base):
    __tablename__ = "shipments"
    __table_args__ = (
        CheckConstraint("status != 'DELIVERED' OR delivered_at IS NOT NULL"),
        CheckConstraint("delivered_at IS NULL OR delivered_at >= shipped_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), unique=True)
    carrier: Mapped[str] = mapped_column(String(80))
    tracking_number: Mapped[str] = mapped_column(String(100), unique=True)
    status: Mapped[ShipmentStatus] = mapped_column(enum_type(ShipmentStatus))
    shipped_at: Mapped[datetime] = mapped_column(UTCDateTime())
    delivered_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    latest_event: Mapped[str] = mapped_column(String(500))
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Ticket(Timestamps, Base):
    __tablename__ = "tickets"
    __table_args__ = (
        UniqueConstraint("id", "user_id"),
        ForeignKeyConstraint(["order_id", "user_id"], ["orders.id", "orders.user_id"]),
        Index("ix_tickets_status_created", "status", "created_at"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(Integer, index=True)
    issue_type: Mapped[IssueType] = mapped_column(enum_type(IssueType))
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[TicketStatus] = mapped_column(enum_type(TicketStatus), default=TicketStatus.OPEN)
    priority: Mapped[Priority] = mapped_column(enum_type(Priority), default=Priority.NORMAL)


class ActionRequest(Timestamps, Base):
    __tablename__ = "action_requests"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key"),
        UniqueConstraint("id", "order_id"),
        UniqueConstraint("id", "ticket_id"),
        ForeignKeyConstraint(["order_id", "user_id"], ["orders.id", "orders.user_id"]),
        ForeignKeyConstraint(["order_item_id", "order_id"], ["order_items.id", "order_items.order_id"]),
        ForeignKeyConstraint(["ticket_id", "user_id"], ["tickets.id", "tickets.user_id"]),
        CheckConstraint("amount >= 0"),
        CheckConstraint("quantity IS NULL OR quantity > 0"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), index=True)
    order_item_id: Mapped[int | None] = mapped_column(ForeignKey("order_items.id"))
    quantity: Mapped[int | None]
    idempotency_key: Mapped[str] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64))
    proposed_action: Mapped[ActionType] = mapped_column(enum_type(ActionType))
    # final_action is populated only after a successful simulated execution.
    final_action: Mapped[ActionType | None] = mapped_column(enum_type(ActionType))
    authorized_action: Mapped[ActionType | None] = mapped_column(enum_type(ActionType))
    decision: Mapped[PolicyDecision] = mapped_column(enum_type(PolicyDecision))
    execution_status: Mapped[ExecutionStatus] = mapped_column(enum_type(ExecutionStatus))
    risk_level: Mapped[RiskLevel] = mapped_column(enum_type(RiskLevel))
    amount: Mapped[Decimal] = mapped_column(Money(), default=ZERO)
    policy_version: Mapped[str] = mapped_column(String(80))
    rule_codes: Mapped[list[str]] = mapped_column(JSON)
    explanation: Mapped[str] = mapped_column(Text)
    evidence_provided: Mapped[bool] = mapped_column(Boolean(create_constraint=True), default=False)
    return_received_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSON)


class Refund(Timestamps, Base):
    __tablename__ = "refunds"
    __table_args__ = (
        ForeignKeyConstraint(["order_item_id", "order_id"], ["order_items.id", "order_items.order_id"]),
        ForeignKeyConstraint(
            ["action_request_id", "order_id"], ["action_requests.id", "action_requests.order_id"]
        ),
        CheckConstraint("amount > 0"),
        CheckConstraint(
            "(order_item_id IS NULL AND quantity IS NULL) OR "
            "(order_item_id IS NOT NULL AND quantity IS NOT NULL AND quantity > 0)"
        ),
        Index("ix_refunds_order_status", "order_id", "status"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"))
    order_item_id: Mapped[int | None] = mapped_column(Integer)
    quantity: Mapped[int | None]
    action_request_id: Mapped[int | None] = mapped_column(ForeignKey("action_requests.id"), unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(180), unique=True)
    amount: Mapped[Decimal] = mapped_column(Money())
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[RefundStatus] = mapped_column(enum_type(RefundStatus), default=RefundStatus.PENDING)


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (
        ForeignKeyConstraint(
            ["action_request_id", "ticket_id"], ["action_requests.id", "action_requests.ticket_id"]
        ),
        CheckConstraint("requested_amount >= 0"),
        CheckConstraint(
            "status = 'PENDING' OR (reviewer IS NOT NULL AND reason IS NOT NULL AND reviewed_at IS NOT NULL)"
        ),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), index=True)
    action_request_id: Mapped[int] = mapped_column(ForeignKey("action_requests.id"), unique=True)
    action_type: Mapped[ActionType] = mapped_column(enum_type(ActionType))
    requested_amount: Mapped[Decimal] = mapped_column(Money())
    status: Mapped[ApprovalStatus] = mapped_column(enum_type(ApprovalStatus), default=ApprovalStatus.PENDING)
    reviewer: Mapped[str | None] = mapped_column(String(100))
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    reviewed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    action_request_id: Mapped[int] = mapped_column(ForeignKey("action_requests.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(80))
    actor: Mapped[str] = mapped_column(String(100))
    data_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class AgentRun(Base):
    """Schema reservation only. Stage 2 audits do not pretend to be LLM traces."""

    __tablename__ = "agent_runs"
    __table_args__ = (
        CheckConstraint("llm_calls >= 0 AND input_tokens >= 0 AND output_tokens >= 0 AND latency_ms >= 0"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    ticket_id: Mapped[int | None] = mapped_column(ForeignKey("tickets.id"))
    user_query: Mapped[str] = mapped_column(Text)
    proposed_action: Mapped[ActionType | None] = mapped_column(enum_type(ActionType))
    final_action: Mapped[ActionType | None] = mapped_column(enum_type(ActionType))
    risk_level: Mapped[RiskLevel | None] = mapped_column(enum_type(RiskLevel))
    status: Mapped[RunStatus] = mapped_column(enum_type(RunStatus), default=RunStatus.RUNNING)
    llm_calls: Mapped[int] = mapped_column(default=0)
    input_tokens: Mapped[int] = mapped_column(default=0)
    output_tokens: Mapped[int] = mapped_column(default=0)
    latency_ms: Mapped[int] = mapped_column(default=0)
    error_type: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class ToolCall(Base):
    __tablename__ = "tool_calls"
    __table_args__ = (CheckConstraint("latency_ms >= 0"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    tool_name: Mapped[str] = mapped_column(String(100))
    arguments_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    result_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    status: Mapped[RunStatus] = mapped_column(enum_type(RunStatus))
    latency_ms: Mapped[int] = mapped_column(default=0)
    error_type: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class TicketSubmission(Base):
    """Additive idempotency mapping: preserve the Stage 2 tickets schema/data."""

    __tablename__ = "ticket_submissions"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    idempotency_key: Mapped[str] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64))
    ticket_id: Mapped[int] = mapped_column(ForeignKey("tickets.id"), unique=True)


class AgentRunDetail(Base):
    """Additive Stage 3 metadata; old AgentRun/ToolCall rows need no destructive migration."""

    __tablename__ = "agent_run_details"
    __table_args__ = (UniqueConstraint("user_id", "idempotency_key"),)
    run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    payload_hash: Mapped[str] = mapped_column(String(64))
    parent_run_id: Mapped[int | None] = mapped_column(ForeignKey("agent_runs.id"))
    action_request_id: Mapped[int | None] = mapped_column(ForeignKey("action_requests.id"))
    provider: Mapped[str] = mapped_column(String(80))
    model: Mapped[str] = mapped_column(String(120))
    outcome: Mapped[str] = mapped_column(String(80), default="RUNNING")
    reply: Mapped[str | None] = mapped_column(Text)
    sources_json: Mapped[list[dict]] = mapped_column(JSON, default=list)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime())


class ModelCall(Base):
    __tablename__ = "model_calls"
    __table_args__ = (
        UniqueConstraint("agent_run_id", "sequence"),
        CheckConstraint("input_tokens IS NULL OR input_tokens >= 0"),
        CheckConstraint("output_tokens IS NULL OR output_tokens >= 0"),
        CheckConstraint("latency_ms >= 0"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    agent_run_id: Mapped[int] = mapped_column(ForeignKey("agent_runs.id"), index=True)
    sequence: Mapped[int]
    is_live: Mapped[bool] = mapped_column(Boolean(create_constraint=True))
    model: Mapped[str] = mapped_column(String(120))
    request_json: Mapped[dict] = mapped_column(JSON)
    response_json: Mapped[dict | None] = mapped_column(JSON)
    input_tokens: Mapped[int | None]
    output_tokens: Mapped[int | None]
    latency_ms: Mapped[int] = mapped_column(default=0)
    status: Mapped[RunStatus] = mapped_column(enum_type(RunStatus), default=RunStatus.RUNNING)
    error_type: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
