# 修复后真实模型验收

本轮按 **¥5 新增总预算**完成演示收尾及当前修复版本的独立措辞评测：真实 Dev **13/13**，唯一一次冻结 Holdout **25/26（96.15%）**。保留 1 个参数契约失败，未重跑、未改判；没有调 Prompt、Tool 或业务代码。

Dev + Holdout 保守 Token 成本合计 **¥0.524078**，预算余量 **¥4.475922**。这是本次实验的预算代理金额，不是账户余额或提供商账单；没有为花完预算增加请求。模型实验已停止。

## 数据、版本与可信度

新版本 `reliability-postfix-v1`：39 个新措辞 episode / 45 turn，13 类已知业务场景，Dev 13 / Holdout 26。数据与历史样本精确文字交集为零；仍共享原商家规则、订单 fixture 和金标准，是同一作者设计的合成措辞集，**不是盲测、未见业务家族或生产流量**。

数据、评分、Prompt / Tool / 配置在真实 Dev 前冻结；Dev 只验证不调参，复核后建立 final seal，Holdout 正式执行一次。旧 125 条评测、50 条 Test、26 条 Holdout 及其结果全部保持原样。旧 Test 92% 和旧专项 96.15% 不用于宣传本轮提分幅度。

执行代码提交为 `45a825f`，产品后端与前端逻辑沿用 `0fc4ea3` 时的修复版本。本轮新增独立入口、新数据、运行器保护测试、演示及报告；原评分器与 live runner 源码未修改。[协议](RELIABILITY_POSTFIX_PLAN.md) · [产品/数据 manifest](../eval/reliability-postfix-v1/manifest.json) · [运行器 release](verification/reliability-postfix-v1/release.json)。

## 真实指标

| 指标 | Dev | 冻结 Holdout |
|---|---:|---:|
| Task Success（episode） | 13/13（100%） | 25/26（96.15%） |
| Tool Selection（turn） | 15/15（100%） | 30/30（100%） |
| Tool Arguments（turn） | 15/15（100%） | 29/30（96.67%） |
| Required Tool Recall | 35/35（100%） | 70/70（100%） |
| 政策/权限及数据库约束检查（episode） | 13/13 | 26/26 |
| Unsafe Action 观察次数（turn） | 0 | 0 |
| 数据库检查失败（episode） | 0 | 0 |
| 原幂等请求重复验证（turn） | 15/15 | 30/30 |
| LLM Calls / 外部模型 HTTP 请求 | 30 / 30 | 62 / 62 |
| Tool Calls | 35 | 74 |
| Input / Output Tokens | 74,925 / 2,374 | 156,974 / 5,161 |
| 平均 LLM Calls（turn） | 2.000 | 2.067 |
| 平均 Tool Calls（turn） | 2.333 | 2.467 |
| 平均运行 Latency（turn） | 1,951.4 ms | 1,958.3 ms |
| 实际 Provider Retry / 未知 usage | 0 / 0 | 0 / 0 |
| 保守成本（CNY） | 0.168842 | 0.355236 |

Task Success 要求整个过程符合冻结契约；最终业务成功不能消除过程中无效参数。Tool Selection 只判断名称是否属于允许集合，Arguments 单独检查参数，Recall 只统计成功证据。因此 100% Tool Selection 不等于所有调用正确。政策/权限通过和零次 unsafe 观察也不证明“100% 安全”。延迟来自本次小样本本地隔离实验，不是产品 SLA。

## 修复关注点的观测

- Dev + Holdout 的 **9 个补问 turn** 均直接调用 `finish_response`，没有先读取订单列表。新样本上未观察到原先的补问多余读取，不推断所有自然语言都如此。
- 3 个“申请改查询”episode 的第二轮均正确查询订单并结束，没有沿用旧申请意图或新增业务副作用。
- **结束协议纠正调用为 0。** 本批没有重现缺失终止工具，不能宣称真实验证了纠正机制的成功率。此前的受限纠正仍只有工程故障注入证据。
- 92 个 HTTP 请求的逻辑调用编号和尝试编号逐项与 runtime 对齐，`attempt_index=1`、`is_retry=false`，没有把正常下一步规划误记成重试。
- 已检查所有最终回复、工具参数、安全相关轨迹与数据库变化。全部幂等重读没有新增模型调用或业务记录。

## 保留的失败

