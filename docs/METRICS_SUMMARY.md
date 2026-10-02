# 离线指标汇总器

入口：[`scripts/summarize_metrics.py`](../scripts/summarize_metrics.py)。只使用 Python 标准库读取已保存的 JSON，不导入 Agent 或模型运行器，不读取 `.env`、密钥、账户余额或 SQLite，不发网络请求。无需启动服务。

它生成派生 JSON 和中文 Markdown，补齐分类结果、业务契约达成、耗时分位数、成功任务成本与错误恢复统计；**不改变原有评分，不重新运行 Dev/Test/Holdout**。

## 使用

在项目根目录执行：

```powershell
# 最新修复版，分别汇总 Dev 和 Holdout
.\.venv\Scripts\python.exe -X utf8 scripts/summarize_metrics.py --split dev
.\.venv\Scripts\python.exe -X utf8 scripts/summarize_metrics.py --split holdout

# 历史可靠性评测：单独输出，不混合版本
.\.venv\Scripts\python.exe -X utf8 scripts/summarize_metrics.py --version reliability-v1 --split holdout
```

默认写入 `docs/metrics/<version>/dev.json|md` 或 `holdout.json|md`。相同结果再次执行不改文件；已有文件内容不同则拒绝覆盖。如将来升级汇总口径，使用新的目录保存：

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/summarize_metrics.py --split holdout --output-dir docs/metrics/new-summary
```

输出目录必须在 `docs/metrics/` 内；不能写入原始实验归档。当前支持 `reliability-postfix-v1` 和 `reliability-v1` 的归档格式。原 125 条评测的数据/评分格式不同，尚未接入本汇总器；仍以原报告为准，不混用其 episode/turn 或 macro/micro 指标。

## 查看结果

| 版本 | Dev | Holdout |
|---|---|---|
| 当前修复版 | [Dev 汇总](metrics/reliability-postfix-v1/dev.md) | [Holdout 汇总](metrics/reliability-postfix-v1/holdout.md) |
| 历史可靠性版 | [Dev 汇总](metrics/reliability-v1/dev.md) | [Holdout 汇总](metrics/reliability-v1/holdout.md) |

当前 Holdout 的原 Strict Task Success 仍为 **25/26（96.15%）**；新派生的业务契约达成是 **26/26**。差异来自 FIX-08-1：额外参数被拒绝后，模型安全纠正并建立物流调查；参数错误仍保留为严格任务失败。[原失败分析](RELIABILITY_POSTFIX_FAILURE_ANALYSIS.md)。

单轮 P50 **2,048 ms**，P95 **3,550 ms**；任务累计活跃时间 P95 **4,744 ms**。全部 Holdout attempt 的成本代理为 **¥0.355236**，除以 25 个严格成功任务得 **约 ¥0.014209/成功任务**，包含失败任务消耗。

## 指标口径

| 指标 | 定义 / 分母 |
|---|---|
| Strict Task Success | 复用原归档的 `passed`；计划 episode 数为分母，不改判失败 |
| 业务目标达成 | 每轮运行成功，原 outcome、动作/金额、响应证据、结束类型及政策检查通过，整个任务数据库与幂等检查通过；恢复的参数错误不单独否定业务目标 |
| 场景分类 | 按冻结数据中的 category 汇总，两种成功率并列；每类的小样本不能推断生产表现 |
| 多轮成功率 | 只统计计划中超过一轮的 episode，所有轮次完成；分别给出严格与业务成功率 |
| Tool Selection / Arguments | 复用原整轮布尔评分；前者为允许名称集合检查，后者任何一次参数错误都会失败 |
| Required Tool Recall | 成功必要工具项总数 / 计划必要工具项总数，micro 汇总 |
| 政策 / 副作用 / 幂等 | 复用原政策检查、Unsafe Action、数据库差异与重复请求证据，不扩大安全结论 |
| Latency | 单轮运行时间；完整 episode 各轮运行时间之和。P50 中位数，P95 最近秩法；不包括用户或人工审批等待 |
| 成本与 Tokens | 使用归档账本的全部该 split attempt，包括失败和重试；缺 usage、结算或请求对应证据则未知 |
| 每个成功任务成本 | 全 split 成本 / 对应成功 episode 数；零成功时未知，不除零 |
| 工具错误恢复 | 发生工具错误的 turn 中，最终所在 episode 安全达成业务目标的比例；保留 case 和错误类型 |
| 结束协议纠正恢复 | 识别带已知纠正标记且仅开放 `finish_response` 的模型请求；按触发 turn 统计安全业务恢复 |
| HTTP 重试恢复 | case + turn + logical call 范围内存在后续 attempt，最后 attempt 成功结算、有 usage 且无传输错误；不等于业务恢复 |
| 调用复核候选 | 可选工具、不在允许集合的工具、同名同参数重复调用和失败调用；不自动给出“浪费率” |

业务目标达成依赖既有金标准的覆盖范围，不是用户满意度、真实支付成功率或生产自动化率。只有合成模拟订单，没有实际支付。恢复只有 **1 个真实工具错误样本**；协议纠正与 HTTP 重试零触发均显示“无样本”，不能宣传 100% 恢复。

缺失任务、未完成轮次保留计划分母；业务证据未知单独计入覆盖缺口，不作为通过。历史重试字段存在已披露口径缺陷，因此旧版 HTTP 恢复指标显示未知，不修改旧记录来补成绩。

## 证据与保护

- 核对 dataset hash 与原 batch；账本按 split 隔离，并核对模型、代码、配置、Prompt、Tool 和实验 hash。
- 原 summary 与逐 Case 文件内容不一致时拒绝汇总；存在复核 hash 时核对它，发现归档变更即报错。
- 新版按 case/turn/logical call/attempt 对齐模型记录和账本，重复或不连续的 attempt 标识报错。
- JSON 保留来源文件 SHA-256、原批次版本信息、逐任务结果及两类 failure stage；不复制 system prompt、reasoning 或用户文本。
- 汇总器不访问或修改业务库，不提供付费重放入口，也不改变 Dashboard 的现有统计口径。

原完整报告：[当前真实模型验收](RELIABILITY_POSTFIX_EVALUATION.md)、[当前失败归因](RELIABILITY_POSTFIX_FAILURE_ANALYSIS.md)、[历史可靠性验收](RELIABILITY_HOLDOUT_EVALUATION.md)、[原冻结 Test 评测](STAGE5_EVALUATION.md)。

## 验证

新增 16 项离线测试覆盖：原失败保留、业务与严格成绩分离、缺失分母、未知业务检查、数据库副作用阻止恢复、未知费用、不连续重试、归档身份/数据 hash、历史字段限制及输出防覆盖。

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest backend/tests/test_metrics_summary.py -q
```

完整后端回归 **294 passed**：[JUnit](metrics/backend-tests.xml)。禁止网络连接的环境下重复生成四份报告成功，输出字节一致；1,639 份历史 JSON 未变，51 个相对链接有效：[核对记录](metrics/verification.json)。

本次未修改产品业务或前端，没有新增模型费用；未来若需要生产用户满意度、持续 UI 性能或新实验的恢复样本，应另行设计采集与验收。
