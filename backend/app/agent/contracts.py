from datetime import datetime
from typing import Annotated, Literal

from pydantic import Field

from app.core.enums import ActionType, IssueType, RunStatus
from app.schemas.api import ActionRead, PositiveId, Schema

Key = Annotated[str, Field(min_length=8, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")]


class ChatRequest(Schema):
    message: str = Field(min_length=1, max_length=4000)
    idempotency_key: Key
    parent_run_id: PositiveId | None = None
    order_id: PositiveId | None = None
    evidence_provided: bool = Field(default=False, strict=True)


class EmptyArgs(Schema):
    pass


class OrderArgs(Schema):
    order_id: PositiveId


class SearchArgs(Schema):
    query: str = Field(min_length=1, max_length=300)


class TicketArgs(Schema):
    order_id: PositiveId
    issue_type: IssueType


class SubmitArgs(Schema):
    ticket_id: PositiveId
    proposed_action: ActionType
    order_item_id: PositiveId | None = None
    quantity: Annotated[int, Field(strict=True, ge=1, le=10000)] | None = None


class FinishArgs(Schema):
    kind: Literal[
        "ASK_ORDER",
        "ASK_ITEM",
        "ASK_QUANTITY",
        "ASK_EVIDENCE",
        "POLICY",
        "ORDER",
        "UNSUPPORTED",
        "REFUSE_UNAUTHORIZED",
    ]
    citation_ids: list[str] = Field(default_factory=list, max_length=5)
    # Untrusted prose is available to reviewers but never overrides a business result.
    draft_reply: str = Field(default="", max_length=1500)


class ToolInvocation(Schema):
    id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=100)
    arguments: str = Field(max_length=8000)


class ModelReply(Schema):
    content: str = Field(default="", max_length=8000)
    tool_calls: list[ToolInvocation] = Field(default_factory=list, max_length=8)
    input_tokens: Annotated[int, Field(strict=True, ge=0)] | None = None
    output_tokens: Annotated[int, Field(strict=True, ge=0)] | None = None

    def message(self) -> dict:
        result = {"role": "assistant", "content": self.content or None}
        if self.tool_calls:
            result["tool_calls"] = [
                {"id": t.id, "type": "function", "function": {"name": t.name, "arguments": t.arguments}}
                for t in self.tool_calls
            ]
        return result


class Citation(Schema):
    id: str
    title: str
    version: str
    content: str
    content_hash: str
    source: str


class ChatResult(Schema):
    run_id: int
    status: RunStatus
    outcome: str
    provider: str
    model: str
    reply: str | None
    action: ActionRead | None
    citations: list[Citation]
    llm_calls: int
    input_tokens: int | None
    output_tokens: int | None
    usage_complete: bool
    tool_calls: int
    latency_ms: int
    error_type: str | None
    parent_run_id: int | None
    created_at: datetime
    finished_at: datetime | None


class AgentTrace(Schema):
    run: ChatResult
    model_calls: list[dict]
    tool_calls: list[dict]


class AgentStatus(Schema):
    provider: str = "deepseek"
    configured: bool
    model: str
    max_steps: int
    max_tools: int
    timeout_seconds: float