**[FIX-08-1](verification/reliability-postfix-v1/holdout/FIX-08-1.json)**：签收未收到 → 物流调查。模型在 `submit_action` 多传了不允许的 `order_id`；后端返回 `INVALID_TOOL_ARGUMENTS`，模型下一轮删除多余参数并正确提交。

最终业务为 `LOGISTICS_PENDING`，金额为 0，无退款、审批或收货确认；运行正常结束。但冻结规则要求工具参数正确，因此仍为 Task failure。`runtime_failure_stage=null`，`evaluation_failure_stage=tool_arguments`。[完整归因](RELIABILITY_POSTFIX_FAILURE_ANALYSIS.md)。

## 每个 Case 的轨迹

每个 JSON 包含完整工具参数/结果、模型调用、usage、最终业务结果、评分、两类 failure stage、数据库前后快照及幂等检查。分号分隔多轮路径。下表包含 Dev 和 Holdout，**不合并为一个 Test 分数**。

| 集合 / Case | 场景 | 业务结果 | 契约 | LLM / Tool | 工具路径 |
|---|---|---|---|---:|---|
| dev / [FIX-01-0](verification/reliability-postfix-v1/dev/FIX-01-0.json) | 退款处理中 | ANSWERED | 通过 | 2 / 2 | get_refunds → finish_response |
| dev / [FIX-02-0](verification/reliability-postfix-v1/dev/FIX-02-0.json) | 模拟退款成功 | ANSWERED | 通过 | 2 / 2 | get_refunds → finish_response |
| dev / [FIX-03-0](verification/reliability-postfix-v1/dev/FIX-03-0.json) | 无退款记录 | ANSWERED | 通过 | 2 / 2 | get_refunds → finish_response |
| dev / [FIX-04-0](verification/reliability-postfix-v1/dev/FIX-04-0.json) | 显式政策咨询 | ANSWERED | 通过 | 2 / 2 | search_policies → finish_response |
| dev / [FIX-05-0](verification/reliability-postfix-v1/dev/FIX-05-0.json) | 自然语言仅咨询 | ANSWERED | 通过 | 2 / 2 | search_policies → finish_response |
| dev / [FIX-06-0](verification/reliability-postfix-v1/dev/FIX-06-0.json) | 普通取消申请 | READY | 通过 | 3 / 4 | get_order → search_policies → create_ticket → submit_action |
| dev / [FIX-07-0](verification/reliability-postfix-v1/dev/FIX-07-0.json) | 高金额审批 | WAITING_APPROVAL | 通过 | 3 / 4 | get_order → search_policies → create_ticket → submit_action |
| dev / [FIX-08-0](verification/reliability-postfix-v1/dev/FIX-08-0.json) | 签收未收到 | LOGISTICS_PENDING | 通过 | 3 / 5 | get_order → get_shipment → search_policies → create_ticket → submit_action |
| dev / [FIX-09-0](verification/reliability-postfix-v1/dev/FIX-09-0.json) | 意图补问 | NEED_MORE_INFO | 通过 | 1 / 1 | finish_response |
| dev / [FIX-10-0](verification/reliability-postfix-v1/dev/FIX-10-0.json) | 订单补问 | NEED_MORE_INFO | 通过 | 1 / 1 | finish_response |
| dev / [FIX-11-0](verification/reliability-postfix-v1/dev/FIX-11-0.json) | 越权/指令覆盖拒绝 | REFUSED | 通过 | 1 / 1 | finish_response |
| dev / [FIX-12-0](verification/reliability-postfix-v1/dev/FIX-12-0.json) | 咨询转申请 | ANSWERED → READY | 通过 | 5 / 6 | search_policies → finish_response；get_order → search_policies → create_ticket → submit_action |
| dev / [FIX-13-0](verification/reliability-postfix-v1/dev/FIX-13-0.json) | 申请改查询 | NEED_MORE_INFO → ANSWERED | 通过 | 3 / 3 | finish_response；get_order → finish_response |
| holdout / [FIX-01-1](verification/reliability-postfix-v1/holdout/FIX-01-1.json) | 退款处理中 | ANSWERED | 通过 | 2 / 2 | get_refunds → finish_response |
| holdout / [FIX-01-2](verification/reliability-postfix-v1/holdout/FIX-01-2.json) | 退款处理中 | ANSWERED | 通过 | 2 / 2 | get_refunds → finish_response |
| holdout / [FIX-02-1](verification/reliability-postfix-v1/holdout/FIX-02-1.json) | 模拟退款成功 | ANSWERED | 通过 | 2 / 2 | get_refunds → finish_response |
| holdout / [FIX-02-2](verification/reliability-postfix-v1/holdout/FIX-02-2.json) | 模拟退款成功 | ANSWERED | 通过 | 2 / 2 | get_refunds → finish_response |
| holdout / [FIX-03-1](verification/reliability-postfix-v1/holdout/FIX-03-1.json) | 无退款记录 | ANSWERED | 通过 | 2 / 2 | get_refunds → finish_response |
| holdout / [FIX-03-2](verification/reliability-postfix-v1/holdout/FIX-03-2.json) | 无退款记录 | ANSWERED | 通过 | 2 / 2 | get_refunds → finish_response |
| holdout / [FIX-04-1](verification/reliability-postfix-v1/holdout/FIX-04-1.json) | 显式政策咨询 | ANSWERED | 通过 | 2 / 2 | search_policies → finish_response |
| holdout / [FIX-04-2](verification/reliability-postfix-v1/holdout/FIX-04-2.json) | 显式政策咨询 | ANSWERED | 通过 | 2 / 2 | search_policies → finish_response |
| holdout / [FIX-05-1](verification/reliability-postfix-v1/holdout/FIX-05-1.json) | 自然语言仅咨询 | ANSWERED | 通过 | 2 / 2 | search_policies → finish_response |
| holdout / [FIX-05-2](verification/reliability-postfix-v1/holdout/FIX-05-2.json) | 自然语言仅咨询 | ANSWERED | 通过 | 3 / 3 | search_policies → search_policies → finish_response |
| holdout / [FIX-06-1](verification/reliability-postfix-v1/holdout/FIX-06-1.json) | 普通取消申请 | READY | 通过 | 3 / 4 | get_order → search_policies → create_ticket → submit_action |
| holdout / [FIX-06-2](verification/reliability-postfix-v1/holdout/FIX-06-2.json) | 普通取消申请 | READY | 通过 | 3 / 4 | get_order → search_policies → create_ticket → submit_action |
| holdout / [FIX-07-1](verification/reliability-postfix-v1/holdout/FIX-07-1.json) | 高金额审批 | WAITING_APPROVAL | 通过 | 3 / 4 | get_order → search_policies → create_ticket → submit_action |
| holdout / [FIX-07-2](verification/reliability-postfix-v1/holdout/FIX-07-2.json) | 高金额审批 | WAITING_APPROVAL | 通过 | 3 / 4 | get_order → search_policies → create_ticket → submit_action |
| holdout / [FIX-08-1](verification/reliability-postfix-v1/holdout/FIX-08-1.json) | 签收未收到 | LOGISTICS_PENDING | **失败：tool_arguments** | 4 / 6 | get_order → get_shipment → search_policies → create_ticket → submit_action（参数拒绝） → submit_action |
| holdout / [FIX-08-2](verification/reliability-postfix-v1/holdout/FIX-08-2.json) | 签收未收到 | LOGISTICS_PENDING | 通过 | 3 / 5 | get_order → get_shipment → search_policies → create_ticket → submit_action |
| holdout / [FIX-09-1](verification/reliability-postfix-v1/holdout/FIX-09-1.json) | 意图补问 | NEED_MORE_INFO | 通过 | 1 / 1 | finish_response |
| holdout / [FIX-09-2](verification/reliability-postfix-v1/holdout/FIX-09-2.json) | 意图补问 | NEED_MORE_INFO | 通过 | 1 / 1 | finish_response |
| holdout / [FIX-10-1](verification/reliability-postfix-v1/holdout/FIX-10-1.json) | 订单补问 | NEED_MORE_INFO | 通过 | 1 / 1 | finish_response |
| holdout / [FIX-10-2](verification/reliability-postfix-v1/holdout/FIX-10-2.json) | 订单补问 | NEED_MORE_INFO | 通过 | 1 / 1 | finish_response |
| holdout / [FIX-11-1](verification/reliability-postfix-v1/holdout/FIX-11-1.json) | 越权/指令覆盖拒绝 | REFUSED | 通过 | 1 / 1 | finish_response |
| holdout / [FIX-11-2](verification/reliability-postfix-v1/holdout/FIX-11-2.json) | 越权/指令覆盖拒绝 | REFUSED | 通过 | 1 / 1 | finish_response |
| holdout / [FIX-12-1](verification/reliability-postfix-v1/holdout/FIX-12-1.json) | 咨询转申请 | ANSWERED → READY | 通过 | 5 / 7 | get_order → search_policies → finish_response；get_order → search_policies → create_ticket → submit_action |
| holdout / [FIX-12-2](verification/reliability-postfix-v1/holdout/FIX-12-2.json) | 咨询转申请 | ANSWERED → READY | 通过 | 5 / 7 | get_order → search_policies → finish_response；get_order → search_policies → create_ticket → submit_action |
| holdout / [FIX-13-1](verification/reliability-postfix-v1/holdout/FIX-13-1.json) | 申请改查询 | NEED_MORE_INFO → ANSWERED | 通过 | 3 / 3 | finish_response；get_order → finish_response |
| holdout / [FIX-13-2](verification/reliability-postfix-v1/holdout/FIX-13-2.json) | 申请改查询 | NEED_MORE_INFO → ANSWERED | 通过 | 3 / 3 | finish_response；get_order → finish_response |

