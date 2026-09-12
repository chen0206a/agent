# AfterSale Copilot

电商售后 Web 产品：客户查询订单、物流和售后进度，通过单 Agent 发起申请；管理员核验政策、审批、确认退货收货、模拟执行并查看运行轨迹。

当前完成 **Stage 1–5**，本轮已停止开发。Stage 5 冻结 Test 单次真实 DeepSeek 评测 **46/50（92%）**，详见 [评测报告](docs/STAGE5_EVALUATION.md)、[失败分析](docs/STAGE5_FAILURE_ANALYSIS.md)、[作品集](docs/STAGE5_PORTFOLIO.md) 和 [简历指标](docs/RESUME_METRICS.md)。页面与鉴权交接见 [STAGE4_HANDOFF.md](docs/STAGE4_HANDOFF.md)，路线见 [V1_ROADMAP.md](docs/V1_ROADMAP.md)。

所有订单、物流和退款为本地模拟业务。申请通过、管理员批准与退款成功是不同阶段；仅管理员能模拟执行。金额与政策由后端确定，Agent 无审批或执行权限。

## 本机启动

现有 `.env`、`.venv`、数据库和前端生产构建已保留。首次使用需要您在本机设置登录密码，没有预置通用密码。

```powershell
Set-Location 'D:\RAG-agent项目\after-sale-copilot'
.\.venv\Scripts\python.exe scripts/setup_accounts.py
```

默认依次设置 `customer1`、`customer3`、`customer4`、`customer6`、`customer10` 和 `admin` 的独立密码，长度 12–128 个字符；输入不回显，只保存加盐哈希。再次执行保留已有账号。可用 `--user-id 1 2` 指定需要开通的客户。必须先有相应模拟业务用户，不提供公共注册入口。

然后打开两个 PowerShell 终端：

```powershell
# 终端 1：FastAPI
Set-Location 'D:\RAG-agent项目\after-sale-copilot'
.\scripts\start.ps1
```

```powershell
# 终端 2：Next.js
Set-Location 'D:\RAG-agent项目\after-sale-copilot'
.\scripts\start_frontend.ps1
```

打开 **http://127.0.0.1:3000**，使用刚设置的账号登录。管理员自动进入运营工作台。两个终端各按 Ctrl+C 停止对应服务。

脚本若受系统执行策略限制，可分别直接执行 `.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers` 和在 `frontend` 中执行 `npm run start`，无需改全局策略。

后端文档：http://127.0.0.1:8000/docs；健康检查：http://127.0.0.1:8000/health。业务 API 必须真实登录；原 `X-Demo-User-Id` / `X-Demo-Role` / `X-Demo-Token` 不再是认证入口。

## 从零安装或更新构建

