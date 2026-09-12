# Stage 3：单 Agent、政策检索与受限工具

工程已实现，离线测试不依赖模型密钥。Stage 3.5 已使用 DeepSeek 完成 5 个代表性真实场景的优化前后验收，详见 [STAGE3_5_HANDOFF.md](STAGE3_5_HANDOFF.md)。优化新增 `finish_response(REFUSE_UNAUTHORIZED)`，生成受限的明确拒绝回复（outcome=`REFUSED`）；业务权限不变。

## 运行流程

`POST /agent/runs` 接收自然语言和可选订单范围 → 服务端绑定当前用户 → 创建幂等 AgentRun → LangGraph reason 节点调用 DeepSeek → tools 节点校验并执行允许的工具 → 把工具结果交回模型决定下一步 → 提交建议或补问后结束 → 根据已验证结果生成回复 → 保存运行和调用记录。

每轮图单独创建，状态与工具上下文不跨用户共享。没有多 Agent，也没有调用管理员工具的路径。审批、收货、模拟执行仍是 Stage 2 的人工角色操作。

模型负责意图理解、必要信息判断、工具选择、参数和建议动作；Python 继续负责身份校验、金额、政策、风险、幂等与实际业务状态。

## 允许的 9 个工具

| 工具 | 能力与约束 |
|---|---|
| list_my_orders | 只能列出当前用户订单；有显式订单范围时进一步过滤 |
| get_order | 每次查询均检查当前用户归属和本轮显式订单范围 |
| get_order_items | 先检查订单归属，再读商品行 |
| get_shipment | 只读物流，签收不等于客户确认收到 |
| get_refunds | 只读历史及在途退款 |
| search_policies | 检索本地维护的版本化政策段落 |
| create_ticket | 只处理已查询订单；用户和原始描述由服务器注入；服务端幂等键 |
| submit_action | 仅允许本轮创建的工单；要求已查询订单、政策及相关商品；参数无金额、用户、证据和审批字段 |
| finish_response | 选择补问类型或引用已检索政策/已查订单；不能编造引用 |

参数全部由 Pydantic 校验，`extra=forbid`，数量和 ID 拒绝布尔值。模型建议的 `evidence_provided` 不会被接受：证据标记来自客户请求，在 Stage 4 接附件系统前仍是演示输入。

政策拒绝或需要人工审批依然可以是一次成功完成的 Agent 协助；它不意味着售后动作已经成功执行。

## 对话与幂等

`ChatRequest` 字段：message、idempotency_key、可选 parent_run_id/order_id、evidence_provided。没有 user_id、system prompt、角色或任意历史消息字段。

身份沿用本地演示会话，由 API 依赖注入。模型从工具描述中无法切换身份。**当前身份仍由本机请求头模拟，不是生产认证**；Stage 4 将替换入口。

续聊使用 `parent_run_id`，仅加载同用户最近最多 6 轮的原始用户消息和服务器生成的回复，不接收客户自行构造的 assistant/system 历史。不实现向量长期 Memory。此前发生的工具结果不会直接作为新一轮授权依据，操作前重新查询。

每个用户的 run 幂等键唯一，规范化请求指纹不一致返回 409；同键同参返回已有结果。并发重试在首轮运行中返回 202/RUNNING，不开启第二次模型调用。

工单新增 `Idempotency-Key` 请求头。Agent 的工单与动作键由服务器生成：`agent:{run_id}:ticket` / `agent:{run_id}:action`。同轮重复创建/提交不会产生额外业务记录。

## 回复真实性

模型可提供 `draft_reply` 供调试审阅，但客户业务回复完全依据政策结果、执行状态、查询事实或允许的补问类型生成。模型自由文本声称“已退款”时，系统返回 UNVERIFIED_RESPONSE，不把它当作事实。

提交动作后立即结束 Agent 工具循环，根据 `ActionRead` 输出拟退款金额、等待审批、等待退货或政策拒绝等状态。物流场景表述为已提交调查建议，等待管理员处理，不声称调查完成。

这是对初始“模型直接生成最终客服回复”的有意调整：当前优先保证资金及业务结论准确，语言风格变化留待真实模型评测稳定后扩展。

GET 运行详情中的 `reply` 是当时保存的历史回复；`action` 返回对应售后申请的最新状态。管理员后续完成退款时，历史回复不会被改写，界面应以最新 action 展示当前业务进度。

## 政策检索

6 篇人工维护政策存于 `backend/app/agent/knowledge.json`。检索用英文词与中文双字片段重合度排序，最多返回 3 篇；当前数据量不需要向量数据库。它能提供出处，不保证自然语言检索质量已通过真实模型验证。

