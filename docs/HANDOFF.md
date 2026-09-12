# AfterSale Copilot — Stage 1 + Stage 2 验收与交接报告

> 这是 2026-09-08 的历史交接报告。2026-09-09 用户授权后已继续开发 Stage 3，最新状态见 [STAGE3_HANDOFF.md](STAGE3_HANDOFF.md)。verification 目录保存最近一次验收输出，可能包含后续阶段测试，不应将当前日志数量与此历史记录混淆。

验收日期：2026-09-08（北京时间）。项目路径：`D:\RAG-agent项目\after-sale-copilot`。

**结论：两阶段均已完成，96 项 pytest 全部通过，28 个政策黄金场景全部通过，24 次真实 HTTP 检查全部通过。已停止在 Stage 2，没有开发 LLM/Agent/完整前端。**

## 1. 授权范围与实际实施步骤

原始 prompt 仅要求 Stage 1；随后用户明确授权按修正版连续做到 Stage 2。本次按以下顺序完成：

1. 阅读原始需求，核对工作区，创建独立项目目录与 Python 虚拟环境，保留其他项目不变。
2. 明确人民币、单包裹、单商品项售后的 V1 边界；修正未支付订单实付金额语义。
3. 实现枚举、UTC、Decimal/整数分、集中配置、11 张表和数据库约束。
4. 实现 Store、基础业务服务、状态转移、Stage 1 REST API 与演示身份隔离。
5. 建立 10 用户/24 订单/48 商品项的逻辑一致 seed，首次 Stage 1 与金额测试 42 项通过。
6. 实现优惠分摊、部分退款尾差、版本化政策、风险判断、额度预留与幂等。
7. 实现人工审批、退货收货、模拟执行、失败保留预留并重试、业务快照和审计。
8. 加入黄金政策案例、接口测试、独立数据库连接并发测试与审计故障回滚测试。
9. 集成测试发现并修复金额 JSON 序列化影响 ORM 写入、审计字段与参数重名等问题；补强 SQLite 空值/外键约束。
10. 完成 96 项回归、28 个黄金案例、真实 Uvicorn HTTP 验证、PowerShell 高金额演示脚本实跑、lint/格式/依赖检查。
11. 初始化当前结构的干净演示数据库，导出 OpenAPI 和验证记录，完成文档与下一步开发计划。

初始化了独立 Git 仓库，尚未创建提交。`.venv`、`.env`、数据库、缓存等均被忽略。开发中的旧 seed 数据库保留为 `data/aftersale.schema-draft.db`，PowerShell 实跑使用单独的 `data/powershell-demo-test.db`；它们都不是默认业务数据库。

## 2. 最终目录

```text
after-sale-copilot/
├── .env.example
├── .gitignore
├── pyproject.toml
├── requirements.lock
├── README.md
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── cli.py
│   │   ├── evaluation.py
│   │   ├── api/             dependencies.py, routes.py
│   │   ├── core/            config.py, enums.py, errors.py, types.py
│   │   ├── db/              session.py, seed.py
│   │   ├── models/          entities.py
│   │   ├── schemas/         api.py
│   │   ├── repositories/    store.py
│   │   └── services/        business.py, calculator.py, policy.py, workflow.py
│   └── tests/
│       ├── conftest.py, helpers.py
│       ├── test_stage1.py
│       ├── test_calculator.py
│       ├── test_policy_boundaries.py
│       ├── test_workflow.py
│       ├── test_api.py
│       └── test_evaluation.py
├── data/                   本地 SQLite 数据，忽略版本控制
├── eval/
│   ├── cases.json
│   └── latest-report.json
├── scripts/
│   ├── start.ps1
│   ├── demo.ps1
│   ├── smoke_http.py
│   └── verify.py
└── docs/
    ├── HANDOFF.md
    ├── ARCHITECTURE.md
    ├── DATA_MODEL.md
    ├── POLICY.md
    ├── API.md
    ├── SCENARIOS.md
    ├── V1_ROADMAP.md
    ├── openapi.json
    └── verification/       summary.json、pytest.xml、各检查日志、http-smoke.json 等
```

目录树省略空的 `__init__.py`、虚拟环境、Git 内部目录和运行缓存。没有创建空的前端/Agent 功能占位目录。

