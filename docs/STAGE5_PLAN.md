# Stage 5 实施与预算计划

日期：2026-09-11。状态：方案待确认，尚未进行 Stage 5 真实 API 批量调用，尚未修改 Agent Prompt。

## 实验范围

构建 125 个自然语言场景：Dev 75、Test 50，覆盖用户指定的 25 类场景。每类主标签分配 Dev 3 / Test 2；另设多标签统计。金额、时间边界、多轮、证据状态和权限组合使用不同 fixture。按场景家族划分，避免同一题换句话同时进入 Dev/Test。Test 不向模型或调参流程提供 expected 字段。

每个 Case 保存用户要求的全部字段：case_id、split、user_id、initial_database_fixture、user_message、parent history、expected_business_outcome、required_tools、optional_tools、forbidden_tools、expected_policy_decision、expected_authorized_action、expected_escalation、unsafe_conditions、expected_database_diff。补充 family_id、业务分类、时钟、允许的等价结果/工具路径、金额期望、故障注入方案和多轮步骤。

先写 fixture、判分规范与 Cases，再冻结数据集 SHA-256。期望结果从独立业务事实与现有规则推导，不能由待测模型生成；人工检查金额/时间边界和困难样本。没有单一必要工具路径时预定义等价查证路径，避免把合理行为判错。不向模型透露标准答案。

## 实施步骤

1. 评测基础设施：独立临时数据库、冻结业务时钟、版本快照、逐 HTTP attempt 账本、断点续跑、结构化判分、失败归因、汇总器；先使用离线 fixture 自测判分器，不计入真实模型成绩。保持已验收的权限、业务、安全和幂等实现。
2. 冻结当前 Stage 4/Stage 3.5 optimized 源码为 stage5-baseline-v1，保存 Prompt、工具定义、检索配置、模型参数、依赖、源文件哈希及模型价格快照。
3. Dev 75 条各跑一次真实 DeepSeek baseline。分析总分、分类型、成本、失败阶段和最多 10 个有分析价值的失败；不足 10 个如实报告，不凑数。先形成分析报告，再决定代码优化。
4. 默认一轮优化，最多两轮；每轮仅针对 1–2 个有证据的失败模式。每轮冻结候选版本并完整运行相同 Dev，做逐 Case 配对比较。安全指标变差或 Task Success 下降则回滚；不将失败后的多次尝试择优合并。
5. 没有可支持的改动时保留 baseline，允许优化收益为零。冻结最终源码/配置为 stage5-final-v1。
6. Test 50 条正式评测一次；每条只登记一个正式 episode，传输重试属于该 episode 并计费计数。中断后只继续未完成 Case；请求结果不确定的 Case 标为不确定，不能悄悄再跑。Test 结果不再用于修改模型、Prompt、判分器或 expected。
7. 跑现有 166 项后端回归、前端测试/生产构建和已有浏览器 E2E；输出评测、失败分析、作品集与简历指标文档。完成后停止，不开发新业务或部署。

## 指标与判分

完整实现用户要求的所有指标，按以下规则解释：

- Task Success：预先规定的业务结果、关键数据库变化、金额和安全约束同时成立。成功补问/拒绝可为成功任务；运行 SUCCESS 本身不是 Task Success。
- Action Accuracy、Policy Compliance、Amount Accuracy 在适用 Case 上统计，公布分母；不适用为 N/A，不凭空算正确。
- Escalation Precision/Recall 区分人工审批和物流调查，避免将所有补问都当升级。
- Tool Selection、Tool Argument、Required Tool Recall、Unnecessary Tool Rate、Invalid Tool Rate 根据预定义等价路径、参数事实和真实轨迹判分，不要求机械复制某一工具序列。
- Unsafe Action、Unauthorized Access、Policy Bypass、Duplicate Side Effect 同时检查实际结果、数据库 diff 与调用轨迹。被工具拒绝的攻击尝试和真正的数据泄露/副作用分开报告。
- Provider Failure 与 Recovery 按 HTTP attempt 和 episode 分别统计，分母明确；注入故障单列，不能伪装成 DeepSeek 服务自然失败。
- NEED_MORE_INFO Accuracy 区分该问且问、该问未问、不该问却问；Unsupported Response Rate 预定义为缺乏依据/不符合协议的回复，另报对超范围请求的正确拒绝率。
- Token、LLM Calls、Tool Calls 与成本覆盖多轮及重试。用量未返回记未知，保留保守估算，不伪造零 Token。
- 平均/P50/P95 使用端到端 Case 耗时，并分别给出单请求与故障注入子集。保存百分位计算方法；比例报告样本数与 Wilson 95% 区间，避免小样本过度推断。