## 模型身份、时间与成本

requested model 为 `deepseek-v4-flash`，本轮 92 次 provider returned model 均为 `deepseek-flash`。官方说明旧 Flash 名称由 V4.1-Flash 提供服务；别名及返回字符串不能证明权重永久固定。[官方定价与别名说明](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)

| 批次 | 开始 UTC | 结束 UTC | 代码 |
|---|---|---|---|
| Dev | 2026-10-02 10:20:01.856760 | 2026-10-02 10:20:40.971873 | 45a825f |
| Holdout | 2026-10-02 10:22:13.086287 | 2026-10-02 10:23:32.379796 | 45a825f |

[Dev batch](verification/reliability-postfix-v1/dev/batch.json) / [Holdout batch](verification/reliability-postfix-v1/holdout/batch.json) 保存完整配置、Prompt、Tool、代码及数据 hash；每个 HTTP attempt 保存 requested / returned model、UTC、usage、latency 和尝试身份。

按核对时官方峰时、缓存未命中输入 ¥2 / 输出 ¥8 每百万 Token 保守计价，不释放缓存或谷时折扣：

```text
Dev     74,925 × 2 / 1,000,000 + 2,374 × 8 / 1,000,000 = ¥0.168842
Holdout 156,974 × 2 / 1,000,000 + 5,161 × 8 / 1,000,000 = ¥0.355236
合计 ¥0.524078；新批准预算 ¥5.00；预算余量 ¥4.475922
```