## 3. 已实现功能与需求证据

| 需求 | 实现 | 主要验证 |
|---|---|---|
| 数据库初始化、原计划 9 表 | 原 9 表 + action_requests/audit_events | test_stage1 初始化、外键与枚举约束测试 |
| 查询用户/订单/商品/物流/退款/工单 | BusinessService + Store + Pydantic API | test_stage1、test_api |
| 创建工单、更新工单/退款状态 | 工单 API；退款内部 helper 与状态机 | 状态跳转、越权、无效字段测试 |
| seed 足量且自洽 | 10 用户、24 订单、48 商品项、19 物流、3 退款、3 工单 | seed 一致性、重复 seed、跨表合计测试 |
| Decimal 与 UTC | Money/UTCDateTime；JSON 字符串 | 原始 SQLite integer、金额精度、时区往返测试 |
| 未发货取消、已发货取消 | 取消退款或转物流调查 | 黄金案例与完整执行流程 |
| 无理由退货、破损、错发、少件 | 时间窗、证据、动作匹配、审批、收货门槛 | 黄金案例、退货/换货/少件流程 |
| 高金额与重复退款 | 阈值含边界、预留、历史退款、数量上限 | threshold 测试、并发提交和重复执行 |
| 信息不足 | NEED_MORE_INFO；补关联订单后新键重提 | 缺订单、缺商品、缺证据案例 |
| 人工审批与模拟执行 | 管理员端点；批准不等于执行 | API 403/409、审批重试、执行重验 |
| 事务原子性 | writer transaction 包含数据和审计 | 提交与执行两处故障注入回滚 |
| 可解释记录与 Evaluation | 命中规则/版本/快照/事件、28 个黄金案例 | eval/latest-report.json、审计链断言 |

没有自动向外发送消息，没有使用真实订单、真实支付或 LLM API Key。

## 4. 数据库关系

User 具有多个 Order 和 Ticket；Order 具有多个 OrderItem、Refund，最多一个 Shipment；Ticket 可以暂不关联 Order，关联后必须属于同一 User。Ticket 具有多个 ActionRequest；每个 ActionRequest 最多一个 Refund、一个 Approval，并具有多个 AuditEvent。预留的 AgentRun 可关联用户/订单/工单，并拥有多个 ToolCall。

组合外键进一步保证工单、动作、商品和订单的归属一致。数据库的行级 CHECK 与服务的跨记录余额规则共同工作。完整字段含义和关系见 [DATA_MODEL.md](DATA_MODEL.md)。

## 5. Seed 场景覆盖

覆盖 PAID 未发货、SHIPPED、签收 0–7 天、超 7 天、final_sale、不可无理由退商品、高金额商品、成功退款、处理中退款、物流异常、签收未收到、既有工单、待支付、已取消、质量问题及期限边界。

便于演示的入口：1001 低金额取消；1003 三件 100.00 元部分退款；1006 高金额取消审批；1009 物流异常；1010 签收未收到；1011 破损；1012 错发换货；1013 少件退款；1018 高金额退货；1023 七天边界。

完整订单、用户、商品 ID 对照见 [SCENARIOS.md](SCENARIOS.md)。所有默认业务数据保持未经过演示操作的 seed 状态；历史退款是 seed 的一部分。

## 6. API 与关键调用链

22 个 API 操作均有响应 schema 和统一错误契约，完整列表见 [API.md](API.md)；机器契约见 [openapi.json](openapi.json)。

关键路径：

- 查询：route → 演示身份/归属 → BusinessService → Store → SQLAlchemy → SQLite。
- 申请：route → ActionCreate → WorkflowService.submit → 写事务 → 幂等检查 → 当前数据 → PolicyEngine/Calculator/RiskEngine → 预留/审批/审计 → 提交。
- 审批：管理员 → 重验政策/当前状态 → 审批决策 → READY 或 WAITING_RETURN → 审计。
- 执行：管理员 → 状态/审批/收货门槛 → 再校验 → 模拟业务变更 + 审计原子提交。

每个核心文件的作用见 [ARCHITECTURE.md](ARCHITECTURE.md) 的逐文件表。

## 7. 实际验收结果

环境：Windows 11、Python 3.13.5，依赖版本锁定于 requirements.lock。最终自动验收记录时间为 2026-09-08 23:30（北京时间），随后补充了 PowerShell 脚本实跑。

