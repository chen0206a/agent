# 修复后独立评测协议

用户授权新增总预算 **CNY ¥5.00**。本轮先整理实际演示与启动说明，再验证当前修复版本；不调 Prompt、Tool 或业务代码，不进入 RAG 或新的功能开发。

## 版本与数据

- 新实验：`reliability-postfix-v1`，数据位于 `eval/reliability-postfix-v1`，证据位于 `docs/verification/reliability-postfix-v1`。
- 39 个新措辞 episode，Dev 13 / Holdout 26，共 45 turn，13 类场景。复用原业务金标准、确定性评分器和固定隔离 fixture 时间 `2026-09-30T04:00:00Z`，金额及政策契约保持不变。
- 场景包括退款状态、政策咨询、取消申请、高金额审批、物流调查、意图/订单补问、越权拒绝、咨询转申请和申请改查询。越权样本包含指令覆盖措辞。
- 检查新数据内部及与原可靠性/历史评测数据的精确文字交集；不声称语义隔离。已知业务家族及 fixture 相同，同一作者编写并结构复核 Holdout，**不是盲测、家族隔离、第三方标注或生产流量**。
- Holdout 在任何真实 Dev 执行前冻结；Dev 仅验证，无调参。完成 Dev 和人工复核后建立 final seal，正式 Holdout 只运行一次。所有开始标记、失败、未运行项和数据库快照保留。

## 实施与冻结

`scripts/reliability_followup.py` 使用独立导入的既有 `reliability_eval.py` / `reliability_live.py`，明确绑定新目录，并纳入适配器、测试、协议、计价、产品及数据 hash。原脚本和旧 release/manifest 不改写。新实验使用自己的预算账本，不继承旧实验未花预算，也不重置旧账本。

先仅执行新 Dev 的脚本契约检查，Holdout 不进入 Agent；冻结当前 Prompt / Tool schema / 配置与完整后端源码，提交代码并核对版本后才能付费执行。请求使用本地配置的 Flash 模型，保留 requested model 和 provider returned model；别名不证明服务商权重永久固定。密钥不进入实验或报告。

## 计价与停止

本次已核对 [DeepSeek 官方人民币定价](https://api-docs.deepseek.com/zh-cn/quick_start/pricing/)：峰时输入缓存未命中 ¥2、输出 ¥8 / 百万 tokens。即便实际享受缓存或谷时折扣，预算结算仍按此保守价格；计价来源与 UTC 核对时间另存 `pricing.json`。

Dev + Holdout 共用 **¥5** 总上限，预约在 HTTP 前持久化；用量不明、预约超额、账本与导出不一致即停止。预算为费用代理值，不是余额或账单。重试同样计费；不因本轮没有花完就增加样本或重跑失败。账户余额不足导致的错误保留，不自动替换 key 或 provider。

## 评分与复核

继承固定评分：Task Success 按 episode，Tool Selection / Arguments 按 turn，Required Tool Recall、Policy Compliance、Unsafe Action、完整模型/工具轨迹、数据库前后状态、幂等重读、LLM / Tool Calls、Tokens 与延迟。`runtime_failure_stage` 与 `evaluation_failure_stage` 分别记录。

新增人工复核：

1. 查全部失败、工具偏差与安全相关轨迹；不依据“文字意思差不多”改标签。
2. 核对模型 HTTP 重试与逻辑调用编号，查看新结束纠正机制是否实际触发。若没有触发，不宣称真实验证了纠正成功率。
3. 对补问是否有多余读取、查询是否正常终止、仅咨询是否产生意外副作用分别统计。
4. 每批记录 UTC 时间、requested/returned model、配置/Prompt/Tool/代码/数据 hash。未运行项计入固定分母，缺失 usage 不当作零。

旧 Test 46/50 与旧可靠性 Holdout 25/26 保持历史结论，新集不能作为直接提分幅度。工程故障注入和脚本浏览器演示不混入真实模型分母。任何零次 unsafe 观察都不表述为“100% 安全”。

## 交付与停止

输出演示指南、实际浏览器录屏/截图、新版本真实评测报告与失败分析，链接完整原始证据；明确当前限制及 RAG 的进入条件。完成后停止，不追加调参、旧 Holdout 重跑或新功能。
