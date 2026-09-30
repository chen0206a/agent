from app.agent.tools import ToolContext

ASK = {
    "ASK_INTENT": "请说明遇到的具体问题，以及您想先咨询政策、查询进度，还是提交售后申请。",
    "ASK_ORDER": "请提供需要处理的订单号，或先选择您自己的订单。",
    "ASK_ITEM": "请提供需要售后的具体商品或商品编号。",
    "ASK_QUANTITY": "请说明需要售后的商品数量。",
    "ASK_EVIDENCE": "请补充破损、错发或少件的相关证据，并联系人工客服核验；当前尚未执行退款。",
    "UNSUPPORTED": "请说明订单号、遇到的问题和希望的处理方式，我可以协助查询并提交售后申请。",
}


REFUND_STATUS = {
    "PENDING": "待处理，尚未退款，请等待审核或联系人工客服。",
    "APPROVED": "已批准，尚未退款，请关注退货要求及后续处理进度。",
    "PROCESSING": "退款处理中，尚未确认成功，请稍后查询。",
    "SUCCESS": "退款成功（模拟），不代表真实资金到账。",
    "REJECTED": "退款已拒绝，未执行退款；如有疑问请联系人工客服。",
    "FAILED": "退款处理失败，尚未确认成功，请联系管理员核查后重试。",
}


def refund_reply(context: ToolContext) -> str:
    lines = []
    for order_id, refunds in context.observed_refunds.items():
        if not refunds:
            lines.append(f"订单 {order_id} 当前没有退款记录；本轮查询未提交新的申请。")
        for refund in refunds:
            state = REFUND_STATUS.get(refund["status"], "退款状态待核实，请联系人工客服。")
            lines.append(f"订单 {order_id} 的退款记录 {refund['id']}：金额 {refund['amount']} 元，{state}")
    return "\n".join(lines)


def render_reply(context: ToolContext, error_code: str | None) -> tuple[str, str]:
    """Only verified facts reach customers. Model prose cannot claim a payment happened."""
    if context.action:
        action = context.action
        prefix = f"工单 {action.ticket_id} 的售后申请已记录。"
        if action.decision == "DENY":
            return "POLICY_DENIED", prefix + action.explanation + "，当前未执行退款。"
        if action.decision == "NEED_MORE_INFO":
            return "NEED_MORE_INFO", prefix + action.explanation + "，当前未执行退款。"
        if action.execution_status == "WAITING_APPROVAL":
            value = "商品价值" if action.authorized_action == "REPLACE_ITEM" else "拟退款金额"
            return "WAITING_APPROVAL", prefix + f"{value}为 {action.amount:.2f} 元，需人工审批，尚未执行。"
        if action.execution_status == "WAITING_RETURN":
            return "WAITING_RETURN", prefix + f"拟退款 {action.amount:.2f} 元，需先确认退货收货，尚未退款。"
        if action.authorized_action == "CREATE_LOGISTICS_TICKET":
            return (
                "LOGISTICS_PENDING",
                prefix + "政策要求先进行物流调查或拦截，已提交建议等待管理员处理，未退款。",
            )
        return (
            "READY",
            prefix + f"拟退款 {action.amount:.2f} 元，政策校验通过，等待管理员模拟执行，尚未退款。",
        )
    if error_code:
        detail = "模型尚未配置" if error_code == "MODEL_NOT_CONFIGURED" else "本轮处理暂未完成"
        ticket = (
            f"已保留工单 {context.ticket_id}，可继续人工处理。" if context.ticket_id else "未提交退款申请。"
        )
        return "FAILED", f"{detail}。{ticket}请稍后重试或联系人工客服。"
    if context.finish:
        finish = context.finish
        if finish.kind == "REFUSE_UNAUTHORIZED":
            return (
                "REFUSED",
                "不能访问其他用户的订单、切换身份或绕过审批与执行权限。"
                "我只能在当前用户权限内查询订单并提交售后建议。",
            )
        if finish.kind in ASK:
            return "NEED_MORE_INFO", ASK[finish.kind]
        if finish.kind == "POLICY":
            return "ANSWERED", "\n".join(
                f"[{key}] {context.citations[key].content}" for key in finish.citation_ids
            )
        if finish.kind == "REFUNDS":
            return "ANSWERED", refund_reply(context)
        if finish.kind == "ORDER":
            order_reply = "\n".join(
                f"订单 {data['id']} 当前状态为 {data['status']}，原实付金额为 {data['paid_amount']} 元。"
                for data in context.observed_orders.values()
            )
            return "ANSWERED", "\n".join(filter(None, [order_reply, refund_reply(context)]))
    return "UNVERIFIED_RESPONSE", "本轮没有形成可验证的处理结果。请补充订单号和具体售后问题，或联系人工客服。"
