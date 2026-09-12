import type { Model } from "./api";
export const stages: Record<
  Model<"ExecutionStatus">,
  { label: string; hint: string }
> = {
  READY: { label: "待处理", hint: "申请已通过，等待处理，尚未退款" },
  WAITING_APPROVAL: {
    label: "待人工审核",
    hint: "退款申请已提交，正在等待人工审核",
  },
  WAITING_RETURN: {
    label: "待退货入库",
    hint: "等待仓库确认收到退货，尚未退款",
  },
  SUCCESS: { label: "处理完成", hint: "处理已完成，请查看具体退款结果" },
  REJECTED: {
    label: "申请未通过",
    hint: "人工审核未通过，可查看说明后联系客服",
  },
  BLOCKED: { label: "暂不支持", hint: "当前申请未满足售后条件" },
  FAILED: { label: "处理异常", hint: "退款尚未完成，客服会继续跟进" },
};
export const orderLabels: Record<Model<"OrderStatus">, string> = {
  PAID: "待发货",
  SHIPPED: "运输中",
  DELIVERED: "已签收",
  CANCELLED: "已取消",
  COMPLETED: "已完成",
  PENDING_PAYMENT: "待付款",
};
export const issueLabels: Record<Model<"IssueType">, string> = {
  CANCEL: "取消订单",
  NO_REASON_RETURN: "无理由退货",
  DAMAGED: "商品破损",
  WRONG_ITEM: "商品错发",
  MISSING_ITEM: "商品少件",
  NOT_RECEIVED: "未收到商品",
  OTHER: "其他问题",
};
export const money = (value: string | number) =>
  new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY" }).format(
    Number(value),
  );
export const date = (value?: string | null) =>
  value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
export function actionHint(action: Model<"ActionRead">) {
  if (action.authorized_action === "CREATE_LOGISTICS_TICKET")
    return action.execution_status === "SUCCESS"
      ? "物流调查工单已建立，仍需等待调查结果；未退款"
      : "已提交物流调查建议，等待客服处理；未退款";
  if (action.execution_status === "SUCCESS")
    return action.final_action === "REPLACE_ITEM"
      ? "换货处理已完成（模拟）"
      : "退款成功（模拟），款项已按申请金额记录";
  return stages[action.execution_status].hint;
}
