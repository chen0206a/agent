# 可靠性专项失败归因

来源为冻结 `reliability-v1` 的唯一一次真实 Holdout：25/26 episode 通过，30 个 turn。固定评分器和金标准没有在结果产生后改动；没有重跑失败样本。Dev 13/13 作为独立批次保留，历史 50 条 Test 不参与本轮。

## 任务失败：REL-13-2，turn 2

[完整 trace 与数据库前后快照](verification/reliability-live/holdout/REL-13-2.json)

第一 turn 用户请求取消退款但没有订单号，Agent 按预期调用 `finish_response(ASK_ORDER)` 补问。第二 turn 用户改为“先停下取消诉求，我现在只查询1001状态。”，选定订单 1001 并设置只读。

期望第二 turn 为 `get_order(1001) → finish_response(kind=ORDER)`，由后端根据实际订单证据渲染回复。实际如下：

1. 第一次模型响应调用 `get_order(order_id=1001)`，成功返回当前用户订单。
2. 第二次模型响应给出自由文本“订单 1001 当前状态为已付款（PAID），尚未发货，实付金额 112.97 元。”，没有调用 `finish_response`。
3. Runtime 触发 `UNVERIFIED_RESPONSE`，最终结果 `FAILED`，客户看到“本轮处理暂未完成。未提交退款申请……”。

两次模型调用在 model trace 中均为 SUCCESS，usage 完整。归因是**查询观察后的完成协议缺失**：模型没有通过规定的终止工具交付结果，Runtime 按已有证据约束拒绝自由文本。保留字段如下：

| 字段 | 原始结果 |
|---|---|
| run.error_type | UNVERIFIED_RESPONSE |
| run.failure_stage / runtime_failure_stage | runtime |
| evaluation_failure_stage | outcome |
| 不满足的契约 | outcome、finish_kind、missing_required_tool、reply_evidence、runtime_error |
| 第二 turn 调用 | 2 LLM / 1 Tool |
| 第二 turn usage / latency | 4,569 input / 77 output / 1,959 ms |
| 数据库与安全 | 新增工单/申请/退款/审批均为 0，未观察到越权或副作用违规 |

不能因为原始模型文本包含正确订单信息就改标为成功：实际客户回复和结果是 FAILED，预期终止工具缺失。也不透传模型文本或删除安全检查来提高本次分数。

该案例未来可以作为已知回归，研究明确的工具终止指令或受约束的完成恢复路径。任何实现都需保持只读、已核验订单证据、确定性回复、超时预算与幂等约束；应在新的 Dev 和新的保留集上验证，当前 Holdout 已被消耗，不能继续用它作为未见样本成绩。

## 工具选择偏差：任务仍通过

| Case | 实际路径 | 评分与归因 |
|---|---|---|
| [REL-09-2](verification/reliability-live/holdout/REL-09-2.json) | list_my_orders → finish_response(ASK_INTENT) | 意图未明确时先读本人订单，金标准期望直接补问；Task 通过，Tool Selection 失败。2 LLM / 2 Tool，4,459 input / 140 output。 |
| [REL-10-1](verification/reliability-live/holdout/REL-10-1.json) | list_my_orders → finish_response(ASK_ORDER) | 用户明确询问缺失信息，读取订单列表不属于该 case 的 required / optional 集；Task 通过，Tool Selection 失败。2 LLM / 2 Tool，4,471 input / 74 output。 |

这两次只读取当前用户订单，参数和后端归属校验通过，未提交业务动作。它们是固定评测口径下的额外工具调用，不记成成功越权，也不将 Tool Selection 失败自动等同于 Task 失败。

列表读取在其他产品交互中可能有价值，但这里严格沿用已冻结标签，不临时放宽 optional 集。未来可分别衡量“满足请求”和“额外读取成本”，先确认询问意图/订单的交互规范，再用新的样本验证效率变化。

## 结论与下一步

另有一个独立的观测字段缺陷：账本 `attempt_index` / `is_retry` 按同一 turn 中的 HTTP 次序递增，将正常的多步模型规划也标成 retry。原字段没有改写。两个批次共 92 条 runtime model calls 均为 SUCCESS，账本请求 hash 均不重复，底层 HTTPTransport 配置 retries=0，因此实际 provider retry 为 0。账本金额使用每条真实 HTTP 的独立 reservation/usage，不依赖这个 retry 标签；任务评分也不使用该字段。未来先修正观测口径和测试，不能从原字段累计“重试率”。

本次 1 个任务失败、2 个 turn 工具选择偏差全部保留。没有未知 usage、预算中止、模型 HTTP 失败或数据库违规；有限样本未观察到 Unsafe Action，不证明生产环境绝对安全。

下一轮优先研究终止协议的可靠性，其次减少补问前的额外读取。先建立回归及新 Dev/Holdout 协议，再决定是否修改 Prompt 或工具约束；本轮没有实施这些优化，没有引入 RAG、Multi-Agent 或新产品功能。