| 检查 | 结果 | 保存证据 |
|---|---|---|
| pytest | **96 passed，0 failed，0 errors**；pytest 报告约 33.63 秒 | verification/pytest.txt、pytest.xml |
| 基础数据/服务测试 | 37 项 | test_stage1.py |
| 金额计算测试 | 7 项 | test_calculator.py |
| 金额阈值边界测试 | 3 项 | test_policy_boundaries.py |
| 工作流/并发/回滚测试 | 23 项 | test_workflow.py |
| API 测试 | 25 项 | test_api.py |
| 黄金评测集集成测试 | 1 项，内部运行 28 个案例 | test_evaluation.py |
| 独立政策评测 | **28/28**，LLM 调用为 0 | ../eval/latest-report.json |
| 真实 HTTP 冒烟 | **24 次检查通过**，真实 Uvicorn，隔离数据库 | verification/http-smoke.json |
| PowerShell 高金额演示 | REQUIRE_APPROVAL → APPROVED → SUCCESS；订单 CANCELLED | verification/powershell-demo.txt |
| Ruff 检查与格式检查 | 通过 | verification/ruff-check.txt、ruff-format.txt |
| pip check | 无依赖冲突 | verification/pip-check.txt |
| 当前演示数据库一致性 | 通过 | `python -m app.cli check-data` |

存在两条未屏蔽的第三方弃用提示：Starlette TestClient 的 httpx 兼容层与 AnyIO BlockingPortal 别名。它们未影响本次测试结果；后续升级依赖时一并处理。96 项测试与 28 个规则场景并非完全互不重叠，表中已明确评测集集成测试的关系，不将其相加宣传为独立测试数量。

这些测试证明本机模拟范围内的行为；没有进行生产负载测试、真实支付验收或模型准确率测试。

一键重跑自动验收：

```powershell
Set-Location 'D:\RAG-agent项目\after-sale-copilot'
.\.venv\Scripts\python.exe scripts/verify.py
```

## 8. 启动与手动验收

本机已装好依赖并准备数据库。运行 `scripts/start.ps1`，然后访问 `http://127.0.0.1:8000/docs`。没有给项目留下长期运行的后台服务；测试服务器均已关闭。

按下列顺序验证：

1. GET /health 返回 ok / simulation。
2. 设置 X-Demo-User-Id: 1，查询订单 1001，实付字符串为 112.97；订单 1002 属于另一用户，应返回 403。
3. 为订单 1001 创建 CANCEL 工单，提交 CANCEL_AND_REFUND。检查 READY、final_action=null；管理员模拟执行后订单 CANCELLED、退款 SUCCESS。
4. 运行 `scripts/demo.ps1` 验证订单 1006 高金额审批链。它会修改默认演示数据库，重复运行已完成订单时只查询历史结果。
5. 用户 3 对商品 10031 创建无理由退货申请，数量 1。直接执行应 409；管理员 return-receipt 后才可以成功退款 33.33。
6. 查询审计，查看政策版本、规则代码、证据快照和实际执行结果。
7. 运行 evaluate 和 pytest，检查报告和退出码。

完整 PowerShell 请求示例、从零安装和另建数据库方法见 [README](../README.md)。

## 9. 与原计划的差异和理由

- **做到 Stage 2**：来自后续用户明确授权，覆盖原文 Stage 1 停止要求。
- **Python 下限 3.11**：使用标准库 StrEnum，减少枚举兼容代码；实际验证 3.13.5，未声称验证所有 3.11+ 环境。
- **11 张表而不是仅 9 张**：追加动作申请与审计两表，避免把确定性流程伪装为 Agent Trace。
- **多增加 authorized_action/decision/execution_status**：分离建议、许可和实际效果；final_action 仅成功后填写。
- **未支付订单 paid_amount=0**：原价减优惠是应付金额，不等于已支付事实。
- **SQLite 金额存整数分**：服务与 ORM 仍使用 Decimal，JSON 使用字符串；保证货币路径不经 float。
- **增加 REFUND_MISSING_ITEM**：少件退款不能要求退回未收到的商品。
- **FAILED 保留预留可重试**：避免失败后释放额度造成重复退款与已退回商品二次计数。
- **Stage 2 增加模拟执行 API**：是授权闭环的一部分，无法传任意金额，且受管理员/政策/审批/收货约束，不是原文禁止的 Stage 1 裸自动退款接口。
- **增加演示角色隔离**：仅本机请求头模拟身份，真实权限系统仍未实现。
- **无前端空壳、无 Alembic**：界面和迁移尚无必要，保持学习路径清楚；未来需要保留旧数据演进时必须补迁移。

