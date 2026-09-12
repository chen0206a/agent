# Stage 3 交接报告

> 本文保留 Stage 3 初次交接时的历史状态。后续配置、真实模型验收和轻量优化已完成，最新结论见 [STAGE3_5_HANDOFF.md](STAGE3_5_HANDOFF.md)；下文的“尚未配置”不代表当前状态。

日期：2026-09-09。项目：`D:\RAG-agent项目\after-sale-copilot`，版本 0.3.0。

**当前状态：Stage 3 工程实现和离线验证完成。DeepSeek 真实模型联调未执行，因为用户选择的具体模型名和本地密钥尚未配置。不能据离线结果宣称自然语言理解准确率或模型端到端效果已验收。**

## 已实现内容

1. LangGraph 单 Agent：reason → tools → reason 的有界循环，提交建议或补问后结束。
2. DeepSeek HTTPS Chat Completions 接口：function tools、模型配置、超时、有限重试、响应大小限制、错误分类。
3. 9 个受限工具：查询自己的订单/商品/物流/退款、检索政策、创建工单、提交建议、补问或依据证据回复。
4. 会话上下文：parent_run_id 关联同用户最近最多 6 轮历史，由服务器加载，不接受客户端伪造角色历史。
5. 服务端工具边界：身份、证据标记、工单/动作幂等键由可信调用上下文注入；模型不能传入金额、审批人或执行状态。
6. 基础政策检索：6 篇模拟政策，中文双字片段/英文词匹配，来源、版本、哈希；阈值和时间窗与 PolicyEngine 同源。
7. 回复依据校验：业务结论由已验证的 ActionRead 生成；自由文本“已退款”不成为客户事实。政策引用限定为已检索来源。
8. 本地 Trace：AgentRun、ToolCall、每次模型调用/重试、nullable token 用量、延迟和错误；不保存 reasoning_content，不上传 LangSmith。
9. 故障处理：同键同参重用运行，运行中并发请求返回 RUNNING；异常后按业务幂等键核对已提交动作，管理员可收尾过期中断运行。
10. 工单幂等：原 POST /tickets 新增可选 Idempotency-Key；Agent 始终使用服务端生成的键。

审批、仓库收货、模拟执行均保留原有管理员流程，未给 Agent 添加执行入口。

## 实际实施顺序

1. 读取现有数据模型、业务服务与路线，确认 Stage 1–2 基线。
2. 用户选择 DeepSeek；核对其工具调用协议和 LangGraph Graph API，保持模型名/密钥为空。
3. 增加 3 张兼容扩展表，先完成工单幂等和工具 schema。
4. 编写政策知识集、检索、DeepSeek provider、受限工具及按证据生成回复的模块。
5. 接入 LangGraph 循环、会话历史、预算和本地 Trace；增加 Agent HTTP API。
6. 建立脚本 provider 与 16 个离线场景，明确它们只测试编排，不测试自然语言能力。
7. 新增 45 项工程/协议测试，覆盖越权、参数注入、虚假业务回复、引用、超时、重试、幂等、恢复和兼容升级。
8. 通过原 96 项回归；补查真实 HTTP 与 Windows 测试进程清理，修复临时日志句柄占用的测试基础设施问题。
9. 备份默认数据库，新增表后逐表对比原 11 张表的行数与哈希，确认数据未改变。
10. 更新依赖锁、OpenAPI、使用说明和开发路线；保留真实模型联调的显式入口。

## 文件与调用链

| 文件 | 作用 |
|---|---|
| backend/app/agent/contracts.py | 对话、模型返回、工具参数、引用和 Trace 的契约 |
| backend/app/agent/provider.py | DeepSeek 协议适配与错误分类；不内置密钥 |
| backend/app/agent/tools.py | 允许名单、身份/订单/工单范围检查及服务调用 |
| backend/app/agent/runtime.py | LangGraph、幂等运行、历史、预算、Trace 和中断恢复 |
| backend/app/agent/replies.py | 根据已验证业务结果生成客户回复 |
| backend/app/agent/knowledge.json | 6 篇人工维护的模拟政策 |
| backend/app/agent/knowledge.py | 检索、同源阈值渲染、版本和引用哈希 |
| backend/app/agent/privacy.py | 常见凭据脱敏；不作为完整 DLP 宣传 |
| backend/app/agent/evaluation.py | 明确标识的脚本 provider、离线/真实模型评测入口 |
| backend/app/api/agent_routes.py | 新增 6 个 Agent HTTP 操作 |
| backend/app/models/entities.py | 增加 TicketSubmission、AgentRunDetail、ModelCall |
| backend/app/services/business.py | 原子创建幂等工单 |
| eval/agent-cases.json | 16 个自然语言输入与场景预期；离线时使用预设工具计划 |
| scripts/chat.ps1 | 中文 UTF-8 对话请求、续聊、证据与幂等键参数 |
| scripts/agent_http_fixture.py | 专供 HTTP 测试的预设模型 ASGI 入口，生产启动脚本不使用 |
| backend/tests/test_agent.py | Agent 编排、数据升级、API 与权限测试 |
| backend/tests/test_agent_provider.py | DeepSeek wire-format mock 与异常测试 |

调用链：`/agent/runs` → API 当前用户 → `AgentService.chat` → 幂等 AgentRun → LangGraph reason/工具循环 → `AgentTools` → 原 BusinessService / WorkflowService → PolicyEngine/Calculator/RiskEngine → `render_reply` → 保存运行 → ChatResult。

管理员后续仍通过 Stage 2 端点审批/收货/执行，Agent 的 final_action 保持真实执行语义。

## 数据升级

当前总计 14 张表。新增 `ticket_submissions`、`agent_run_details`、`model_calls`，不修改原 11 张表的结构。重复 init-db 可以补建，不清空已有数据。