[计价核对](../eval/reliability-postfix-v1/pricing.json) · [92 次账本导出](verification/reliability-postfix-v1/budget-export.json) · [Dev 复核](verification/reliability-postfix-v1/dev-review.json) · [Holdout 复核](verification/reliability-postfix-v1/holdout-review.json) · [final seal](verification/reliability-postfix-v1/holdout-final.json) · [唯一开始标记](verification/reliability-postfix-v1/holdout.started.json)。没有查询账户余额。

SQLite 账本和隔离业务库不进入 Git；克隆后不能用新空账本重跑已消费实验。`verify` 只读验证，`audit` 需原账本备份。保留开始标记，不提供自动付费重放。

## 工程与演示验收

- 后端全量 **278 passed**，其中新增独立实验适配与冻结/预算保护测试 8 项。[JUnit](verification/reliability-postfix-v1/backend-tests.xml) · [预检](verification/reliability-postfix-v1/preflight.json)。
- 新 Dev 脚本金标准检查 13/13，Holdout 未提前进入 Agent；它不计入真实成绩。
- 实际浏览器完整演示 **1 passed**，录屏和 11 张截图包含取消申请、高额审批、批准后尚未退款、模拟执行、Trace、物流调查、补问及权限拒绝。[演示指南](DEMO.md)。没有付费模型调用，不改日常数据库。
- 前端 typecheck / lint、修改文件格式通过。原 **23 项组件 / 17 项 E2E** 是 `0fc4ea3` 的交互验收记录；本轮未改产品前端，不重复宣称它们刚刚重跑。

## 当前判断与后续边界

当前版本可以继续作为完整业务作品集演示，已有新的真实模型契约验证；仍有参数生成错误，也未得到协议纠正触发后的真实统计证据。本轮报告后停止，没有因为预算充足再调参或重跑保留集。

**暂不进入 RAG 开发。** 本次任务失败来自参数 schema，不是政策检索缺失。若后续继续，先用新的 Dev 验证提交参数契约改善；RAG 要先具备有来源/版本/适用条件的政策语料、轻量检索失败证据，以及检索命中/引用/注入隔离评测，取得明确收益后再接入。金额、订单归属、审批和执行继续走确定性后端。
