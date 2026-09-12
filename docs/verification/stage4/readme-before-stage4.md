# AfterSale Copilot

用于学习与面试展示的电商售后系统。当前包含 **Stage 1 数据基础、Stage 2 确定性售后闭环、Stage 3 单 Agent 与 Stage 3.5 真实模型验收**。Stage 3.5 已完成同样 5 个 DeepSeek 场景的优化前后对照，优化后 5/5 通过；152 项测试通过。当前停止在 Stage 3.5，未进入 Stage 4。

最新结果、失败分析、配置版本与完整轨迹见 [STAGE3_5_HANDOFF.md](docs/STAGE3_5_HANDOFF.md)。这些是代表性场景结果，不是生产成功率。

可以查询订单/物流、创建工单、计算可退金额、检查政策、人工审批、确认退货收货、模拟执行，并查看审计记录。新增 LangGraph 单 Agent、DeepSeek tool-calling 接口、6 篇版本化政策检索、会话补问、受限工具与本地 Trace。**未配置模型时不会调用外部模型，也不会伪装成智能对话**。当前没有完整前端，Swagger 是接口调试界面。

所有用户、商品、物流、退款都是本地模拟数据。服务不接支付、电商账号或外部业务 API；配置后会把必要的对话和工具上下文发送至指定 DeepSeek 接口。Trace 保存在本地，禁用 LangSmith 自动上传。

## Stage 3 使用入口

将 `.env.example` 复制为本地 `.env`（不要覆盖已有配置），填写以下两项：

```dotenv
ASC_LLM_BASE_URL=https://api.deepseek.com
ASC_LLM_MODEL=你的工具调用模型名
ASC_LLM_API_KEY=你的本地密钥
```

本轮验收使用 DeepSeek 的 `deepseek-v4-flash`，模型名通过配置读取。修改 `.env` 或更新 Agent 代码后重启服务。运行 `GET /agent/status` 可检查配置是否齐全，此接口不回显密钥。

```powershell
$headers = @{ 'X-Demo-User-Id'='1' }
$body = @{ message='Cancel my order 1001 and request a refund'; order_id=1001; idempotency_key='chat-cancel-1001' } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/agent/runs' `
  -Headers $headers -ContentType 'application/json' -Body $body
```

模型未配置时返回带 run_id 的 `MODEL_NOT_CONFIGURED`，用量未知为 null，LLM 调用为 0。续聊时传前一轮 `parent_run_id` 和新的幂等键，历史从服务端按所属用户加载。结构化 `order_id` 为可选的明确订单范围，证据存在标记 `evidence_provided` 由调用方提交，不能由模型伪造。

Agent 只能查询、检索、创建工单及提交建议。成功申请不等于退款到账；审批、收货、执行仍由管理员流程完成。业务答复按已验证结果生成，模型的自由文本不能宣称退款成功。

离线检查：`python -m app.cli agent-evaluate --output eval/agent-offline-report.json`。这里使用预设工具计划测试编排，**不是自然语言理解准确率**。完整 16 个真实场景命令 `python -m app.cli agent-evaluate --live --output eval/agent-live-report.json` 会产生 API 费用，本轮未执行。Stage 3.5 的 10 次真实运行结果已保存，无需重新收费复跑。

PowerShell 中文聊天使用 `scripts/chat.ps1`，可加 `-OutputPath` 保存 UTF-8 JSON。只读导出日常服务的 Trace：

```powershell
.\scripts\trace.ps1 -RunId 2 -OutputPath .\data\run-2-trace.json
```

如启用了演示访问令牌，附加 `-DemoToken`。实验库中的 run_id 与日常库独立，实验轨迹请阅读验收报告中的文件链接。

完整设计与限制见 [STAGE3.md](docs/STAGE3.md)，交接报告见 [STAGE3_HANDOFF.md](docs/STAGE3_HANDOFF.md)。

## 快速启动（Windows PowerShell）

本机已经准备了 `.venv` 和演示数据库。进入项目后运行：

```powershell
Set-Location 'D:\RAG-agent项目\after-sale-copilot'
.\scripts\start.ps1
```

服务启动在 <http://127.0.0.1:8000>；接口文档 <http://127.0.0.1:8000/docs>；健康检查 <http://127.0.0.1:8000/health>。在启动终端按 Ctrl+C 停止。脚本会补建缺失表并在空库 seed，已有数据不重置。若本机执行策略不允许运行脚本，使用下面的 Python 命令即可，无需修改系统执行策略。

### 从零安装

使用 Python 3.11+；本次实际验证环境为 Windows / Python 3.13.5。

```powershell
Set-Location 'D:\RAG-agent项目\after-sale-copilot'
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
```

`requirements.lock` 固定了本次验证过的运行与开发依赖；`pyproject.toml` 描述项目本身。需要更新依赖时使用 `pip install -e '.[dev]'`，重新验证后再更新锁定文件。

### 配置、初始化与运行

配置文件模板是 `.env.example`，默认值已足够运行。需要修改配置时将其复制为 `.env`；不要覆盖自己已有的 `.env`。真实 `.env` 已加入 `.gitignore`。

```powershell
.\.venv\Scripts\python.exe -m app.cli init-db
.\.venv\Scripts\python.exe -m app.cli seed
.\.venv\Scripts\python.exe -m app.cli check-data
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

