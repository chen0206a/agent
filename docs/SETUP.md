# 安装、配置与验证

[返回项目首页](../README.md)

以下命令均在克隆后的项目根目录执行，进入 frontend 的步骤除外。

## 本机启动

完成“从零安装或更新构建”步骤后，在项目根目录设置登录账号。密码由使用者自行设置，没有预置通用密码。

```powershell
# 在克隆后的项目根目录执行
.\.venv\Scripts\python.exe scripts/setup_accounts.py
```

默认依次设置 `customer1`、`customer3`、`customer4`、`customer6`、`customer10` 和 `admin` 的独立密码，长度 12–128 个字符；输入不回显，只保存加盐哈希。再次执行保留已有账号。可用 `--user-id 1 2` 指定需要开通的客户。必须先有相应模拟业务用户，不提供公共注册入口。

然后打开两个 PowerShell 终端：

```powershell
# 终端 1：FastAPI
# 在克隆后的项目根目录执行
.\scripts\start.ps1
```

```powershell
# 终端 2：Next.js
# 在克隆后的项目根目录执行
.\scripts\start_frontend.ps1
```

打开 **http://127.0.0.1:3000**，使用刚设置的账号登录。管理员自动进入运营工作台。两个终端各按 Ctrl+C 停止对应服务。

脚本若受系统执行策略限制，可分别直接执行 `.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers` 和在 `frontend` 中执行 `npm run start`，无需改全局策略。

后端文档：http://127.0.0.1:8000/docs；健康检查：http://127.0.0.1:8000/health。业务 API 通过服务端登录会话鉴权。

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

首次安装将 `.env.example` 复制为 `.env`；已有配置不要覆盖。旧数据库升级可以运行 `scripts/upgrade_stage4.py`：先备份，再增量建表并校验原记录不变。

## 模型与身份配置

在项目根目录 `.env` 设置 `ASC_LLM_BASE_URL`、`ASC_LLM_MODEL`、`ASC_LLM_API_KEY`。密钥仅后端读取，不放入任何 `NEXT_PUBLIC_*` 变量。修改后重启后端。未配置模型会明确返回不可用结果。

前端通过同源 `/api/*` 代理请求 FastAPI，后端地址默认 `http://127.0.0.1:8000`；需要改变时配置 Next.js 运行环境 `BACKEND_URL`。`ASC_FRONTEND_ORIGINS` 控制允许的浏览器来源。当前服务只绑定本机，HTTP 下 `ASC_COOKIE_SECURE=false`；对外部署需另行完成 HTTPS 与部署加固。

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

已记录的回归结果：后端 173 项测试、前端 5 项测试和 8 项浏览器 E2E 均通过；另有 28 个政策案例、16 个离线 Agent 案例及两组 HTTP 冒烟。浏览器脚本临时创建数据库，在 8014/3810 启动测试服务，结束后停止服务；脚本模型标识 `NOT-A-REAL-MODEL`，不读取日常 API 密钥，也不改日常订单。它验证产品集成，不代表模型理解能力。


接口契约变动后同时更新 `frontend/openapi.json` 与 `frontend/src/lib/generated.ts`。