期限和金额阈值从相同 Settings 渲染，版本与 PolicyEngine 一致。每份结果包含 id、标题、版本、内容、SHA-256 和本地 source 路径。模型只能引用本轮真正检索到的 id。

当前引用快照保存在运行详情，`GET /agent/policies/{id}` 返回当前进程配置对应的文档；旧快照与最新文档可能在配置变更后不同，应查看版本和哈希。规则引擎仍是最终业务许可来源，检索文本不能覆盖它。

## DeepSeek 接口与预算

通过 httpx 访问配置的 HTTPS `/chat/completions`，使用 JSON function tools 和非流式响应，显式关闭 thinking。模型名无默认值，用户决定后写入 `.env`。没有使用需要额外 Beta 端点的 strict mode；所有工具参数仍由本地严格校验。

默认最多 8 次 reason 步骤、12 次工具执行、每次模型请求最长 20 秒、整轮 90 秒；429/5xx/网络超时最多重试 1 次。不会重试业务执行操作，更不会绕过幂等创建第二笔申请。

上下文消息上限 40000 字符、模型输出最多 1024 token、单工具结果最多 20000 字符、模型响应最多 250000 字节。时限在节点/网络/工具调用前后检查；已开始的本地数据库事务保持原子提交，不因到点强行杀线程。因此总耗时可能包含数据库锁等待和最终落库时间，不宣称硬实时截止。

错误码区分未配置、网络超时、HTTP 错误、响应格式、上下文/步数/工具上限。HTTP 错误正文不记录，也不回传给客户。URL 只允许 HTTPS，不允许内嵌凭据或查询字符串；不跟随重定向。

## 本地 Trace 与恢复

使用已有 `agent_runs/tool_calls`，新增 `agent_run_details/model_calls`。记录实际起止、模型/工具参数和结果、工具错误、模型每次重试、耗时、政策来源和申请 ID。

每次模型调用的 token 字段允许 null。对外的 token 总量仅在全部实际模型尝试都有 usage 时才提供，否则为 null，`usage_complete=false`。旧 agent_runs 的整型计数为了兼容保留，仅聚合已知数值，**不能作为完整用量来源**；API 使用 model_calls 计算。

无密钥时没有模型请求，不产生假的 ModelCall。离线 fixture 明确标识 `is_live=false`，LLM 调用数为 0。测试中模拟网络和 usage 的数据只存在临时数据库，不能据此声称真实 API 成本或效果。

不保存 DeepSeek 的 reasoning_content，不把密钥或 HTTP Authorization 写入 Trace；已知本地密钥、常见 sk- 形式及凭据字段做基础脱敏。这不是完整的 DLP 系统，避免在售后文本中输入真实凭据。LangGraph 调用位于 `tracing_context(enabled=False)`，不向 LangSmith 上传本地内容。

业务服务提交与工具 Trace 更新是两个事务，因此存在“业务已提交，Trace 未更新”的中断窗口。异常结束时按服务端幂等键查找已有工单/动作，回复真实的已保存状态。进程意外退出留下 RUNNING 时，管理员在超过运行预算 +60 秒后可调用 `/agent/runs/{id}/recover`，只做状态核对和收尾，不再调用模型或执行业务。中断调用标记 TRACE_INTERRUPTED，不能推断未知 token 用量。

## API

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | /agent/status | 配置是否齐全、模型名、预算，不返回密钥 |
| POST | /agent/runs | 开始或幂等查询一轮对话 |
| GET | /agent/runs/{id} | 同用户或管理员查看结果 |
| GET | /agent/runs/{id}/trace | 管理员查看模型与工具 Trace |
| POST | /agent/runs/{id}/recover | 管理员收尾过期 RUNNING |
| GET | /agent/policies/{id} | 当前版本政策来源 |

## 验证分层

- 旧 Stage 1–2 回归：确定性业务继续有效。
- Agent 工程单测：工具边界、会话归属、并发幂等、超时/重试、引用、真实状态回复、用量、恢复。
- 协议 mock：DeepSeek JSON 请求/响应、HTTP 错误、截断、非法 usage 和超时；不使用真实 API。
- 16 个脚本场景：验证 LangGraph 驱动预设工具计划后的业务结果，不衡量语言理解。
- 真实 Uvicorn HTTP：一套验证未配置降级，一套明确使用 scripted-fixture 验证工具链；都不访问 DeepSeek。
- `agent-evaluate --live`：配置后单独衡量真实模型的意图、工具选择和安全处理，当前尚未执行。

官方接口核对来源：[DeepSeek Tool Calls](https://api-docs.deepseek.com/guides/tool_calls/)、[DeepSeek Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)、[LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)。具体依赖以 requirements.lock 为准。
