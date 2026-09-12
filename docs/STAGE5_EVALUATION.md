# Stage 5 真实模型评测报告

本轮完成 125 个预注册自然语言场景：Dev 75、Test 50；最终 Test Task Success 为 **46/50（92.0%）**。Test 每 Case 正式执行一次，没有按 Test 结果调参或重跑。

这是单次、合成本地售后场景的模型与 Agent 集成评测，不是线上客户数据或生产成功率。全部支付/审批执行仍为本地模拟能力，Agent 没有实际资金执行权限。

## 数据集与实验流程

25 类场景覆盖取消、已发货拦截、高额退款、无理由、质量、错发、少件、未收到、退款中/重复、缺信息、多轮、模糊/同义、错误订单、越权/注入/绕过审批/篡改金额、故障、幂等、金额/时间边界、多商品和不支持请求。每类 Dev 3 / Test 2；完整字段在 [冻结数据集](../eval/stage5/manifest.json)。

先完成 125 个 fixture 的离线约束校验和金额/政策交叉核对，再冻结 baseline；随后完成 75 条真实 Dev，形成失败分析，才修改 Prompt/工具说明。候选版本完整复跑 Dev 后作保留/回滚决策，最终代码冻结后才打开 Test 运行。实验用独立数据库与固定业务时钟，未使用模型生成标准答案。

同一业务意图存在语言变体，两个 split 的 family_id 不交叉；但共享种子结构和商家规则，不能声称完全消除模板关联。数量为 125 个 episode，多轮包含两个实际 turn，同请求重放验证真实幂等。

数据集 hash：`ec351e0be642739c5fa0301d98ac9c4eab1e23974a0b2c96ee626f3dc3afacdd`。源码无已提交 git revision，以逐文件 SHA-256 和源码 ZIP 标识版本。

## 全部核心指标

| 指标 | Baseline Dev | Final Dev | Frozen Test |
|---|---:|---:|---:|
| Task Success Rate | 84.00%（n=75） | 93.33%（n=75） | 92.00%（n=50） |
| Action Accuracy | 97.33%（n=75） | 98.67%（n=75） | 98.00%（n=50） |
| Policy Compliance Rate | 97.92%（n=48） | 97.92%（n=48） | 96.77%（n=31） |
| Amount Accuracy | 97.92%（n=48） | 97.92%（n=48） | 96.77%（n=31） |
| Escalation Precision（审批） | 100.00%（n=14） | 100.00%（n=14） | 100.00%（n=10） |
| Escalation Recall（审批） | 100.00%（n=14） | 100.00%（n=14） | 100.00%（n=10） |
| Escalation Precision（物流） | 100.00%（n=7） | 100.00%（n=7） | 100.00%（n=4） |
| Escalation Recall（物流） | 100.00%（n=7） | 100.00%（n=7） | 100.00%（n=4） |
| Tool Selection Accuracy | 86.67%（n=75） | 93.33%（n=75） | 98.00%（n=50） |
| Tool Argument Accuracy（Case 级） | 100.00%（n=75） | 97.33%（n=75） | 100.00%（n=50） |
| Required Tool Recall（宏平均） | 91.29%（n=75） | 99.29%（n=75） | 99.32%（n=49） |
| Unsafe Action Rate | 0.00%（n=75） | 0.00%（n=75） | 0.00%（n=50） |
| Unauthorized Access Rate | 0.00%（n=75） | 0.00%（n=75） | 0.00%（n=50） |
| Policy Bypass Rate | 0.00%（n=75） | 0.00%（n=75） | 0.00%（n=50） |
| Duplicate Side Effect Rate | 0.00%（n=75） | 0.00%（n=75） | 0.00%（n=50） |
| Provider Failure Rate（自然故障 Case） | 0.00%（n=75） | 0.00%（n=75） | 0.00%（n=50） |
| NEED_MORE_INFO Accuracy | 58.33%（n=12） | 91.67%（n=12） | 87.50%（n=8） |
| Unsupported Response Rate | 10.67%（n=75） | 2.67%（n=75） | 4.00%（n=50） |
| Recovery Rate（可恢复注入故障） | 100.00%（n=3） | 100.00%（n=3） | 100.00%（n=1） |
| Average LLM Calls（外部 attempts） | 2.91 | 2.75 | 2.58 |
| Average Tool Calls | 3.72 | 3.73 | 3.50 |
| Input Tokens / Case | 6009.61 | 6479.81 | 6095.10 |
| Output Tokens / Case | 211.37 | 205.87 | 189.12 |
| Total Tokens / Case | 6220.99 | 6685.68 | 6284.22 |
| Avg Latency ms | 2716.71 | 2749.76 | 2725.86 |
| P50 Latency ms | 2751.00 | 2986.00 | 3092.00 |
| P95 Latency ms | 4471.70 | 4282.30 | 4312.30 |
| Unnecessary Tool Rate | 0.025090 | 0.007143 | 0.000000 |
| Invalid Tool Call Rate | 0.000000 | 0.003571 | 0.000000 |
| 批次 Cost Proxy USD | 0.154240 | 0.164324 | 0.102774 |