默认数据库为项目根目录下 `data/aftersale.db`。以 `sqlite:///./` 开头的配置路径按项目根目录解析；切换终端目录不会创建另一个数据库。初始化不会修改已有表结构；本阶段不提供数据库迁移。演进现有数据库前先做备份并引入 Alembic。

如需另建一套演示数据，使用新的文件名，不必删除现有数据库：

```powershell
$env:ASC_DATABASE_URL = 'sqlite:///./data/demo2.db'
.\.venv\Scripts\python.exe -m app.cli init-db
.\.venv\Scripts\python.exe -m app.cli seed
```

seed 包含 **10 用户、24 订单、48 商品项、19 物流记录、3 历史退款和 3 已有工单**。默认按初始化时刻生成相对时间；测试和评测使用固定 UTC 时刻。使用 `seed --at '2026-09-08T12:00:00+00:00'` 可复现固定时间。重复 seed 在存在用户时直接跳过，不合并、不清库。

## 演示身份与接口示例

业务接口只接受 loopback 连接，`--no-proxy-headers` 避免把代理头当作客户端地址。以下请求头**模拟身份**，不构成生产身份认证：

- 客户：`X-Demo-User-Id: 1`；默认 `X-Demo-Role: customer`。
- 管理员：`X-Demo-Role: admin`，可选 `X-Demo-Reviewer: alice`。
- 若设置了 `ASC_DEMO_API_TOKEN`，还必须传 `X-Demo-Token`。

客户只能访问自己名下的数据；审批、仓库收货、模拟执行、审计明细需要管理员角色。不要将这一演示接口代理到公网；真实登录与权限系统是 Stage 4 的前置工作。

```powershell
$customerHeaders = @{ 'X-Demo-User-Id' = '1' }
Invoke-RestMethod 'http://127.0.0.1:8000/orders/1001' -Headers $customerHeaders
Invoke-RestMethod 'http://127.0.0.1:8000/orders/1001/items' -Headers $customerHeaders

$body = @{ user_id=1; order_id=1001; issue_type='CANCEL'; description='Cancel my order' } | ConvertTo-Json
$ticket = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/tickets' `
  -Headers $customerHeaders -ContentType 'application/json' -Body $body

$request = @{ ticket_id=$ticket.id; proposed_action='CANCEL_AND_REFUND'; idempotency_key="readme-$($ticket.id)" } | ConvertTo-Json
$action = Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/actions' `
  -Headers $customerHeaders -ContentType 'application/json' -Body $request
