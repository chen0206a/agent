# 可用于简历的实测指标

口径：冻结的 50 个本地合成自然语言 Test episodes，真实 DeepSeek API，一次正式评测。不是线上真实客户指标；所有资金操作为模拟，模型无支付权限。

| 指标 | 测得结果 |
|---|---|
| Test Case 数量 | 50 |
| Task Success Rate | 92.00%（n=50） |
| Policy Compliance Rate | 96.77%（n=31） |
| Unsafe Action Rate | 0.00%（n=50） |
| Escalation Recall（审批） | 100.00%（n=10） |
| Tool Selection Accuracy | 98.00%（n=50） |
| 平均 Tool Calls | 3.50 |
| 已报告 Tokens / Case | 6284.22 |
| P50 Latency（ms） | 3092.00 |
| P95 Latency（ms） | 4312.30 |

Task Success 的 Wilson 95% 区间为 81.2%–96.8%。Unsafe 0/50 若成立只表示该样本中未观察到，不等于生产风险为零。

推荐简历描述：

> 开发电商智能售后单 Agent 系统，结合确定性 PolicyEngine、金额校验、服务端角色权限与幂等控制；构建 125 条合成自然语言评测（Dev 75 / Test 50），冻结 Test 单次真实 DeepSeek 评测取得 Task Success 92.0%（46/50），观察到实际不安全动作 0/50，记录逐调用轨迹、Token 与 P50/P95 延迟。

来源：[最终 Test 汇总](verification/stage5/stage5-final-v1-test/summary.json)、[总审计](verification/stage5/final-audit.json)。不能写成“生产系统准确率”“零风险”“真实支付落地”或把离线测试当真实模型成绩。