指标分母与含义：Policy/Amount 只评价有预期动作的 Case；未形成应有动作也会失败，故该失败不等于实际越过政策引擎。Action Accuracy 包含应无动作的 Case。Tool Argument 的 Case 级指标对未产生调用的 Case 是空集通过，因此同时应看 Tool Selection/Required Recall；参数检查范围为 schema、订单/商品/数量/诉求/已观察工单，结束 kind 的语义错误归入意图/补问指标。不能将这项单独宣传为模型全参数准确率。

Unnecessary Tool Rate 的分子为最终处理轮不在预定义必要/可选集合中的调用，分母为 episode 全部工具调用；多轮首轮补问单独检查，不是逐工具人工语义评分。Unsupported Response 包括无协议依据的输出及未展示所查退款状态的答复。补问准确率按最终应为 NEED_MORE_INFO 的 Case 计；多轮父轮是否成功另外纳入 Task Success。

自然 Provider Failure 只看真实 transport HTTP/网络失败，不能用它覆盖模型未遵守工具协议的错误。可恢复故障 Recovery 与持续故障分别报告。所有真实请求、重试、输入/输出都计数；注入 transport 不计为真实外部调用。Token 未报告时保留未知和成本预留，不填入“实测零”。

百分位是 (n−1)×p 线性插值；Latency 为 episode 多轮模型、工具、重试和落库时间，不含 fixture 初始化。95% Wilson 区间在各批次 summary.json 中。

## 配对优化对照

采用版本：`stage5-candidate-v1`。Dev 修复 Case：S5-051, S5-057, S5-061, S5-062, S5-087, S5-091, S5-121, S5-122；新失败 Case：S5-072。所有成功样本仅在预注册的整套 Dev 对照中复跑，没有挑选最好的一次来合并结果。

只针对两类 baseline 证据修改：①将真正的 function call 协议置顶，补问/拒绝也必须调用 finish_response；②明确越权或金额篡改、意图不清、订单/商品/数量缺失的优先级。金额/时间常量、Case ID、具体句子都没有写入运行时代码。工具 schema、Provider 的 tool_choice、PolicyEngine、金额计算与安全校验未放宽。

未采用：直接展示 draft_reply（失去事实约束）；为退款进度新增回复渲染能力（超出本轮限定优化面）；强行提交每个政策查询以迎合严格 gold；针对测试句写关键词分支；无证据的检索/重试/高权限扩展。退款进度模板缺口作为真实失败保留。

Baseline→Final 只比较同一 Dev；独立 Test 用于报告最终成绩，不将 Dev/Test 的差异称为优化收益。单次配对仍受模型随机性与网络波动影响。

## 各业务类型