$action
```

低金额取消会返回 `decision=ALLOW`、`execution_status=READY` 和 `amount="112.97"`。这一步只授权并预留额度，`final_action` 仍为空。模拟执行需显式调用：

```powershell
$adminHeaders = @{ 'X-Demo-Role'='admin'; 'X-Demo-Reviewer'='local-reviewer' }
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/actions/$($action.id)/simulate-execution" `
  -Headers $adminHeaders -ContentType 'application/json' -Body '{}'
```

所有金额响应为人民币两位小数字符串；客户端不能提交退款金额、政策结果或最终执行状态。完整接口列表见 [API.md](docs/API.md)。

### 高金额审批完整演示

保持服务运行，在另一个 PowerShell 终端运行：

```powershell
.\scripts\demo.ps1
```

脚本对订单 1006 执行“创建工单 → 申请 → 高金额审批 → 模拟退款 → 展示审计”。会修改演示数据库；订单已经取消时只展示历史结果。设置了演示令牌时使用 `-DemoToken '你的本地令牌'`。

## 测试与规则评测

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check backend scripts
.\.venv\Scripts\python.exe -m ruff format --check backend scripts
.\.venv\Scripts\python.exe -m app.cli evaluate --output eval/latest-report.json
.\.venv\Scripts\python.exe scripts/smoke_http.py
```

pytest、政策评测和真实 HTTP 冒烟脚本都使用隔离临时数据库，不改变演示数据。冒烟脚本自动启动、验证、关闭自己的 Uvicorn 子进程。评测退出码非零表示存在失败；预期答案保存在 `eval/cases.json`，不能通过改答案掩盖实现错误。

依赖本身目前产生一条 AnyIO BlockingPortal 别名弃用提示，没有关闭或过滤。历史 Stage 1–2 结果见 [HANDOFF.md](docs/HANDOFF.md)，最新结果见 [Stage 3 报告](docs/STAGE3_HANDOFF.md)。

## 核心设计

1. **建议、授权、执行分离**：`proposed_action` 是调用者建议；`authorized_action` 是政策允许的动作；`decision` 是政策结论；`final_action` 仅在模拟执行成功后填写。
2. **金额守恒**：Python Decimal、SQLite 整数分、JSON 字符串；优惠按最大余数法分摊；最后一批部分退款补齐分币尾差。
3. **服务拥有事务**：检查余额、预留额度、创建审批、写审计原子提交。SQLite `BEGIN IMMEDIATE` 在查余额前获得写锁。
4. **审批不越过硬规则**：审批、收货、执行时再次检查现有状态和额度；政策版本或结果改变使原授权失效。
5. **可复现**：固定场景 ID、可注入时钟、黄金规则案例、独立并发连接测试、真实 HTTP 验证。

无理由退货 7×24 小时、质量售后 30×24 小时、金额 ≥1000 元人工审批，均为**可配置的模拟商家规则**。这些设定不是对真实平台条款或法定消费者权益的判断。

## 阅读与后续

- [验收与交接报告](docs/HANDOFF.md)：实施步骤、验证证据、差异、目录与面试工程决策。
- [架构说明](docs/ARCHITECTURE.md)：调用链、边界、事务与授权。
- [数据模型](docs/DATA_MODEL.md)：原 11 张表和 Stage 3 新增的 3 张表。
- [政策说明](docs/POLICY.md)：业务规则、状态转移和限制。
- [场景索引](docs/SCENARIOS.md)：固定订单/用户/商品 ID。
- [开发路线](docs/V1_ROADMAP.md)：Stage 3–5 的交付与验收条件。

当前范围限定为人民币、单订单单包裹、整单取消或单商品项售后。不包含真实库存/换货物流、图片上传、运费税费、复杂促销、自动到期释放、真实身份认证或生产部署；这些业务边界不会因接入 Agent 改变。
