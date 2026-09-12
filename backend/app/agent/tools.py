import json
from dataclasses import dataclass, field

from pydantic import ValidationError

from app.agent.contracts import (
    ChatRequest,
    Citation,
    EmptyArgs,
    FinishArgs,
    OrderArgs,
    SearchArgs,
    SubmitArgs,
    TicketArgs,
)
from app.agent.knowledge import PolicyKnowledge
from app.core.errors import DomainError
from app.schemas.api import (
    ActionCreate,
    ActionRead,
    ItemRead,
    OrderRead,
    RefundRead,
    ShipmentRead,
    TicketCreate,
)
from app.services.business import BusinessService
from app.services.workflow import WorkflowService

TOOL_MODELS = {
    "list_my_orders": (EmptyArgs, "列出当前会话用户的订单，不能选择其他用户。"),
    "get_order": (OrderArgs, "查询当前用户的一张订单，金额为实付人民币字符串。"),
    "get_order_items": (OrderArgs, "商品退换/少件时查明细；整单取消不需要。不得猜商品或数量。"),
    "get_shipment": (OrderArgs, "已发货取消、物流异常或未收到时查物流；未发货不需要。签收不证明收到。"),
    "get_refunds": (OrderArgs, "查退款进度或重复申请疑问；提交时业务层始终重新计算额度，无须例行查询。"),
    "search_policies": (SearchArgs, "按本次实际诉求关键词检索版本化政策，不要混入无关场景。"),
    "create_ticket": (TicketArgs, "按用户诉求建立幂等工单，用户身份和描述由服务器注入。"),
    "submit_action": (SubmitArgs, "提交建议给确定性政策校验，不执行退款；必须先查订单及政策。"),
    "finish_response": (
        FinishArgs,
        "结束补问、查询、拒绝或非售后请求时必须实际调用本函数，不能只输出文字。"
        "越权或伪造金额用 REFUSE_UNAUTHORIZED；意图未明或不支持用 UNSUPPORTED；"
        "意图明确后才按缺失信息选择 ASK_ORDER/ASK_ITEM/ASK_QUANTITY。draft_reply 不展示给客户。",
    ),
}


def compact_schema(value):
    """Remove generated display titles only; preserve every validation constraint."""
    if isinstance(value, dict):
        return {key: compact_schema(item) for key, item in value.items() if key != "title"}
    if isinstance(value, list):
        return [compact_schema(item) for item in value]
    return value


def tool_definitions() -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": compact_schema(model.model_json_schema()),
            },
        }
        for name, (model, description) in TOOL_MODELS.items()
    ]


@dataclass
class ToolContext:
    user_id: int
    run_id: int
    request: ChatRequest
    observed_orders: dict[int, dict] = field(default_factory=dict)
    observed_items: dict[int, list[dict]] = field(default_factory=dict)
    citations: dict[str, Citation] = field(default_factory=dict)
    ticket_id: int | None = None
    action: ActionRead | None = None
    finish: FinishArgs | None = None


