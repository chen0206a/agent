from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.core.config import Settings
from app.core.enums import ActionType as A
from app.core.enums import IssueType as I
from app.core.enums import OrderStatus as O
from app.core.enums import PolicyDecision as D
from app.core.enums import RiskLevel
from app.core.errors import DomainError
from app.core.types import ZERO
from app.schemas.api import ActionCreate, ItemRead, OrderRead, PolicyResult, ShipmentRead
from app.services.calculator import LineBalance, RefundCalculator


@dataclass(frozen=True)
class PolicyContext:
    issue_type: I
    order: OrderRead | None
    item: ItemRead | None
    shipment: ShipmentRead | None
    line_balance: LineBalance | None
    reserved_amount: Decimal = ZERO
    whole_refund_exists: bool = False
    replacement_exists: bool = False


class RiskEngine:
    def __init__(self, settings: Settings):
        self.threshold = settings.high_amount_threshold

    def assess(self, amount: Decimal, issue_type: I) -> tuple[RiskLevel, list[str]]:
        codes = []
        if amount >= self.threshold:
            codes.append("HIGH_AMOUNT")
        if issue_type in (I.DAMAGED, I.WRONG_ITEM, I.MISSING_ITEM):
            codes.append("EVIDENCE_REQUIRES_REVIEW")
        if "HIGH_AMOUNT" in codes:
            return RiskLevel.HIGH, codes
        return (RiskLevel.MEDIUM if codes else RiskLevel.LOW), codes


class PolicyEngine:
    """Pure decision function: no SQL, mutations, external calls, or user-supplied money.

    These are versioned DEMO merchant policies, not claims about statutory rights.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.risk = RiskEngine(settings)
        self.version = (
            f"demo-v1:r{settings.return_window_days}:q{settings.quality_window_days}"
            f":h{settings.high_amount_threshold:.2f}"
        )

    def evaluate(self, request: ActionCreate, context: PolicyContext, *, now: datetime) -> PolicyResult:
        def result(decision, code, message, action=None, amount=ZERO, risk=RiskLevel.LOW):
            return PolicyResult(
                decision=decision,
                rule_codes=[code],
                explanation=message,
                authorized_action=action,
                amount=amount,
                risk_level=risk,
                policy_version=self.version,
            )

        order, item, issue = context.order, context.item, context.issue_type
        action = request.proposed_action
        if order is None:
            return result(D.NEED_MORE_INFO, "ORDER_REQUIRED", "请补充订单信息")
        if order.currency != "CNY":
            return result(D.DENY, "UNSUPPORTED_CURRENCY", "当前模拟政策仅支持人民币")
        if order.status in (O.PENDING_PAYMENT, O.CANCELLED) or order.paid_amount <= ZERO:
            return result(D.DENY, "ORDER_NOT_REFUNDABLE", "订单未支付、已取消或没有实付金额")

        if issue == I.NOT_RECEIVED or (issue == I.CANCEL and order.status == O.SHIPPED):
            if order.status not in (O.SHIPPED, O.DELIVERED, O.COMPLETED) or context.shipment is None:
                return result(D.NEED_MORE_INFO, "SHIPMENT_REQUIRED", "需要有效的发货及物流信息")
            # Policy may replace an unsafe refund proposal with a logistics investigation.
            return result(
                D.ALLOW, "LOGISTICS_FIRST", "先建立物流调查或拦截工单，不直接退款", A.CREATE_LOGISTICS_TICKET
            )

        if action == A.CREATE_LOGISTICS_TICKET:
            return result(D.DENY, "ACTION_ISSUE_MISMATCH", "当前问题不适用物流调查动作")
        if action == A.CANCEL_AND_REFUND:
            if issue != I.CANCEL or order.status != O.PAID:
                return result(D.DENY, "CANCEL_REQUIRES_UNSHIPPED", "仅已支付且未发货订单支持取消退款")
            if context.reserved_amount > ZERO or context.replacement_exists:
                return result(D.DENY, "EXISTING_AFTERSALE", "已有退款或换货占用，不能再做整单取消")
            amount = order.paid_amount
            pass_code = "UNSHIPPED_CANCELLATION"
        else:
            if order.status not in (O.DELIVERED, O.COMPLETED):
                return result(D.DENY, "DELIVERY_REQUIRED", "该售后动作需要订单已签收")
            if item is None or request.quantity is None:
                return result(D.NEED_MORE_INFO, "ITEM_REQUIRED", "请补充具体商品和数量")
            if item.order_id != order.id:
                return result(D.DENY, "ITEM_ORDER_MISMATCH", "商品不属于该订单")
            if order.delivered_at is None or order.delivered_at > now:
                return result(D.DENY, "INVALID_DELIVERY_TIME", "签收时间无效")
            if context.whole_refund_exists:
                return result(D.DENY, "WHOLE_ORDER_REFUND_EXISTS", "已有整单退款，不能再申请商品售后")
            if issue == I.NO_REASON_RETURN:
                if action != A.RETURN_AND_REFUND:
                    return result(D.DENY, "ACTION_ISSUE_MISMATCH", "无理由退货只支持退货退款")
                if not item.refundable or item.final_sale:
                    return result(D.DENY, "ITEM_NOT_RETURNABLE", "该商品不支持模拟政策中的无理由退货")
                if now - order.delivered_at > timedelta(days=self.settings.return_window_days):
                    return result(D.DENY, "RETURN_WINDOW_EXPIRED", "已超过模拟无理由退货申请期限")
                pass_code = "WITHIN_RETURN_WINDOW"
            elif issue in (I.DAMAGED, I.WRONG_ITEM, I.MISSING_ITEM):
                supported = (
                    (A.REFUND_MISSING_ITEM, A.REPLACE_ITEM)
                    if issue == I.MISSING_ITEM
                    else (
                        A.RETURN_AND_REFUND,
                        A.REPLACE_ITEM,
                    )
                )
                if action not in supported:
                    return result(D.DENY, "ACTION_ISSUE_MISMATCH", "申请动作与质量或少件问题不匹配")
                if now - order.delivered_at > timedelta(days=self.settings.quality_window_days):
                    return result(D.DENY, "QUALITY_WINDOW_EXPIRED", "已超过模拟质量售后申请期限")
                if not request.evidence_provided:
                    return result(D.NEED_MORE_INFO, "EVIDENCE_REQUIRED", "请提供破损、错发或少件证据")
                pass_code = "QUALITY_CLAIM"
            else:
                return result(D.NEED_MORE_INFO, "ISSUE_UNSUPPORTED", "请补充或明确售后问题类型")
            if context.line_balance is None:
                return result(D.NEED_MORE_INFO, "BALANCE_REQUIRED", "缺少商品结算数据")
            try:
                amount = RefundCalculator.item_amount(context.line_balance, request.quantity)
                if amount > order.paid_amount - context.reserved_amount:
                    raise DomainError("NO_REFUNDABLE_BALANCE", "订单剩余额度不足")
            except DomainError as error:
                return result(D.DENY, error.code, error.message)

        risk, risk_codes = self.risk.assess(amount, issue)
        return PolicyResult(
            decision=D.REQUIRE_APPROVAL if risk_codes else D.ALLOW,
            authorized_action=action,
            amount=amount,
            risk_level=risk,
            rule_codes=[pass_code, *risk_codes],
            explanation="需人工核验证据或高金额申请" if risk_codes else "符合模拟售后政策",
            policy_version=self.version,
        )