升级前备份位于 `data/backups/before-stage3-20260909T030854Z.db`。升级前后逐表数据行数和 SHA-256 完全一致，证据见 [stage3-upgrade.json](verification/stage3-upgrade.json)。备份和数据库被 .gitignore 排除。

旧 AgentRun 整型 token 汇总因兼容保留，只表示已知值之和；真正的完整性判断和对外用量来自 nullable 的 ModelCall 记录。未知 usage 对外返回 null，不用 0 冒充完整统计。

## 验证结果与证据

| 验证 | 结果 | 范围 |
|---|---|---|
| pytest | **141 项全部通过** | 原 96 项 + 新增 45 项 |
| Stage 2 政策黄金案例 | **28/28** | 金额/业务规则回归 |
| Agent 脚本场景 | **16/16** | 编排与工具边界，不是模型准确率 |
| HTTP，模型未配置 | **31 次请求通过** | 真实 Uvicorn、无模型降级、原业务流程 |
| HTTP，scripted-fixture | **31 次请求通过** | 真实 Uvicorn、预设模型驱动 Agent 工具链 |
| DeepSeek wire-format | 纳入 pytest | MockTransport，无真实 API 请求 |
| 旧数据兼容升级 | 通过 | 原 11 张表数据完全不变 |
| Ruff / 格式 / pip check | 通过 | 代码格式与依赖一致性 |
| PowerShell chat.ps1 | 语法解析通过 | 未使用真实模型实跑 |
| DeepSeek 真实模型 | **未执行** | 缺模型名与密钥，不计算模型效果或费用 |

完整输出见 [summary.json](verification/summary.json)、[pytest.txt](verification/pytest.txt)、[Agent 离线报告](../eval/agent-offline-report.json)、[Agent HTTP 报告](verification/agent-http-smoke.json)。保留一条未屏蔽的 AnyIO/Starlette 第三方弃用提示。

两套 HTTP 请求以及 pytest 中的场景存在重叠，不把它们相加宣传为独立案例总数。scripted-fixture 和协议 mock 所产生的记录只在临时数据库中，不能作为真实 LLM 的用量或效果证据。

一键验收仍为：

```powershell
.\.venv\Scripts\python.exe scripts/verify.py
```

默认不会调用真实模型。所有测试与评测均使用隔离数据库，默认业务数据库保留用户此前数据。

## 如何使用

1. 复制 `.env.example` 为 `.env`，保留原有配置，填写 `ASC_LLM_MODEL` 与 `ASC_LLM_API_KEY`。模型需支持 DeepSeek tool calls；密钥不要发到聊天或提交 Git。
2. 执行 `scripts/start.ps1`，升级补建与 seed 检查后启动本机服务。
3. 查看 `/agent/status`，配置齐全时 configured 为 true；它不代表网络或模型实际可用。
4. 使用 Swagger 的 POST /agent/runs，或运行：

```powershell
.\scripts\chat.ps1 -UserId 1 -OrderId 1001 -Message '请取消订单1001并申请退款'
```

5. 需要补问时，下一次传 `-ParentRunId 上轮ID` 和新的请求内容；每次新消息使用新幂等键。网络重试同一消息则保留原 `-IdempotencyKey`。
6. 用管理员角色查看 `/agent/runs/{id}/trace`，检查真实工具参数、结果、来源和模型尝试。
7. 真实效果验收显式运行：

```powershell
.\.venv\Scripts\python.exe -m app.cli agent-evaluate --live --output eval/agent-live-report.json
```

该命令会访问已配置的模型并可能产生费用，但只使用隔离模拟订单。不要修改预期答案来迎合错误的模型输出。

## 已知限制与有意调整

- 模型仍未配置，无法声称自然语言补问、参数提取、工具选择或多轮体验在 DeepSeek 上已达到验收标准。
- 客户自然语言回复采用确定性模板和真实查询/引用内容。模型草稿仅供 Trace 审阅，以防虚假的退款/审批承诺；当前语言风格较固定。
- 同一轮只处理一个工单/一个建议动作。复杂跨单售后、多个商品同时处理、跨轮复用未完成工单需要后续设计。
- 当前凭据入口仍是本地演示身份；对模型不可切换身份，但生产认证尚未实现。
- 检索是小规模词项匹配，不包含 embedding、reranker 或大规模知识库；不能称为复杂 RAG。
- 证据只有调用方标记，没有图片存储；质量证据仍需人工核验。
- 运行超时在节点边界与网络层执行，数据库原子提交和锁等待可能增加最终收尾耗时。
- 崩溃窗口内用幂等键恢复已提交业务结果，不保证中断的外部模型 usage 可以找回；未知值保持 null。
- 没有后台自动恢复任务，管理员对超时 RUNNING 显式 recover。没有增加 Memory、MCP、多 Agent 或完整前端。
- HTTP 测试入口明确使用脚本 provider；正常 start.ps1 只使用 DeepSeekProvider，不会静默切换到假模型。

## 下一步

**优先补齐 Stage 3 真实模型验收**：选择模型、配置密钥 → 先跑一条低金额取消 → 审阅 Trace → 跑 16 个真实模型场景 → 记录意图/工具选择失败 → 修正提示和工具描述 → 冻结模型配置与评测结果。只有这一步完成后，才把 Stage 3 模型效果标为通过。

随后进入 Stage 4：真实登录和权限先行，客户会话/订单界面与管理员审批/Trace 界面复用当前 API。详细路线见 [V1_ROADMAP.md](V1_ROADMAP.md)。

阅读顺序建议：contracts → tools → knowledge → provider → replies → runtime → test_agent → evaluation。先理解“模型能做什么、不能做什么”，再读图循环和持久化。