| 类型 | Dev Baseline | Dev Final | Test |
|---|---:|---:|---:|
| ambiguous | 33.33%（n=3） | 100.00%（n=3） | 50.00%（n=2） |
| amount_boundary | 100.00%（n=3） | 100.00%（n=3） | 100.00%（n=2） |
| bypass_approval | 66.67%（n=3） | 100.00%（n=3） | 100.00%（n=2） |
| cancel | 100.00%（n=3） | 100.00%（n=3） | 100.00%（n=2） |
| change_amount | 66.67%（n=3） | 100.00%（n=3） | 100.00%（n=2） |
| damaged | 100.00%（n=3） | 100.00%（n=3） | 100.00%（n=2） |
| duplicate_refund | 66.67%（n=3） | 66.67%（n=3） | 50.00%（n=2） |
| fault | 100.00%（n=3） | 100.00%（n=3） | 100.00%（n=2） |
| high_amount | 100.00%（n=3） | 100.00%（n=3） | 100.00%（n=2） |
| idempotency | 100.00%（n=3） | 100.00%（n=3） | 100.00%（n=2） |
| injection | 100.00%（n=3） | 100.00%（n=3） | 100.00%（n=2） |
| invalid_order | 100.00%（n=3） | 66.67%（n=3） | 100.00%（n=2） |
| missing | 100.00%（n=3） | 100.00%（n=3） | 100.00%（n=2） |
| missing_info | 66.67%（n=3） | 100.00%（n=3） | 100.00%（n=2） |
| multi_item | 100.00%（n=3） | 100.00%（n=3） | 100.00%（n=2） |
| multiturn | 66.67%（n=3） | 100.00%（n=3） | 100.00%（n=2） |
| not_received | 100.00%（n=3） | 100.00%（n=3） | 100.00%（n=2） |
| processing | 0.00%（n=3） | 0.00%（n=3） | 0.00%（n=2） |
| return | 100.00%（n=3） | 100.00%（n=3） | 100.00%（n=2） |
| shipped_cancel | 100.00%（n=3） | 100.00%（n=3） | 100.00%（n=2） |
| synonym | 100.00%（n=3） | 100.00%（n=3） | 100.00%（n=2） |
| time_boundary | 100.00%（n=3） | 100.00%（n=3） | 100.00%（n=2） |
| unauthorized | 100.00%（n=3） | 100.00%（n=3） | 100.00%（n=2） |
| unsupported | 33.33%（n=3） | 100.00%（n=3） | 100.00%（n=2） |
| wrong | 100.00%（n=3） | 100.00%（n=3） | 100.00%（n=2） |

## 调用、成本与模型身份

全部批次实际外部请求 **756** 次；输入 **1,729,205**、输出 **55,791** Tokens；峰时无缓存折扣 cost proxy 合计 **US$0.585711**，低于 US$5 上限。未知用量 attempts：0。这是按价格计算的代理金额，不是供应商账单截图。

