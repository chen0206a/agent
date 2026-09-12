# Stage 5 项目作品集交接

## 项目解决什么问题

AfterSale Copilot 把客户自然语言售后需求转换为可审计的业务建议：先查询订单/物流/商品与政策，再由确定性业务层决定金额、授权动作和是否需要人工。客户可以在中文 Web 门户咨询和看进度，管理员在独立权限下审批、收货和模拟执行。

## 技术与边界

FastAPI + SQLite + LangGraph 单 Agent；Next.js / React / TypeScript / Tailwind / shadcn/ui 前端。服务端 Cookie 会话、scrypt 密码、CSRF、归属校验；Agent 工具不含管理员或资金执行入口。PolicyEngine 承担许可判断，RefundCalculator 计算金额，WorkflowService 保持幂等和审计。

## 最有价值的实验结论

最终冻结 Test：Task Success 92.00%（n=50）；平均工具调用 3.50；平均已报告 Tokens 6284.22。这些结果可追溯到完整 trajectory 与配置、数据集 hash，详细口径见 [评测报告](STAGE5_EVALUATION.md)。

本次优化针对“正确意思却输出了无效协议”的失败，强化真正调用结束工具与澄清优先级。没有让模型决定金额或执行动作，也没有通过放开自由文本绕过事实约束。真实模型会失败；完整保留失败是作品集可信度的一部分。

## 推荐演示流程

1. 按 README 设置本机账号并启动前后端，customer 查询未发货订单并申请取消，说明 READY 不等于已退款。
2. 演示高额退款 WAITING_APPROVAL，admin 核实政策后批准和模拟执行，解释职责分离。
3. 演示签收未收到和主动补问，再由普通客户尝试访问 admin，展示后端拒绝。
4. 打开 Agent Trace、Stage 5 冻结清单和一例成功/失败；说明真实模型评测与脚本 E2E 的区别。

## 面试时如何解释

- 为什么不让 LLM 算金额：优惠分摊、额度占用和重复提交需要确定性保证。
- 为什么不以运行 SUCCESS 当总分：正常结束仍可能没有解决诉求；本次退款查询就暴露了该差异。
- 如何防止刷分：先冻结 dataset/expected，Dev 调参，Test 仅一次，保留失败和逐次调用。
- 是否是 RAG：使用小规模版本化政策检索作说明证据，最终许可不由检索文本决定。
- 有什么局限：合成小样本、每类 Test 2 条、外部模型别名变更、非支付生产系统、退款答复模板未覆盖全部查询。

## 阅读与复现顺序

先读 [README](../README.md) → [Stage 4 页面与鉴权](STAGE4_HANDOFF.md) → [评测协议](verification/stage5/PROTOCOL.md) → [冻结数据集](../eval/stage5/manifest.json) → scripts/stage5.py → backend/tests/test_stage5.py → 单 Case JSON → 四份报告。模型账本与结果直接保存在 docs/verification/stage5；独立库在 data/stage5，日常库不重置。

## 交付清单

- [STAGE5_EVALUATION.md](STAGE5_EVALUATION.md)：所有指标、分类型和模型/配置身份。
- [STAGE5_FAILURE_ANALYSIS.md](STAGE5_FAILURE_ANALYSIS.md)：baseline 分析、优化假设、完整失败与限制。
- 本文：作品集讲解和演示路线。
- [RESUME_METRICS.md](RESUME_METRICS.md)：真实 Test 指标及推荐表述。

Stage 5 完成后停止开发。未增加 Multi-Agent、MCP、复杂 Memory、新业务或生产部署。
