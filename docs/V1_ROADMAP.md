# V1 路线与下一步开发计划

## 已完成：Stage 1

数据库、模拟数据、Pydantic API、业务服务、仓储、配置、日志、UTC/金额类型、外键/数量/状态约束、pytest。保留 agent_runs/tool_calls 表，但没有宣称已具备 Agent。

## 已完成：Stage 2

版本化 PolicyEngine、RiskEngine、RefundCalculator；优惠分摊与部分退款；申请幂等和额度预留；审批、退货收货、模拟执行与失败重试；并发保护；政策快照与审计；28 个规则黄金案例及真实 HTTP 验证。

Stage 3 工程与 Stage 3.5 代表性真实 DeepSeek 联调均已完成。

## 已完成：Stage 3 与 Stage 3.5

以下工程步骤已落地，详见 STAGE3.md；真实模型验收范围以 STAGE3_5_HANDOFF.md 为准。

1. **工具契约与权限上下文**：9 个受限工具的 schema，工具从服务端当前用户上下文注入身份，不允许模型自行选择 user_id；已补创建工单幂等。Stage 4 已将身份入口替换为服务端真实会话。
2. **政策知识基线**：整理少量人工维护、带版本与来源的模拟政策文档，先用简单检索；检索提供说明和证据，确定性引擎继续负责业务许可。
3. **单个 LangGraph 流程**：输入 → 理解问题 → 查询必要数据 → 提交 proposed_action → 读取政策结果 → 回复。只在确有需要时使用 LangChain 组件。
4. **限制模型权限与预算**：允许名单工具、最大步骤、调用超时、重试限制；审批和模拟执行端点不暴露给模型；密钥从环境读取。
5. **真实 Trace**：记录运行起止、每次工具参数/结果摘要、错误、模型返回用量和延迟。未提供的 token 信息标记未知，不能伪造为零。
6. **评测同步接入**：将当前结构化案例扩展为自然语言请求、歧义问题、工具失败、越权尝试和提示注入样例；与规则基线比较。

**Stage 3 验收条件**：至少覆盖 10 类售后诉求；正确补问订单/商品信息；无法跨用户读数据；无法绕过政策或调用审批/执行；每条关键结论可追溯到工具数据或政策来源；运行有步数和时间限制；LLM 离线/超时有明确降级结果；测试和评测同时通过。

**当前状态**：工程与离线回归通过；Stage 3.5 按用户约定完成 5 个代表性真实场景的 baseline/optimized 对照，优化后 5/5 通过，配置和完整轨迹已冻结。见 [STAGE3_5_HANDOFF.md](STAGE3_5_HANDOFF.md)。该结论限于本轮 5 个真实场景；原规划中更广的诉求、自然语言变体和长期稳定性尚未完成真实模型验收，16 个脚本场景不能替代它们。

Stage 3.5 已验收；随后按用户授权完成 Stage 4。

## 已完成：Stage 4 界面与真实权限

Customer Portal 展示售后会话、订单物流与工单状态；Admin Console 展示工单、审批、证据、审计与 Agent Trace。

已实现 scrypt 本地密码、服务端会话、CSRF、后端角色/归属校验，移除演示身份头。Next.js 客户与管理员页面复用现有业务服务，OpenAPI 生成 TypeScript 类型；审批、退货与执行状态分别展示。完成报告见 [STAGE4_HANDOFF.md](STAGE4_HANDOFF.md)。

**验收条件**：两种角色可以演示完整业务路径；所有越权端到端测试通过；刷新页面状态不丢失；不把模型内部参数、堆栈或调试标识塞进客户操作流程。

## 已完成：Stage 5 评测驱动优化

冻结 125 条合成场景（Dev 75 / Test 50），完成 baseline、两轮 Dev 对照，第二轮回滚，采用第一轮版本。最终 Test 正式执行一次，46/50 通过，观察到四类实际安全违规均为 0；保留全部失败、模型身份、版本 hash、用量和轨迹。详见 [STAGE5_EVALUATION.md](STAGE5_EVALUATION.md)、[STAGE5_FAILURE_ANALYSIS.md](STAGE5_FAILURE_ANALYSIS.md)、[STAGE5_PORTFOLIO.md](STAGE5_PORTFOLIO.md)、[RESUME_METRICS.md](RESUME_METRICS.md)。

Stage 5 完成后停止。以下仅保留未来可能方向，不代表已授权或开始。

## 视需求再做

Alembic 与 PostgreSQL 迁移、多包裹、真实库存模拟、退货质检拒收、申请撤回/到期释放、证据文件、运费税费和更复杂促销。在接入前明确金额、数量、状态及审计语义。Multi-Agent、MCP、Memory 暂无业务必要性，不列为默认目标。
