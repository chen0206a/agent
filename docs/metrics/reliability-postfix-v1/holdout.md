# 指标汇总：reliability-postfix-v1 / holdout

只读派生报告；未调用模型、未重跑评测、未修改冻结评分。来源 hash 及逐任务记录见 [holdout.json](holdout.json)。

| 指标 | 结果 |
|---|---:|
| Strict Task Success（episode） | 25/26（96.15%） |
| 业务目标达成（episode） | 26/26（100.00%） |
| Tool Selection（turn） | 30/30（100.00%） |
| Tool Arguments（turn） | 29/30（96.67%） |
| Required Tool Recall（micro） | 70/70（100.00%） |
| 政策/权限契约（episode） | 26/26（100.00%） |
| 多轮 Strict Task Success（episode） | 4/4（100.00%） |
| 幂等验证（turn） | 30/30（100.00%） |
| Unsafe Action 观察次数 | 0 |
| 数据库检查失败 episode | 0 |
| 工具错误后安全业务恢复（turn） | 1/1（100.00%） |
| 结束协议纠正后恢复（turn） | 无样本 / 未知 |
| HTTP 重试后恢复（logical request） | 无样本 / 未知 |

## 耗时与成本

| 范围 | 样本 | 平均 ms | P50 ms | P95 ms |
|---|---:|---:|---:|---:|
| 单轮 | 30 | 1958.267 | 2048.000 | 3550.000 |
| 任务累计活跃时间 | 26 | 2259.538 | 2187.000 | 4744.000 |

成本代理值：CNY 0.355236；每个严格成功任务：0.014209；每个业务成功任务：0.013663。
Input / Output Tokens：156974 / 5161。完整 usage 与费用证据：True。

## 场景分类

| Category | Strict Task Success | 业务目标达成 |
|---|---:|---:|
| cancel_apply | 2/2（100.00%） | 2/2（100.00%） |
| consult_to_apply | 2/2（100.00%） | 2/2（100.00%） |
| correct_to_query | 2/2（100.00%） | 2/2（100.00%） |
| deny_foreign | 2/2（100.00%） | 2/2（100.00%） |
| high_approval | 2/2（100.00%） | 2/2（100.00%） |
| logistics_apply | 1/2（50.00%） | 2/2（100.00%） |
| missing_intent | 2/2（100.00%） | 2/2（100.00%） |
| missing_order | 2/2（100.00%） | 2/2（100.00%） |
| natural_consult | 2/2（100.00%） | 2/2（100.00%） |
| policy_consult | 2/2（100.00%） | 2/2（100.00%） |
| refund_empty | 2/2（100.00%） | 2/2（100.00%） |
| refund_processing | 2/2（100.00%） | 2/2（100.00%） |
| refund_success | 2/2（100.00%） | 2/2（100.00%） |

## 调用与失败

LLM / Tool Calls：62 / 74；可选工具调用 2；不在允许集合 0；同名同参数重复 0；工具失败 1。
任务失败阶段：`{"tool_arguments": 1}`。

## 口径与边界

- 业务目标达成复用归档中的 outcome、动作/金额契约、响应证据、结束类型、政策与数据库检查，要求运行成功及幂等通过；不因已恢复的参数错误单独判失败。原 Strict 成绩保持不变。
- 这是既定合成任务的业务契约达成率，不是用户满意度、实际到账率或生产成功率。
- 缺失任务/轮次保留计划分母；业务证据未知计入覆盖缺口，不计为通过。当前覆盖：`{"planned_episodes": 26, "observed_episodes": 26, "completed_episodes": 26, "planned_turns": 30, "observed_turns": 30, "business_unknown_episodes": 0}`。
- Tool Selection 是允许工具名称集合检查，Tool Arguments 按整轮统计；Required Tool Recall 按必要工具项 micro 汇总。不同历史报告的 macro 值不能直接混用。
- P50 为中位数；P95 为最近秩法。任务时间为各轮运行耗时之和，不包含用户思考或人工审批等待。
- 恢复按实际触发统计；零触发为无样本。工具/协议恢复要求最终任务安全达成业务目标，HTTP 恢复只表示该逻辑模型请求最终有成功 usage，不代表业务成功。
- 同名同参数重复与可选调用是复核候选，不自动等于浪费；当前没有不必要调用率。
- 成本覆盖整个 split 的所有模型 attempt（包括失败），不是账户余额或提供商账单。缺 usage、费用或请求对应证据时显示未知，不按零计费。
- 未观察到不安全动作不等于 100% 安全；小样本恢复比例不代表总体可靠性。
- 原始模型请求文本、system prompt、reasoning 与用户消息不复制到本报告；完整轨迹保留在原归档。