验证环境：Windows 11、Python 3.13.5、Node.js 24.15.0、npm 11.12.1。建议沿用此组合；依赖版本由两个 lock 文件固定。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m app.cli init-db
.\.venv\Scripts\python.exe -m app.cli seed
.\.venv\Scripts\python.exe scripts/setup_accounts.py
Set-Location frontend
$env:npm_config_cache = "$env:LOCALAPPDATA\npm-cache"
npm ci
npm run build
```

首次安装将 `.env.example` 复制为 `.env`；已有配置不要覆盖。旧数据库升级可以运行 `scripts/upgrade_stage4.py`：先备份，再增量建表并校验原记录不变。本机日常数据库已完成此步骤。

## 模型与身份配置

在项目根目录 `.env` 设置 `ASC_LLM_BASE_URL`、`ASC_LLM_MODEL`、`ASC_LLM_API_KEY`。密钥仅后端读取，不放入任何 `NEXT_PUBLIC_*` 变量。修改后重启后端。未配置模型会明确返回不可用结果，不伪装成智能客服。

前端通过同源 `/api/*` 代理请求 FastAPI，后端地址默认 `http://127.0.0.1:8000`；需要改变时配置 Next.js 运行环境 `BACKEND_URL`。`ASC_FRONTEND_ORIGINS` 控制允许的浏览器来源。当前服务只绑定本机，HTTP 下 `ASC_COOKIE_SECURE=false`；对外部署需另行完成 HTTPS 与部署加固，本轮未部署。

账户采用 scrypt 密码哈希，12 小时随机服务端会话，HttpOnly / SameSite=Strict Cookie，写操作校验 CSRF 和来源。用户归属及 admin 权限由后端判断。Trace 仅管理员可见，HTTP 输出过滤 system 消息及 reasoning_content。

## PowerShell API 使用

```powershell
$auth = .\scripts\login.ps1
.\scripts\chat.ps1 -Session $auth.Session -CsrfToken $auth.CsrfToken `
  -OrderId 1001 -Message '请取消订单1001并退款' -OutputPath .\data\chat.json
# Trace 需要另行使用 admin 登录
$admin = .\scripts\login.ps1
.\scripts\trace.ps1 -Session $admin.Session -RunId 2 -OutputPath .\data\run-2-trace.json
```

脚本显式使用 UTF-8 解码和保存 JSON，兼容 Windows PowerShell 5.1。续聊添加 `-ParentRunId`；同一次不确定请求重试应复用 `-IdempotencyKey`。`scripts/demo.ps1` 会分别提示登录 customer6 和 admin，再演示高额申请及模拟执行。

## 验证与类型生成

```powershell
.\.venv\Scripts\python.exe scripts/verify.py
.\.venv\Scripts\python.exe scripts/export_openapi.py
Set-Location frontend
npm run generate:api
npm run test
npm run lint
npm run build
npx playwright install chromium
Set-Location ..
.\.venv\Scripts\python.exe scripts/run_stage4_e2e.py
```

Stage 5 完成时，后端 173 项测试、前端 5 项测试和 8 项浏览器 E2E 均通过；另有 28 个政策案例、16 个离线 Agent 案例及两组 HTTP 冒烟。浏览器脚本临时创建数据库，在 8014/3810 启动测试服务，结束后停止服务；脚本模型标识 `NOT-A-REAL-MODEL`，不读取日常 API 密钥，也不改日常订单。它验证产品集成，不代表模型理解能力。

最新评测与回归证据：[docs/verification/stage5](docs/verification/stage5)；Stage 4 页面截图与原验收证据：[docs/verification/stage4](docs/verification/stage4)。接口契约变动后同时更新 `frontend/openapi.json` 与 `frontend/src/lib/generated.ts`。

Stage 5 已完成 125 条合成场景评测（Dev 75 / Test 50），采用第一轮 Dev 优化版本，最终冻结 Test 仅正式运行一次，46/50 通过。完整失败、模型身份、配置与数据集 hash、Token 和费用记录均已保留；不要重跑旧 Test 来替换正式成绩。

## 代码入口

- `backend/app/api/`：业务路由、真实鉴权依赖、Auth 与 Portal 接口。
- `backend/app/services/`：已有政策、金额、工作流，以及新增账户/门户服务。
- `backend/app/repositories/` / `models/`：数据库访问与约束。
- `backend/app/agent/`：单 Agent、受限工具、模型适配、政策检索；Stage 5 优化了 Prompt 与工具说明，保留业务授权和金额计算边界。
- `frontend/src/components/`：登录与应用框架、客户门户、管理员工作台、shadcn Button。
- `frontend/src/app/`：页面路由与同源 API 代理；`frontend/e2e/`：浏览器测试。

- `eval/stage5/`：冻结的 Dev/Test 数据集与 manifest。
- `scripts/stage5.py`：隔离评测、评分与调用账本；`docs/verification/stage5/`：版本快照、完整轨迹与实测结果。

页面与鉴权设计见 [Stage 4 交接报告](docs/STAGE4_HANDOFF.md)。Stage 5 已完成，指标口径与测试边界见 [评测报告](docs/STAGE5_EVALUATION.md) 和 [失败分析](docs/STAGE5_FAILURE_ANALYSIS.md)，推荐演示与阅读顺序见 [作品集](docs/STAGE5_PORTFOLIO.md)，简历表述见 [实测指标](docs/RESUME_METRICS.md)。
