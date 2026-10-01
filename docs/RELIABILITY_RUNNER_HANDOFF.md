# 真实模型评测运行器交接

已新增 `scripts/reliability_live.py`。本轮按用户明确选择**只完成运行器，暂不运行真实评测**；没有调用真实 DeepSeek API，也没有创建生产评测的 release、预算账本、开始标记或 Holdout seal。

产品代码、Prompt、Tool、数据集和既有 `reliability-v1` manifest 均保持冻结。新运行器复用冻结的评分器、ChatRequest、AgentService、PolicyEngine 与业务服务；新增测试仅使用临时数据库和模拟 HTTP。

## 实现

| 模块 | 行为 |
|---|---|
| prepare / verify | 显式预算及单价，校验产品/数据/配置冻结，另记录运行器和测试源码 hash |
| BudgetLedger | SQLite 持久事务；全 Dev/Holdout 共用一份账本；预约先提交，随后才发 HTTP |
| MeteredTransport | 记录 requested/returned model、UTC 时间、尝试编号、retry、输入/输出 usage、latency、request hash |
| 批次 metadata | 配置、Prompt、Tool、数据、产品 manifest、运行器源码 hash 和代码 commit |
| 预算停止 | 请求预约超额时不发网络请求；usage 不明或成本超过预约时停止下一次请求 |
| 单次执行 | 全局排他 lock，Dev/Holdout 各自不可覆盖 started marker；不会自动续跑付费请求 |
| Holdout seal | 完成 Dev 后提供已复核 summary hash，冻结该 Dev 与 release；之后才允许正式 Holdout |
| 逐 turn 证据 | 完整 trace、工具参数/结果、评分、failure attribution；每个 episode 业务数据库前后快照 |
| 幂等检查 | 使用同一请求再读结果；trace 与业务表不得新增变化 |
| summary | 固定 episode/turn 分母；中止后的案例保留为未运行；效率均值明确仅统计已观测 turn |
| audit | 读取已保存证据和账本；未知结果保持未知；不移除标记、不触发模型或业务操作 |

没有把审批、仓库确认或模拟退款执行工具提供给 Agent。新增 runtime 脚本不修改线上路由和客户端页面。

## 成本估算

2026-09-30 查验 [DeepSeek 官方定价](https://api-docs.deepseek.com/quick_start/pricing/)：V4.1-Flash 峰时缓存未命中输入 US$0.30 / 百万 tokens、输出 US$1.20 / 百万 tokens，谷时减半。官方说明旧 API 名称 `deepseek-v4-flash` 仍被接受，其请求由 V4.1-Flash 提供服务；因此没有改动本地已冻结模型名。

39 episode / 45 turn 的估算为 US$0.15–0.60，假设每 turn 累计约 1–3 万输入和 500–2000 输出 tokens，并留重试余量；不是当前模型的新测量。推荐新增总上限 US$2，**尚未得到真实执行预算授权**。执行前重新核对价格，保存来源与 UTC 核对时间，不能用本页价格代替未来实时核验。

预约以完整 payload UTF-8 字节数加 4096 framing tokens、配置的最大输出 tokens 和输入未命中价格估算。完整 usage 按统一保守价格结算，不按缓存/谷时折扣释放更多额度；未知 usage 保留预约并停批。该金额是**保守代理成本**，不是提供商账单，也不能严格证明私有 tokenizer 的上界。提供商实际 usage 超过预约时记录实际代理金额并停止；最终账单需另行核对。

## 使用顺序

本轮仅执行无网络命令和测试：

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/reliability_live.py --help
.\.venv\Scripts\python.exe -X utf8 scripts/reliability_eval.py verify
.\.venv\Scripts\python.exe -X utf8 -m pytest backend/tests/test_reliability_live.py -q
```

未来获得预算和实际运行授权后：

1. `prepare`：必须传 `--budget-usd`、`--input-usd-per-million`、`--output-usd-per-million`、`--price-source`、`--price-checked-at`。检查源码、数据和本地非敏感配置后排他创建 release，不能覆盖。
2. `verify`：核对产品和运行器版本。`run dev` 发起真实 Dev；在 `docs/verification/reliability-live/` 保存证据、账本和不可覆盖开始标记。
3. 人工复核所有失败及安全轨迹，检查预算，读取 Dev summary 文件 SHA-256。`seal-holdout --reviewed-dev-hash HASH` 明确固定已复核的结果。此参数记录复核声明，程序不能代替人工判断。
4. `run holdout` 正式执行一次。开始标记持久保留；即使中途失败或未完成，也不能删标记重跑后只报告好成绩。
5. 中断后用 `audit dev` 或 `audit holdout` 核对证据，无模型调用。未持久化的最后一步仍为未知，不推定失败或无副作用。

冻结版本的 Dev 也限制单次正式批次；若以后需要调参/再次 Dev，应明确建立新版本，不覆盖当前证据。代码、配置或数据改变会阻止 run，不能为了通过校验删除 manifest。

## 验证与限制

完整后端回归 **250 passed**；新增文件 Ruff 检查与格式检查通过。遗留 Starlette/AnyIO 弃用警告不影响验证。

新增 29 项工程测试通过，包含真实 Agent runtime 与模拟 HTTP 的完整批次、超预算零请求、账本重启、并发预约、未知 usage、超预约、重复结算、model metadata、凭据不进入账本、幂等重读、固定中止分母、全局 lock、seal、audit，以及不依赖 Python assert 的冻结校验。完整后端回归及 hash 见 [checks](verification/reliability-runner/checks.json)。

- 本轮没有重新运行前端/E2E，未改前端；没有执行真实或冻结 Holdout Agent 请求。
- 硬崩溃保留 lock、started marker、数据库和预约；没有实现自动对账或自动续跑。人工应核对提供商账单并保留原证据，不能直接重置账本。
- 原始隔离 SQLite 数据库被 Git 忽略；分享证据使用 JSON 快照、trace 和 budget-export，完整本地恢复需保留数据库文件。
- 运行器是单机顺序批次，使用文件排他和 SQLite 事务；未实现分布式调度、跨机器额度控制或后台任务系统。
- `audit` 不重评分未完成 episode；没有完整 checkpoint 的执行结果保守列为未知/未核验。
- 保留集仍是已知业务家族上的合成措辞；工程通过不代表当前模型 Task Success，也不更新历史 92% 成绩。

相关：[原始评测协议](RELIABILITY_EVALUATION_PLAN.md)、[评测准备交接](RELIABILITY_EVALUATION_HANDOFF.md)、[历史失败分析](STAGE5_FAILURE_ANALYSIS.md)。下一步仅在授权后开展真实评测，本轮不加入 RAG 或产品新功能。
