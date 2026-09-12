from datetime import datetime
from typing import Literal

from pydantic import Field, SecretStr

from app.schemas.api import Schema


class LoginInput(Schema):
    username: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.@-]+$")
    password: SecretStr = Field(min_length=1, max_length=128)


class AccountRead(Schema):
    username: str
    role: Literal["customer", "admin"]
    user_id: int | None
    csrf_token: str


class RunRead(Schema):
    id: int
    user_id: int
    order_id: int | None
    ticket_id: int | None
    user_query: str
    reply: str | None
    outcome: str
    status: str
    llm_calls: int
    latency_ms: int
    created_at: datetime
    parent_run_id: int | None


class DashboardRead(Schema):
    total_runs: int
    successful_runs: int
    completed_runs: int
    human_review_count: int
    rejected_or_clarified_count: int
    automation_rate: float
    human_review_rate: float
    avg_llm_calls: float
    avg_tool_calls: float
    input_tokens: int
    output_tokens: int
    unknown_usage_calls: int
    avg_latency_ms: float
    agent_error_count: int
    pending_approvals: int
