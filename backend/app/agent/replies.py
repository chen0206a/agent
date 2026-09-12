from app.agent.tools import ToolContext

ASK = {
    "ASK_ORDER": "请提供需要处理的订单号，或先选择您自己的订单。",
    "ASK_ITEM": "请提供需要售后的具体商品或商品编号。",
    "ASK_QUANTITY": "请说明需要售后的商品数量。",
    "ASK_EVIDENCE": "请补充破损、错发或少件证据；本地演示可设置 evidence_provided=true，后续仍需人工核验。",
    "UNSUPPORTED": "请说明订单号、遇到的问题和希望的处理方式，我可以协助查询并提交售后申请。",
}


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
        if finish.kind == "ORDER":
            return "ANSWERED", "\n".join(
                f"订单 {data['id']} 当前状态为 {data['status']}，原实付金额为 {data['paid_amount']} 元。"
                for data in context.observed_orders.values()
            )
    return "UNVERIFIED_RESPONSE", "本轮没有形成可验证的处理结果。请补充订单号和具体售后问题，或联系人工客服。"