class AgentTools:
    def __init__(
        self,
        context: ToolContext,
        business: BusinessService,
        workflow: WorkflowService,
        knowledge: PolicyKnowledge,
    ):
        self.context, self.business, self.workflow, self.knowledge = context, business, workflow, knowledge

    def _owned_order(self, order_id: int):
        if self.context.request.order_id is not None and self.context.request.order_id != order_id:
            raise DomainError("ORDER_SCOPE_MISMATCH", "只能处理本轮用户明确选择的订单", 403)
        order = self.business.get_order(order_id)
        if order.user_id != self.context.user_id:
            raise DomainError("FORBIDDEN", "不能查询或处理其他用户的订单", 403)
        return order

    def invoke(self, name: str, raw_arguments: str) -> dict:
        if name not in TOOL_MODELS:
            raise DomainError("TOOL_NOT_ALLOWED", "该工具不在允许名单，Agent 不能审批或执行业务", 403)
        try:
            args = TOOL_MODELS[name][0].model_validate_json(raw_arguments)
        except (ValidationError, ValueError) as error:
            raise DomainError(
                "INVALID_TOOL_ARGUMENTS", "工具参数不符合 schema；不能添加身份、金额或状态", 422
            ) from error
        ctx = self.context
        if name == "list_my_orders":
            orders = self.business.list_user_orders(ctx.user_id)
            return {
                "orders": [
                    {"id": o.id, "status": o.status.value, "paid_amount": f"{o.paid_amount:.2f}"}
                    for o in orders
                    if ctx.request.order_id is None or o.id == ctx.request.order_id
                ]
            }
        if name in {"get_order", "get_order_items", "get_shipment", "get_refunds"}:
            order = self._owned_order(args.order_id)
            if name == "get_order":
                data = OrderRead.model_validate(order).model_dump(mode="json", exclude={"user_id"})
                ctx.observed_orders[order.id] = data
                return data
            if name == "get_order_items":
                items = [
                    ItemRead.model_validate(i).model_dump(mode="json")
                    for i in self.business.get_order_items(order.id)
                ]
                ctx.observed_items[order.id] = items
                return {"items": items}
            if name == "get_shipment":
                shipment = self.business.get_shipment(order.id)
                return {
                    "shipment": ShipmentRead.model_validate(shipment).model_dump(mode="json")
                    if shipment
                    else None
                }
            return {
                "refunds": [
                    RefundRead.model_validate(r).model_dump(mode="json")
                    for r in self.business.get_refunds(order.id)
                ]
            }
        if name == "search_policies":
            docs = self.knowledge.search(args.query)
            ctx.citations.update({doc.id: doc for doc in docs})
            return {"documents": [doc.model_dump() for doc in docs]}
        if name == "create_ticket":
            self._owned_order(args.order_id)
            if args.order_id not in ctx.observed_orders:
                raise DomainError("ORDER_LOOKUP_REQUIRED", "创建申请前必须查询订单")
            ticket = self.business.create_ticket(
                TicketCreate(
                    user_id=ctx.user_id,
                    order_id=args.order_id,
                    issue_type=args.issue_type,
                    description=ctx.request.message,
                ),
                idempotency_key=f"agent:{ctx.run_id}:ticket",
            )
            ctx.ticket_id = ticket.id
            return {
                "ticket_id": ticket.id,
                "order_id": ticket.order_id,
                "issue_type": ticket.issue_type.value,
            }
        if name == "submit_action":
            if args.ticket_id != ctx.ticket_id:
                raise DomainError("TICKET_SCOPE_MISMATCH", "只能向本轮创建的工单提交动作", 403)
            ticket = self.business.get_ticket(args.ticket_id)
            self._owned_order(ticket.order_id)
            if not ctx.citations:
                raise DomainError("POLICY_LOOKUP_REQUIRED", "提交前必须检索相关政策")
            if args.order_item_id is not None and args.order_item_id not in {
                item["id"] for item in ctx.observed_items.get(ticket.order_id, [])
            }:
                raise DomainError("ITEM_LOOKUP_REQUIRED", "商品售后前必须查询对应商品项")
            action = self.workflow.submit(
                ActionCreate(
                    **args.model_dump(),
                    evidence_provided=ctx.request.evidence_provided,
                    idempotency_key=f"agent:{ctx.run_id}:action",
                )
            )
            ctx.action = ActionRead.model_validate(action)
            return ctx.action.model_dump(mode="json")
        if any(citation_id not in ctx.citations for citation_id in args.citation_ids):
            raise DomainError("UNVERIFIED_CITATION", "不能引用未检索到的政策")
        if args.kind == "POLICY" and not args.citation_ids:
            raise DomainError("POLICY_LOOKUP_REQUIRED", "政策回答需要有效来源")
        if args.kind == "ORDER" and not ctx.observed_orders:
            raise DomainError("ORDER_LOOKUP_REQUIRED", "订单回答需要实际查询")
        ctx.finish = args
        return {"finished": True, "kind": args.kind}


def safe_arguments(raw: str) -> dict:
    try:
        value = json.loads(raw)
        return value if isinstance(value, dict) else {"invalid_type": type(value).__name__}
    except ValueError:
        return {"invalid_json": raw[:2000]}
