# 架构与实现边界

本页主要解释 Stage 1–2 的确定性业务核心；当前已增加 Stage 3，详见 [STAGE3.md](STAGE3.md)。下文原本为 Agent 预留的表现在由运行时实际写入，完整前端和真实身份认证仍未实现。

## 当前系统

单进程或多个本地 worker 共用 SQLite 的模块化后端。HTTP 入口调用业务服务，服务通过 Store 操作数据库。PolicyEngine / RiskEngine / RefundCalculator 只负责确定性判断和计算。

Stage 1 与 Stage 2 在同一工程中分层实现，最终交付是两阶段合并版本；没有维护一个单独的 Stage 1 老版本分支。

## 核心文件

| 文件 | 作用 |
|---|---|
| `backend/app/main.py` | 应用工厂、依赖装配、请求编号、结构化错误与日志；不自动 seed |
| `backend/app/api/routes.py` | REST 路由、Pydantic 响应和演示访问边界 |
| `backend/app/api/dependencies.py` | 本机限制、演示角色、可选令牌与对象归属检查 |
| `backend/app/core/config.py` | 集中配置、项目路径和环境变量 |
| `backend/app/core/enums.py` | 订单、工单、退款、动作、策略、风险、审批、执行等枚举 |
| `backend/app/core/types.py` | Decimal 与整数分转换、UTC 数据库存取适配 |
| `backend/app/core/errors.py` | 与 HTTP 可映射的领域错误 |
| `backend/app/models/entities.py` | 11 张表与外键、唯一、CHECK、索引定义 |
| `backend/app/schemas/api.py` | 请求/响应契约，禁止额外字段和客户端注入金额 |
| `backend/app/repositories/store.py` | SQL 查询和 flush；不自行 commit |
| `backend/app/services/business.py` | 基础查询、工单服务、内部退款记录创建、状态转移约束 |
| `backend/app/services/calculator.py` | 优惠分摊、剩余额度与部分退款分币计算 |
| `backend/app/services/policy.py` | 纯规则判断和风险判断，版本化模拟政策 |
| `backend/app/services/workflow.py` | 申请、审批、收货、模拟执行与审计的事务编排 |
| `backend/app/db/session.py` | SQLite 连接配置、建表、会话、写事务 |
| `backend/app/db/seed.py` | 可复现 seed 与跨表一致性验证 |
| `backend/app/cli.py` | 初始化、seed、检查数据、场景索引、运行评测 |
| `backend/app/evaluation.py` | 在临时数据库运行独立黄金案例，生成 JSON 报告 |
| `scripts/start.ps1` | 本机服务启动入口 |
| `scripts/demo.ps1` | 对演示数据库运行高金额审批退款流程 |
| `scripts/smoke_http.py` | 隔离数据库上的真实 HTTP 全链路检查 |

## 调用链

**查询订单**：`GET /orders/{id}` → `principal/require_owner` → `BusinessService.get_order` → `Store.get` → SQLAlchemy → SQLite → `OrderRead`。

**提交申请**：`POST /actions` → `ActionCreate` → 归属检查 → `WorkflowService.submit` → `write_transaction` → 幂等检查 → 读取当前订单/物流/占用额度 → `PolicyEngine.evaluate` → `RefundCalculator` + `RiskEngine` → 保存 ActionRequest → 创建退款预留/审批 → 写 AuditEvent → 一次提交。

**审批**：管理员路由 → `WorkflowService.review` → 读取当前申请和审批 → 重新校验政策/额度/状态 → 审批通过并进入 READY/WAITING_RETURN，或拒绝并释放预留 → 保存审计 → 提交。

**模拟执行**：管理员路由 → 检查状态、审批和退货收货 → 再校验政策 → 在同一事务内更新模拟退款/订单/工单/执行结果和审计。没有调用真实支付工具。

## 事务与并发

SQLite 默认的“先查询，再写入”可能让两个请求同时看到同一余额。写服务使用 `BEGIN IMMEDIATE` 在读取余额之前拿到数据库写锁，连接配置 `busy_timeout=15000`。并发请求排队重新读取最新余额；超时返回 503，而不绕过约束。

所有写操作走同一种事务边界，repository 只 flush。两项故障注入测试分别在“创建申请后写审计”及“更新退款成功后写审计”失败，验证整个事务回滚。

此方案适合单机演示，不是生产高吞吐支付架构。迁移 PostgreSQL 时，必须重新实现并验证行锁/条件更新策略；不能直接沿用 SQLite 的 BEGIN IMMEDIATE。

## 幂等与余额

- `(user_id, idempotency_key)` 唯一；规范化请求 JSON 的 SHA-256 保证同键异参返回 409。
- 同键同参返回已有申请，即使动作已成功；修改信息需要新幂等键。
- 一个申请最多关联一条退款和一条审批。
- 退款 `PENDING/APPROVED/PROCESSING/SUCCESS/FAILED` 均计入已占用额度。FAILED 在此版本表示可重试的模拟失败，不能释放后再创建另一笔退款。
- 换货用 ActionRequest 的数量预留，不能以“换货无退款记录”为由重复售后同一数量。
- `REJECTED` 释放预留；成功记录持续占用，避免重复赔付。
- 每个工单最多一个未完成动作；跨工单仍根据订单及商品余额控制。

## 时间、政策和证据

Python 只接受 aware datetime，SQLite 持久化去时区的 UTC，读出恢复 UTC。API 输出带 `Z` 的 ISO 时间。

申请期限以 `ActionRequest.created_at` 判断；后续审批和仓库延误不消耗用户申请期限。每次后续操作仍读取当前订单状态和余额。政策版本编码规则修订号、时间窗口和金额阈值；配置变化或重新计算结果变化将使旧授权失效。

`evidence_provided` 只是演示“已提供证据”这一事实，不声称验证过图片。质量问题无论金额大小都会经过人工审批。审批记录保存处理者、理由和时间。

## Trace 与审计

当前 `audit_events` 保存政策命中规则、输入快照、重新校验结果、审批理由、收货及模拟执行结果。表通过公开 API 只读，不提供修改或删除接口；它不是防篡改账本，数据库管理员仍可直接改库。

`agent_runs/tool_calls` 仅保留 schema，seed 和业务流程都不会伪造 LLM 调用、token 或工具 Trace。Stage 3 接入时再补运行时间线与真实工具记录。

## 刻意省略

没有通用抽象 repository 接口、消息队列、分布式锁、异步 ORM、多 Agent、MCP、Memory、向量数据库或完整前端。当前流程由结构化 API 驱动；后续 Agent 通过受限工具使用相同的服务边界。
