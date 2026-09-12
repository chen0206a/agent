# Stage 4 实施计划

1. 增量新增账户、会话和登录限流表；旧14张表和已验收Agent/PolicyEngine保持原样。密码scrypt，随机会话令牌只存哈希，HttpOnly/SameSite Cookie与CSRF；生产代码不接受演示身份头。CLI交互初始化账户，不存明文密码。
2. 补充受权限约束的申请、运行列表与Dashboard统计，route → service → repository；管理员Trace输出过滤system消息与reasoning_content。
3. Next.js / React / TypeScript / Tailwind / shadcn/ui；同源API代理，OpenAPI生成类型。客户登录、订单/物流、会话和申请；管理员统计、工单、审批、收货、模拟执行与Trace。
4. 迁移原身份相关测试到真实会话，其业务断言保留；新增Auth、CSRF、越权、Dashboard测试；组件/集成测试与Playwright浏览器E2E（独立数据库、明确标识的scripted模型，不追加真实API成本）。
5. 验证生产构建、152项原回归及新增测试；保留截图与机器结果，输出STAGE4_HANDOFF.md后停止。Stage5不执行。

指标口径：请求总数=AgentRun；成功数=run.status SUCCESS（不是退款成功）；人工审批数=有审批的Agent申请数；Automation Rate=无人工审批的READY/WAITING_RETURN/LOGISTICS_PENDING运行数÷已完成运行数；Human Review Rate=关联Approval的运行数÷已完成运行数。Token仅累加真实调用已知usage，并单列未知usage调用数。物流Timeline仅显示已有时间点，不捏造轨迹。
