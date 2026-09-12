from datetime import timedelta
from decimal import Decimal

import pytest
from app.core.enums import RefundStatus, TicketStatus
from app.core.errors import DomainError
from app.core.types import Money, UTCDateTime
from app.db.seed import seed, validate_seed
from app.db.session import initialize, write_transaction
from app.models.entities import Base, Order, OrderItem, Refund, Ticket, User
from app.repositories.store import Store
from app.schemas.api import TicketCreate
from app.services.business import create_refund_record, update_refund_status
from pydantic import ValidationError
from sqlalchemy import func, inspect, select, text
from sqlalchemy.exc import IntegrityError, StatementError

from backend.tests.conftest import NOW


def test_initialization_is_repeatable_with_all_tables(application, sessions):
    initialize(application.state.engine)
    assert set(inspect(application.state.engine).get_table_names()) == set(Base.metadata.tables)
    with sessions() as session:
        assert session.scalar(text("PRAGMA foreign_keys")) == 1
        assert session.scalar(select(func.count()).select_from(User)) == 10


def test_seed_counts_consistency_and_non_destructive_repeat(sessions):
    assert seed(sessions, now=NOW + timedelta(days=1))["status"] == "skipped"
    with sessions() as session:
        assert validate_seed(session) == []
        assert session.scalar(select(func.count()).select_from(Order)) == 24
        assert session.scalar(select(func.count()).select_from(OrderItem)) == 48
        assert session.scalar(select(func.count()).select_from(Refund)) == 3
        unpaid = session.get(Order, 1014)
        assert unpaid.paid_amount == Decimal("0.00")
        assert unpaid.payable_amount == Decimal("112.97")


def test_read_services_and_null_shipment(business):
    assert business.get_user(1).email.endswith("example.invalid")
    assert len(business.list_user_orders(1)) == 3
    assert len(business.get_order_items(1001)) == 2
    assert business.get_shipment(1001) is None
    assert business.get_shipment(1010).delivered_at is not None
    assert business.get_refunds(1007)[0].status == RefundStatus.SUCCESS
    assert business.get_ticket(3).order_id is None


@pytest.mark.parametrize(
    "method",
    [
        "get_user",
        "get_order",
        "get_order_items",
        "get_shipment",
        "get_refunds",
        "get_ticket",
        "list_user_orders",
    ],
)
def test_missing_entities_are_consistent(business, method):
    with pytest.raises(DomainError) as error:
        getattr(business, method)(999999)
    assert error.value.code == "NOT_FOUND"
    assert error.value.status_code == 404


def test_ticket_ownership_and_orderless_link(business):
    with pytest.raises(DomainError, match="不属于"):
        business.create_ticket(
            TicketCreate(user_id=2, order_id=1001, issue_type="CANCEL", description="取消")
        )
    ticket = business.create_ticket(TicketCreate(user_id=1, issue_type="CANCEL", description="取消"))
    assert ticket.order_id is None
    assert business.link_ticket_order(ticket.id, 1001).order_id == 1001
    with pytest.raises(DomainError):
        business.link_ticket_order(ticket.id, 1011)


def test_database_money_is_integer_and_utc_roundtrip(sessions):
    with sessions() as session:
        raw, storage_type = session.execute(
            text("SELECT paid_amount, typeof(paid_amount) FROM orders WHERE id=1001")
        ).one()
        assert (raw, storage_type) == (11297, "integer")
        order = session.get(Order, 1001)
        assert order.paid_amount == Decimal("112.97")
        assert order.created_at.utcoffset() == timedelta(0)
    assert UTCDateTime().process_bind_param(NOW.astimezone(), None) == NOW.replace(tzinfo=None)
    with pytest.raises(ValueError):
        UTCDateTime().process_bind_param(NOW.replace(tzinfo=None), None)


@pytest.mark.parametrize("amount", [1.1, Decimal("0.001"), Decimal("NaN"), Decimal("Infinity")])
def test_money_rejects_unsafe_values(amount):
    with pytest.raises(ValueError):
        Money().process_bind_param(amount, None)


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE order_items SET quantity=0 WHERE id=10011",
        "UPDATE order_items SET returned_quantity=99 WHERE id=10011",
        "UPDATE orders SET user_id=999 WHERE id=1001",
        "UPDATE orders SET status='FAKE' WHERE id=1001",
        "UPDATE orders SET paid_amount=-1 WHERE id=1001",
        "UPDATE orders SET discount_amount=999999 WHERE id=1001",
        "UPDATE orders SET delivered_at='2026-01-01' WHERE id=1001",
        "UPDATE tickets SET user_id=2 WHERE id=1",
        "UPDATE refunds SET order_id=1001 WHERE order_id=1007",
        "UPDATE refunds SET quantity=NULL WHERE order_id=1007",
        "UPDATE orders SET currency='USD' WHERE id=1001",
    ],
)
def test_database_rejects_invalid_rows(sessions, sql):
    with pytest.raises(IntegrityError), write_transaction(sessions) as session:
        session.execute(text(sql))


def test_orm_rejects_invalid_enum(sessions):
    with pytest.raises(StatementError), write_transaction(sessions) as session:
        session.get(Order, 1001).status = "FAKE"


@pytest.mark.parametrize(
    "changes",
    [{"description": " "}, {"issue_type": "FAKE"}, {"status": "CLOSED"}, {"user_id": True}, {"user_id": 0}],
)
def test_ticket_schema_rejects_illegal_fields(changes):
    with pytest.raises(ValidationError):
        TicketCreate.model_validate({"user_id": 1, "issue_type": "CANCEL", "description": "取消", **changes})


def test_ticket_status_machine(business):
    ticket = business.create_ticket(TicketCreate(user_id=1, issue_type="CANCEL", description="取消"))
    business.update_ticket_status(ticket.id, TicketStatus.RESOLVED)
    business.update_ticket_status(ticket.id, TicketStatus.CLOSED)
    with pytest.raises(DomainError):
        business.update_ticket_status(ticket.id, TicketStatus.OPEN)


def test_refund_status_machine_and_direct_overrefund_guard(sessions):
    with write_transaction(sessions) as session:
        store = Store(session)
        refund = create_refund_record(
            store, order_id=1001, amount=Decimal("112.97"), reason="取消", idempotency_key="direct-test"
        )
        with pytest.raises(DomainError):
            update_refund_status(refund, RefundStatus.SUCCESS)
        update_refund_status(refund, RefundStatus.APPROVED)
        update_refund_status(refund, RefundStatus.PROCESSING)
        update_refund_status(refund, RefundStatus.SUCCESS)
        with pytest.raises(DomainError):
            update_refund_status(refund, RefundStatus.PENDING)
        with pytest.raises(DomainError):
            create_refund_record(
                store, order_id=1001, amount=Decimal("0.01"), reason="重复", idempotency_key="direct-test-2"
            )


def test_cross_table_validator_detects_total_corruption(sessions):
    with write_transaction(sessions) as session:
        session.execute(text("UPDATE order_items SET paid_amount=0 WHERE id=10011"))
        assert any("paid amount mismatch" in issue for issue in validate_seed(session))


def test_transaction_rolls_back_all_writes(sessions):
    with pytest.raises(RuntimeError), write_transaction(sessions) as session:
        session.add(Ticket(user_id=1, order_id=1001, issue_type="CANCEL", description="rollback"))
        session.flush()
        raise RuntimeError("fail after first write")
    with sessions() as session:
        assert session.scalar(select(func.count()).select_from(Ticket)) == 3