模型请求别名为 deepseek-v4-flash，供应商返回模型标识见下表。官方说明该旧别名目前由 V4.1 Flash 服务；返回别名不能证明底层权重版本固定，因此未拿 Stage 3.5 旧模型结果做因果对照。[官方价格与别名说明](https://api-docs.deepseek.com/quick_start/pricing/)

| 批次 | requested model | returned model | 开始/结束（UTC） |
|---|---|---|---|
| stage5-baseline-v1-dev | deepseek-v4-flash | deepseek-flash | 2026-09-11T04:22:38.380191+00:00 / 2026-09-11T04:27:02.134710+00:00 |
| stage5-candidate-v1-dev | deepseek-v4-flash | deepseek-flash | 2026-09-11T04:28:52.121698+00:00 / 2026-09-11T04:33:06.457070+00:00 |
| stage5-candidate-v2-dev | deepseek-v4-flash | deepseek-flash | 2026-09-11T04:34:51.647004+00:00 / 2026-09-11T04:38:42.148955+00:00 |
| stage5-final-v1-test | deepseek-v4-flash | deepseek-flash | 2026-09-11T10:26:21.545475+00:00 / 2026-09-11T10:29:01.513732+00:00 |

最终 config hash：`76090acb5da6d5205541603a91813e27b2fb2aece6238bd44d3526fea4782798`；Prompt hash：`8c65ccdcef0405cad220a327ff13b9ca4d8761f39c5e47e22a7673b6fc39a756`；代码版本 hash：`0f43c9aeddfbbafc4d8717cb344964b4cc874d27e13e9d97bd1d700de8babbeb`。每批完整 hash 保存在 batch.json，每 Case 同步记录，逐请求 ledger 另存请求 hash 与 returned model。

## 证据和复现

- [总账审计](verification/stage5/final-audit.json)、[实验协议](verification/stage5/PROTOCOL.md)。
- [Baseline](verification/stage5/stage5-baseline-v1-dev/summary.json)、[最终 Test](verification/stage5/stage5-final-v1-test/summary.json)、[采用决策](verification/stage5/adoption.json)。
- 每批 cases/ 保存完整工具/模型 trajectory、数据库 diff、failure_stage/failure_stages/failure_reason；attempts/ 保存实际 HTTP 用量。数据快照 ZIP 可恢复冻结 Case。
- 原实验命令为 `python scripts/stage5.py freeze <version>` 和 `python scripts/stage5.py run <version> --split dev|test`；已有版本拒绝覆盖，已完成 Case 不重发，未完成标记阻止盲目重试。不要删除 Test 标记后重跑正式成绩。

## 测试与限制

工程回归：后端 173/173、前端组件 5/5、浏览器 E2E 8/8 通过；Ruff、依赖检查、政策/HTTP/离线 Agent 回归及前端 lint/build 通过。见 [regression-summary.json](verification/stage5/regression-summary.json) 与 [frontend-summary.json](verification/stage5/frontend-summary.json)。浏览器 E2E 使用脚本模型，不计入真实模型成绩。Stage 4 前端与鉴权继续使用原实现。

本轮不是生产压力测试；Test 每类只有 2 条，分类型比例不稳定。0 次观察到的安全违规不等于绝对安全，应结合置信区间及有限攻击覆盖解读。退款查询固定模板、严格的政策持久化 gold、外部模型版本不可固定、未覆盖全部多轮组合仍是限制。故障注入只能说明这些受控故障下的行为。

Stage 5 到此停止，没有新增业务模块、Multi-Agent、MCP、长期 Memory 或生产部署。

## 每轮 Dev 明细

| 版本 | Task Success | Token/Case | LLM/Case | Tool/Case | Avg ms |
|---|---:|---:|---:|---:|---:|
| stage5-baseline-v1-dev | 84.00%（n=75） | 6220.99 | 2.91 | 3.72 | 2716.71 |
| stage5-candidate-v1-dev | 93.33%（n=75） | 6685.68 | 2.75 | 3.73 | 2749.76 |
| stage5-candidate-v2-dev | 92.00%（n=75） | 6703.80 | 2.71 | 3.63 | 2631.52 |

第一轮假设见 [round1-hypothesis.json](verification/stage5/round1-hypothesis.json)；第二轮仅针对 Dev 中错误订单的对象替换问题，见 [round2-hypothesis.json](verification/stage5/round2-hypothesis.json)。每轮整套运行，所有结果保留；最多两轮，没有用 Test 决定改动。

Baseline 63/75 → 第一轮 70/75；第二轮降至 69/75，按预定标准回滚并采用第一轮。第一轮成功率提高 9.33 个百分点，平均 Tokens 从 6220.99 增至 6685.68（约 +7.47%），平均 LLM 调用从 2.91 降至 2.75；这次主要改善任务正确性，并未实现 Token 成本下降。三批 Dev 加一批 Test 共 275 次 episode 执行，对应 125 个唯一场景。

数据来源澄清：场景文本由开发助手编写，期望按确定性业务规则定义并在冻结前交叉验证；不是人工标注的真实客户语料，也没有让被测 DeepSeek 自行生成评分答案。协议早期“人工编写”应按此说明理解。

## 交付完整性核对

冻结源码、Prompt、Tool 定义和数据集 hash 均未变化，Prompt/Tool 与第一轮 Dev 采用版本一致。日常数据库与 baseline 运行中所留只读检查点的全部表 hash 一致（不是评测前备份证明）；各场景数据库位于独立 data/stage5。见 [integrity-audit.json](verification/stage5/integrity-audit.json)。

完成实验与报告交付不代表所有功能零缺陷：退款进度答复仍有覆盖缺口，另有严格落库 gold 和补问标注歧义。Test 结果保持 46/50，不因这些解释改分。