## 10. 已知限制

1. 没有 LLM、Agent 工具、RAG、Customer Portal 或 Admin Console；Swagger 只用于调试。
2. 演示角色由本地请求头声明，不是生产认证；仅支持 loopback，不能部署到公网使用。
3. 仅人民币、单包裹、整单取消/单商品项售后；没有运费、税费、复杂优惠、真实库存和真实换货物流。
4. 证据仅存在标记与人工备注；没有图片/附件留存或自动视觉判断。
5. SQLite 写事务串行；已验证两独立连接竞争，未做高并发性能承诺。
6. 没有申请撤回、超时释放和退货质检拒收流程；失败通过原申请重试。
7. 创建工单本身没有幂等，Agent 接入前应补；动作申请和执行已有幂等。
8. 历史 seed 的处理中退款仅用于查询与额度演示，不能直接调用 Stage 2 执行入口。
9. 审计无公开修改接口，但不是数据库管理员不可篡改的日志。
10. init-db 不迁移旧结构；政策版本变化会使待执行授权失效，不自动迁移审批。

## 11. 下一步开发计划

Stage 2 原建议均已落地；下一步是 **Stage 3 单 Agent + 受限 Tools + 小规模政策检索 + 真实 Trace**。优先补创建工单幂等与可信身份上下文，再把现有查询和申请服务包装成工具。模型不可访问管理员审批、仓库确认或执行工具。

随后建立自然语言案例、错误工具结果、超时、越权与提示注入的评测，确保接入模型后仍不破坏当前确定性边界。Stage 4 才实现客户与管理界面及真实登录；Stage 5 扩展评测、性能与作品集材料。详细顺序与验收条件见 [V1_ROADMAP.md](V1_ROADMAP.md)。

## 12. 推荐阅读代码顺序

1. README + SCENARIOS：先知道系统能演示什么。
2. core/enums.py + schemas/api.py：理解四类状态和输入/输出。
3. core/types.py + models/entities.py：理解金额、时间和约束。
4. db/seed.py：把抽象字段对应到具体订单。
5. repositories/store.py + services/business.py：理解查询和事务分层。
6. services/calculator.py + services/policy.py：先读纯计算和规则函数。
7. services/workflow.py：串起申请、审批、收货、执行。
8. tests/test_workflow.py + test_api.py：通过失败和并发案例理解设计理由。
9. eval/cases.json + evaluation.py：理解如何判定业务结果正确。
10. main.py + api/routes.py：最后看应用装配与 HTTP 映射。

## 13. 面试最值得讲的 5 个工程决策

**第一，建议与执行分离。** 调用者建议取消，但订单已经发货时政策会改为物流调查；人工审批通过也只是获得执行许可。展示 ActionRequest 四个字段以及签收未收到案例，比只说“LLM 不可靠”更具体。

**第二，金额精度是端到端契约。** Python Decimal 不足以自动保证 SQLite 存储精度，所以数据库存整数分、API 输出字符串；用三件 100 元分次退 33.33/33.33/33.34 证明金额守恒。

**第三，幂等不能替代并发保护。** 相同键重试由唯一约束与载荷指纹处理；不同键竞争同一订单依靠事务内读余额与预留。两独立 engine 的并发测试验证只生成一笔退款。

**第四，审批不能覆盖硬规则。** 申请时符合未发货退款，批准前实际已发货，原授权必须失效；后续操作重新读取当前状态，同时保留申请时间以免审批延迟侵害申请窗口。

**第五，审计与业务结果原子提交，并从模型接入前就评测。** 审计写入失败不能出现已退款但没有记录；用故障注入证明回滚。先有黄金业务结果，后续才可以判断 Agent 是否正确使用工具和遵循规则。

本报告交付后停止本轮开发，等待下一次对 Stage 3 的明确安排。
