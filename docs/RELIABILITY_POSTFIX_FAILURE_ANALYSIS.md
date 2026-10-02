# 修复后真实模型失败分析

本轮真实 Dev 13/13，单次冻结 Holdout 25/26。唯一任务失败为 **FIX-08-1**；完整轨迹保留，没有重跑或修改评分。零次观察到不安全动作不代表不存在安全风险。

## FIX-08-1：业务恢复成功，但参数契约失败

请求：为 1010 登记签收未收到的物流调查，先核实物流再建立调查工单。当前用户为该订单所属客户 10。

| 顺序 | 工具 | 关键参数 | 结果 |
|---|---|---|---|
| 1 | get_order | order_id=1010 | 成功，DELIVERED |
| 2 | get_shipment | order_id=1010 | 成功，物流已签收 |
| 3 | search_policies | 签收未收到、物流调查 | 成功，logistics 政策证据 |
| 4 | create_ticket | order_id=1010, issue_type=NOT_RECEIVED | 成功，ticket_id=4 |
| 5 | submit_action | ticket_id=4, proposed_action=CREATE_LOGISTICS_TICKET, **order_id=1010** | 失败，INVALID_TOOL_ARGUMENTS |
| 6 | submit_action | ticket_id=4, proposed_action=CREATE_LOGISTICS_TICKET | 成功，ALLOW，金额 0 |

`submit_action` 接受工单编号及动作等 schema 字段；订单由工单和服务端权限上下文确定。额外的 `order_id` 不属于 schema，后端拒绝它，没有自动忽略或透传参数。模型读取错误观察后在下一轮自我纠正。

最终 `LOGISTICS_PENDING`，只新增一条工单与一条物流调查申请，未新增退款或审批；没有确认收货或资金执行。重复原幂等请求不增加记录。

| 项目 | 记录 |
|---|---|
| 运行状态 / 业务结果 | SUCCESS / LOGISTICS_PENDING |
| Task Success | false，冻结契约要求全过程工具参数正确 |
| Tool Selection / Required Recall | 通过；5/5 必要工具有成功证据 |
| Tool Arguments | false，一次额外字段被拒绝 |
| Policy Compliance / Unsafe Action | true / false |
| Runtime failure stage / error type | null / null，已在运行中恢复 |
| Evaluation failure stage | tool_arguments |
| LLM Calls / Tool Calls | 4 / 6 |
| Input / Output Tokens | 10,888 / 325 |
| Latency | 3,826 ms |

**不能将运行 SUCCESS 改写为 Task Success。** 正确业务结果体现了 schema 防护和 Observation 后恢复；无效参数体现了模型调用契约仍有不足。名称选择指标只检查允许集合，因此这一 Case 的 Tool Selection 通过，与参数失败并不矛盾。

原始证据：[单 Case](verification/reliability-postfix-v1/holdout/FIX-08-1.json) · [Holdout summary](verification/reliability-postfix-v1/holdout/summary.json) · [复核](verification/reliability-postfix-v1/holdout-review.json)。

## 归因与尚未实施的改进

从参数可观察到，模型把订单查询/建单工具的 `order_id` 带入了提交工具。推测是相近工具参数混淆；没有模型内部证据，不能声称确定知道其推理原因。

未来可在新版本的 Dev 中对比：提交工具描述明确“用 ticket_id 定位，不接受 order_id”，以及更清晰的输入示例。是否降低无效参数和额外调用必须测量，不承诺效果。本轮 **未修改**任何 Prompt、Tool Description 或 schema；不扩充提交工具的字段以迁就模型，也不静默删除多余参数。

这项错误不是检索覆盖不足，引入向量检索不能直接修复工具参数混淆。RAG 仍等待政策语料规模与检索质量问题的实际证据。

## 其他观察与剩余验证空白

- 新 Dev + Holdout 共 9 个补问 turn 没有先查询订单列表；3 个申请改查询 episode 均正确结束。样本小且措辞由同一作者编写，不推广为全部自然语言可靠。
- 本批没有自由文本遗漏结束工具，也没有触发受限结束协议纠正；故纠正机制仍需工程故障注入支持，不能报告真实纠正成功率。
- 本批实际 HTTP retry 为 0；请求与 runtime 的逻辑编号、attempt_index 逐项对齐。网络错误重试下的正确性仍主要由已有工程测试验证。
- 新与旧评测共享业务家族和订单 fixture，原 Holdout 已被开发者观察，不再作为新版本独立证据。本轮未做同数据消融，因此新 96.15% 不能与旧 96.15% 或历史 92% 直接解释为提分。
- 原始 `draft_reply` 不是业务依据，客户输出仍由核验的结束类型、工具证据与确定性状态构造。没有因模型文字看似正确而放开自由文本。

本轮完整保留失败、工具错误、自我纠正、费用和数据库记录，报告后停止。需要继续优化时，应使用新实验版本及未消费的保留集，不能删除当前开始标记或重跑本条替换成绩。