自动归因包含全部指定类别：SUCCESS、INTENT_ERROR、MISSING_INFORMATION_ERROR、TOOL_SELECTION_ERROR、TOOL_ARGUMENT_ERROR、RETRIEVAL_ERROR、POLICY_INTERPRETATION_ERROR、BUSINESS_STATE_ERROR、UNSAFE_ACTION、PERMISSION_ERROR、FINAL_RESPONSE_ERROR、PROVIDER_ERROR、TIMEOUT、UNKNOWN。保存 failure_stage、failure_stages、failure_reason 和对应证据；不确定因果保留 UNKNOWN，人工补充分析不得修改评分事实。

Baseline→Final 的效果对比仅使用相同 Dev；最终 Test 独立报告，不能将不同集合的差异宣传为优化收益。复现指复现数据、配置与步骤，不保证外部随机模型每次输出相同。

## 模型与成本

官方价格核验：https://api-docs.deepseek.com/quick_start/pricing/ （2026-09-11）。官方当前说明 legacy deepseek-v4-flash 请求已由 DeepSeek-V4.1-Flash 服务。保留原请求别名和参数以重新建立 baseline，记录响应 model、时间及可用的版本标识；不将新实验与旧版模型的 Stage 3.5 数字做因果比较。API 若无法固定底层权重，报告此复现限制。

当前 Flash 每百万 Token：峰时未命中输入 USD 0.30，输出 USD 1.20；非峰时分别 USD 0.15 / 0.60。按峰时、输入全部未命中估算，不假设缓存折扣，最终以实际账单为准。

Stage 3.5 optimized 五个场景合计输入 22,665、输出 1,153、11 次真实模型调用，即约 4,533 输入/231 输出/2.2 调用每 Case。新评测有多轮和故障，采用更宽的 6,000–12,000 输入、300–800 输出、3–6 次 HTTP attempt 每 episode 作为规划区间，不作为测得指标。

| 批次 | Case episodes | HTTP attempt 估计 | 输入 Token | 输出 Token | 峰时 cost proxy |
|---|---:|---:|---:|---:|---:|
| Baseline Dev | 75 | 225–450 | 0.45–0.90M | 22.5–60K | $0.162–0.342 |
| 一轮候选 Dev | 75 | 225–450 | 0.45–0.90M | 22.5–60K | $0.162–0.342 |
| Frozen Test | 50 | 150–300 | 0.30–0.60M | 15–40K | $0.108–0.228 |
| 默认合计 | 200 | 600–1200 | 1.20–2.40M | 60–160K | $0.432–0.912 |

若进行第二轮 Dev，再增加 75 episodes，预计总额 $0.594–1.254。真实调用的长上下文、重试、价格变化可能超出估计。

建议批准总预算 USD 5；同时设置最多 1,800 次外部 attempt 的守卫。每次请求前计入可保守估算的本次最大消耗，超过预算则停止新请求；失败未报告用量时保留未知区间，预算控制不能承诺与供应商账单分毫一致。优先为最终 Test 保留 USD 2 和 600 attempts；不能为了多做 Dev 消耗掉 Test 配额。到上限后报告实际覆盖，不擅自提高预算。无需现在额外充值，余额如不足再如实报告。

串行或低并发运行，按每 Case 10–30 秒粗估默认批量模型时间约 35–100 分钟，不含评测实现、故障等待、分析与回归；不是完成时间承诺。

## 交付

- eval/stage5/：冻结数据集、fixture 定义、schema 与 manifest。
- docs/verification/stage5/：baseline/final/候选快照、运行账本、逐 Case 轨迹、数据库 diff、指标与故障证据。
- docs/STAGE5_EVALUATION.md。
- docs/STAGE5_FAILURE_ANALYSIS.md。
- docs/STAGE5_PORTFOLIO.md。
- docs/RESUME_METRICS.md：只收录真实、明确分母的最终 Test 指标和诚实的简历描述。

## 批量调用前确认

用户提供的 Stage 5 文件明确要求：“先输出实施计划和预计 API 成本，确认评测集、指标和实验流程后再开始真实 API 批量运行。”

待确认的统一方案：125 Cases（Dev 75 / Test 50），默认一轮、最多两轮有证据的优化，Test 正式运行一次，总预算 USD 5。确认后执行；本计划阶段不产生模型调用费用。
