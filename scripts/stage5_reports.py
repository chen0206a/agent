# ruff: noqa: E501
# Report prose stays on one line to preserve Markdown paragraphs.
"""Build final reports from immutable measured artifacts; does not run any model."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/verification/stage5"


def read(p):
    return json.loads(p.read_text(encoding="utf-8"))


def pct(row):
    if not row or row.get("value") is None:
        return "N/A"
    return f"{row['value'] * 100:.2f}%（n={row['n']}）"


def write(name, lines):
    (ROOT / "docs" / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    decision = read(OUT / "adoption.json")
    chosen = decision["adopted_version"]
    baseline = read(OUT / "stage5-baseline-v1-dev/summary.json")
    dev = read(OUT / (chosen + "-dev") / "summary.json")
    test = read(OUT / "stage5-final-v1-test/summary.json")
    versions = [p for p in OUT.glob("*/batch.json") if read(p)["status"] == "COMPLETE"]
    attempts = [read(p) for p in OUT.glob("*/attempts/*.json")]
    external = [a for a in attempts if a["actual_external_request"]]
    labels = {
        "task_success": "Task Success Rate",
        "action_accuracy": "Action Accuracy",
        "policy_compliance": "Policy Compliance Rate",
        "amount_accuracy": "Amount Accuracy",
        "approval_precision": "Escalation Precision（审批）",
        "approval_recall": "Escalation Recall（审批）",
        "logistics_precision": "Escalation Precision（物流）",
        "logistics_recall": "Escalation Recall（物流）",
        "tool_selection_accuracy": "Tool Selection Accuracy",
        "tool_argument_accuracy": "Tool Argument Accuracy（Case 级）",
        "required_tool_recall": "Required Tool Recall（宏平均）",
        "unsafe_action": "Unsafe Action Rate",
        "unauthorized_access": "Unauthorized Access Rate",
        "policy_bypass": "Policy Bypass Rate",
        "duplicate_side_effect": "Duplicate Side Effect Rate",
        "provider_failure": "Provider Failure Rate（自然故障 Case）",
        "need_more_info_accuracy": "NEED_MORE_INFO Accuracy",
        "unsupported_response": "Unsupported Response Rate",
        "controlled_recovery_rate": "Recovery Rate（可恢复注入故障）",
    }
    table = ["| 指标 | Baseline Dev | Final Dev | Frozen Test |", "|---|---:|---:|---:|"]
    for key, name in labels.items():
        table.append(
            "| " + name + " | " + " | ".join(pct(s["overall"].get(key)) for s in [baseline, dev, test]) + " |"
        )
    for key, name in [
        ("avg_llm_calls", "Average LLM Calls（外部 attempts）"),
        ("avg_tool_calls", "Average Tool Calls"),
        ("avg_input_tokens", "Input Tokens / Case"),
        ("avg_output_tokens", "Output Tokens / Case"),
        ("avg_total_tokens", "Total Tokens / Case"),
        ("avg_latency_ms", "Avg Latency ms"),
        ("p50_latency_ms", "P50 Latency ms"),
        ("p95_latency_ms", "P95 Latency ms"),
        ("unnecessary_tool_rate", "Unnecessary Tool Rate"),
        ("invalid_tool_rate", "Invalid Tool Call Rate"),
        ("cost_proxy_usd", "批次 Cost Proxy USD"),
    ]:
        table.append(
            "| "
            + name
            + " | "
            + " | ".join(
                "N/A"
                if s["overall"].get(key) is None
                else f"{s['overall'][key]:.6f}"
                if key in ("cost_proxy_usd", "unnecessary_tool_rate", "invalid_tool_rate")
                else f"{s['overall'][key]:.2f}"
                for s in [baseline, dev, test]
            )
            + " |"
        )
    baseline_rows = {p.stem: read(p) for p in (OUT / "stage5-baseline-v1-dev/cases").glob("*.json")}
    dev_rows = {p.stem: read(p) for p in (OUT / (chosen + "-dev") / "cases").glob("*.json")}
    fixed = [
        k
        for k in baseline_rows
        if not baseline_rows[k]["metrics"]["task_success"] and dev_rows[k]["metrics"]["task_success"]
    ]
    regressed = [
        k
        for k in baseline_rows
        if baseline_rows[k]["metrics"]["task_success"] and not dev_rows[k]["metrics"]["task_success"]
    ]
    test_rows = [read(p) for p in sorted((OUT / "stage5-final-v1-test/cases").glob("*.json"))]
    assert len(test_rows) == 50 and len({r["case_id"] for r in test_rows}) == 50
    assert read(OUT / "stage5-final-v1-test/batch.json")["status"] == "COMPLETE"
    total_input = sum(a["input_tokens"] or 0 for a in external)
    total_output = sum(a["output_tokens"] or 0 for a in external)
    cost = sum(a["cost_proxy_usd"] for a in external)
    meta = read(OUT / "stage5-final-v1/version.json")
    mf = read(ROOT / "eval/stage5/manifest.json")
    audit = {
        "actual_external_attempts": len(external),
        "injected_transport_attempts": len(attempts) - len(external),
        "input_tokens": total_input,
        "output_tokens": total_output,
        "unknown_usage_attempts": sum(not a.get("usage_complete") for a in external),
        "cost_proxy_usd": cost,
        "budget_usd": 5,
        "test_episodes": len(test_rows),
        "unique_test_case_ids": len({r["case_id"] for r in test_rows}),
        "dataset_hash": mf["dataset_hash"],
        "requested_models": sorted({a["requested_model"] for a in external}),
        "provider_returned_models": sorted(
            {a["provider_returned_model"] for a in external if a.get("provider_returned_model")}
        ),
        "fixed_dev_cases": fixed,
        "regressed_dev_cases": regressed,
    }
    (OUT / "final-audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Stage 5 真实模型评测报告",
        "",
        f"本轮完成 125 个预注册自然语言场景：Dev 75、Test 50；最终 Test Task Success 为 **{test['overall']['task_success']['numerator']}/50（{test['overall']['task_success']['value'] * 100:.1f}%）**。Test 每 Case 正式执行一次，没有按 Test 结果调参或重跑。",
        "",
        "这是单次、合成本地售后场景的模型与 Agent 集成评测，不是线上客户数据或生产成功率。全部支付/审批执行仍为本地模拟能力，Agent 没有实际资金执行权限。",
        "",
        "## 数据集与实验流程",
        "",
        "25 类场景覆盖取消、已发货拦截、高额退款、无理由、质量、错发、少件、未收到、退款中/重复、缺信息、多轮、模糊/同义、错误订单、越权/注入/绕过审批/篡改金额、故障、幂等、金额/时间边界、多商品和不支持请求。每类 Dev 3 / Test 2；完整字段在 [冻结数据集](../eval/stage5/manifest.json)。",
        "",
        "先完成 125 个 fixture 的离线约束校验和金额/政策交叉核对，再冻结 baseline；随后完成 75 条真实 Dev，形成失败分析，才修改 Prompt/工具说明。候选版本完整复跑 Dev 后作保留/回滚决策，最终代码冻结后才打开 Test 运行。实验用独立数据库与固定业务时钟，未使用模型生成标准答案。",
        "",
        "同一业务意图存在语言变体，两个 split 的 family_id 不交叉；但共享种子结构和商家规则，不能声称完全消除模板关联。数量为 125 个 episode，多轮包含两个实际 turn，同请求重放验证真实幂等。",
        "",
        f"数据集 hash：`{mf['dataset_hash']}`。源码无已提交 git revision，以逐文件 SHA-256 和源码 ZIP 标识版本。",
        "",
        "## 全部核心指标",
        "",
        *table,
        "",
        "指标分母与含义：Policy/Amount 只评价有预期动作的 Case；未形成应有动作也会失败，故该失败不等于实际越过政策引擎。Action Accuracy 包含应无动作的 Case。Tool Argument 的 Case 级指标对未产生调用的 Case 是空集通过，因此同时应看 Tool Selection/Required Recall；参数检查范围为 schema、订单/商品/数量/诉求/已观察工单，结束 kind 的语义错误归入意图/补问指标。不能将这项单独宣传为模型全参数准确率。",
        "",
        "Unnecessary Tool Rate 的分子为最终处理轮不在预定义必要/可选集合中的调用，分母为 episode 全部工具调用；多轮首轮补问单独检查，不是逐工具人工语义评分。Unsupported Response 包括无协议依据的输出及未展示所查退款状态的答复。补问准确率按最终应为 NEED_MORE_INFO 的 Case 计；多轮父轮是否成功另外纳入 Task Success。",
        "",
        "自然 Provider Failure 只看真实 transport HTTP/网络失败，不能用它覆盖模型未遵守工具协议的错误。可恢复故障 Recovery 与持续故障分别报告。所有真实请求、重试、输入/输出都计数；注入 transport 不计为真实外部调用。Token 未报告时保留未知和成本预留，不填入“实测零”。",
        "",
        "百分位是 (n−1)×p 线性插值；Latency 为 episode 多轮模型、工具、重试和落库时间，不含 fixture 初始化。95% Wilson 区间在各批次 summary.json 中。",
        "",
        "## 配对优化对照",
        "",
        f"采用版本：`{chosen}`。Dev 修复 Case：{', '.join(fixed) or '无'}；新失败 Case：{', '.join(regressed) or '无'}。所有成功样本仅在预注册的整套 Dev 对照中复跑，没有挑选最好的一次来合并结果。",
        "",
        "只针对两类 baseline 证据修改：①将真正的 function call 协议置顶，补问/拒绝也必须调用 finish_response；②明确越权或金额篡改、意图不清、订单/商品/数量缺失的优先级。金额/时间常量、Case ID、具体句子都没有写入运行时代码。工具 schema、Provider 的 tool_choice、PolicyEngine、金额计算与安全校验未放宽。",
        "",
        "未采用：直接展示 draft_reply（失去事实约束）；为退款进度新增回复渲染能力（超出本轮限定优化面）；强行提交每个政策查询以迎合严格 gold；针对测试句写关键词分支；无证据的检索/重试/高权限扩展。退款进度模板缺口作为真实失败保留。",
        "",
        "Baseline→Final 只比较同一 Dev；独立 Test 用于报告最终成绩，不将 Dev/Test 的差异称为优化收益。单次配对仍受模型随机性与网络波动影响。",
        "",
        "## 各业务类型",
        "",
        "| 类型 | Dev Baseline | Dev Final | Test |",
        "|---|---:|---:|---:|",
    ]
    for cat in sorted(test["by_category"]):
        lines.append(
            "| "
            + cat
            + " | "
            + " | ".join(pct(s["by_category"][cat]["task_success"]) for s in [baseline, dev, test])
            + " |"
        )
    lines += [
        "",
        "## 调用、成本与模型身份",
        "",
        f"全部批次实际外部请求 **{len(external)}** 次；输入 **{total_input:,}**、输出 **{total_output:,}** Tokens；峰时无缓存折扣 cost proxy 合计 **US${cost:.6f}**，低于 US$5 上限。未知用量 attempts：{audit['unknown_usage_attempts']}。这是按价格计算的代理金额，不是供应商账单截图。",
        "",
        "模型请求别名为 deepseek-v4-flash，供应商返回模型标识见下表。官方说明该旧别名目前由 V4.1 Flash 服务；返回别名不能证明底层权重版本固定，因此未拿 Stage 3.5 旧模型结果做因果对照。[官方价格与别名说明](https://api-docs.deepseek.com/quick_start/pricing/)",
        "",
        "| 批次 | requested model | returned model | 开始/结束（UTC） |",
        "|---|---|---|---|",
    ]
    for p in versions:
        b = read(p)
        lines.append(
            f"| {p.parent.name} | {b['requested_model']} | {', '.join(b['provider_returned_models'])} | {b['started_at']} / {b['finished_at']} |"
        )
    lines += [
        "",
        f"最终 config hash：`{meta['config_hash']}`；Prompt hash：`{meta['prompt_hash']}`；代码版本 hash：`{meta['code_version']}`。每批完整 hash 保存在 batch.json，每 Case 同步记录，逐请求 ledger 另存请求 hash 与 returned model。",
        "",
        "## 证据和复现",
        "",
        "- [总账审计](verification/stage5/final-audit.json)、[实验协议](verification/stage5/PROTOCOL.md)。",
        "- [Baseline](verification/stage5/stage5-baseline-v1-dev/summary.json)、[最终 Test](verification/stage5/stage5-final-v1-test/summary.json)、[采用决策](verification/stage5/adoption.json)。",
        "- 每批 cases/ 保存完整工具/模型 trajectory、数据库 diff、failure_stage/failure_stages/failure_reason；attempts/ 保存实际 HTTP 用量。数据快照 ZIP 可恢复冻结 Case。",
        "- 原实验命令为 `python scripts/stage5.py freeze <version>` 和 `python scripts/stage5.py run <version> --split dev|test`；已有版本拒绝覆盖，已完成 Case 不重发，未完成标记阻止盲目重试。不要删除 Test 标记后重跑正式成绩。",
        "",
        "## 测试与限制",
        "",
        "工程回归：后端 173/173、前端组件 5/5、浏览器 E2E 8/8 通过；Ruff、依赖检查、政策/HTTP/离线 Agent 回归及前端 lint/build 通过。见 [regression-summary.json](verification/stage5/regression-summary.json) 与 [frontend-summary.json](verification/stage5/frontend-summary.json)。浏览器 E2E 使用脚本模型，不计入真实模型成绩。Stage 4 前端与鉴权继续使用原实现。",
        "",
        "本轮不是生产压力测试；Test 每类只有 2 条，分类型比例不稳定。0 次观察到的安全违规不等于绝对安全，应结合置信区间及有限攻击覆盖解读。退款查询固定模板、严格的政策持久化 gold、外部模型版本不可固定、未覆盖全部多轮组合仍是限制。故障注入只能说明这些受控故障下的行为。",
        "",
        "Stage 5 到此停止，没有新增业务模块、Multi-Agent、MCP、长期 Memory 或生产部署。",
    ]
    lines += [
        "",
        "## 每轮 Dev 明细",
        "",
        "| 版本 | Task Success | Token/Case | LLM/Case | Tool/Case | Avg ms |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for batch_path in sorted(OUT.glob("*-dev/summary.json")):
        m = read(batch_path)["overall"]
        lines.append(
            f"| {batch_path.parent.name} | {pct(m['task_success'])} | {m['avg_total_tokens']:.2f} | {m['avg_llm_calls']:.2f} | {m['avg_tool_calls']:.2f} | {m['avg_latency_ms']:.2f} |"
        )
    lines += [
        "",
        "第一轮假设见 [round1-hypothesis.json](verification/stage5/round1-hypothesis.json)；第二轮仅针对 Dev 中错误订单的对象替换问题，见 [round2-hypothesis.json](verification/stage5/round2-hypothesis.json)。每轮整套运行，所有结果保留；最多两轮，没有用 Test 决定改动。",
        "",
        "Baseline 63/75 → 第一轮 70/75；第二轮降至 69/75，按预定标准回滚并采用第一轮。第一轮成功率提高 9.33 个百分点，平均 Tokens 从 6220.99 增至 6685.68（约 +7.47%），平均 LLM 调用从 2.91 降至 2.75；这次主要改善任务正确性，并未实现 Token 成本下降。三批 Dev 加一批 Test 共 275 次 episode 执行，对应 125 个唯一场景。",
        "",
        "数据来源澄清：场景文本由开发助手编写，期望按确定性业务规则定义并在冻结前交叉验证；不是人工标注的真实客户语料，也没有让被测 DeepSeek 自行生成评分答案。协议早期“人工编写”应按此说明理解。",
    ]
    write("STAGE5_EVALUATION.md", lines)
    # Keep the pre-change baseline analysis intact, append final findings once.
    failure_path = ROOT / "docs/STAGE5_FAILURE_ANALYSIS.md"
    old = failure_path.read_text(encoding="utf-8").split("\n## 最终结果")[0]
    lines = [
        old,
        "## 最终结果",
        "",
        f"Dev 采用决策：{chosen}；修复 {len(fixed)} 个，新增失败 {len(regressed)} 个。见采用决策中的配对表和各轮完整结果。",
        "",
        "### Frozen Test 全部失败",
        "",
        "| Case | 类型 | 自动首阶段 | 证据 |",
        "|---|---|---|---|",
    ]
    for r in test_rows:
        if not r["metrics"]["task_success"]:
            lines.append(
                f"| {r['case_id']} | {r['category']} | {r['metrics']['failure_stage']} | [轨迹](verification/stage5/stage5-final-v1-test/cases/{r['case_id']}.json) |"
            )
    lines += [
        "",
        "### 自动失败标签数量",
        "",
        "| 阶段 | Baseline Dev | Final Dev | Test |",
        "|---|---:|---:|---:|",
    ]
    for key in sorted(
        set(baseline["failure_counts"]) | set(dev["failure_counts"]) | set(test["failure_counts"])
    ):
        lines.append(
            f"| {key} | {baseline['failure_counts'].get(key, 0)} | {dev['failure_counts'].get(key, 0)} | {test['failure_counts'].get(key, 0)} |"
        )
    lines += [
        "",
        "同一 Case 可有多个标签，总数不等于失败 Case 数。SUCCESS 不表示工具效率最优。UNKNOWN 保留无法由当前规则完整解释的失败，不修改预期来掩盖。",
        "",
        "### 典型成功证据",
        "",
    ]
    for cat in ["cancel", "high_amount", "not_received", "amount_boundary", "idempotency"]:
        r = next((r for r in test_rows if r["category"] == cat and r["metrics"]["task_success"]), None)
        if r:
            lines.append(
                f"- {cat}：[{r['case_id']}](verification/stage5/stage5-final-v1-test/cases/{r['case_id']}.json)，结果 {r['trajectory'][-1]['run']['outcome']}。"
            )
    lines += [
        "",
        "所有 Test 失败在首次正式结果后直接保留。没有增加修复轮次、修改 expected 或重跑 Test。退款查询的模板限制仍需未来单独获准修复，不能把模型草稿当作已验证事实输出。",
    ]
    write("STAGE5_FAILURE_ANALYSIS.md", lines)
    t = test["overall"]
    ci = t["task_success"]["wilson_95"]
    lines = [
        "# 可用于简历的实测指标",
        "",
        "口径：冻结的 50 个本地合成自然语言 Test episodes，真实 DeepSeek API，一次正式评测。不是线上真实客户指标；所有资金操作为模拟，模型无支付权限。",
        "",
        "| 指标 | 测得结果 |",
        "|---|---|",
        "| Test Case 数量 | 50 |",
    ]
    for k in [
        "task_success",
        "policy_compliance",
        "unsafe_action",
        "approval_recall",
        "tool_selection_accuracy",
    ]:
        lines.append(f"| {labels[k]} | {pct(t[k])} |")
    for k, name in [
        ("avg_tool_calls", "平均 Tool Calls"),
        ("avg_total_tokens", "已报告 Tokens / Case"),
        ("p50_latency_ms", "P50 Latency（ms）"),
        ("p95_latency_ms", "P95 Latency（ms）"),
    ]:
        lines.append(f"| {name} | {t[k]:.2f} |")
    lines += [
        "",
        f"Task Success 的 Wilson 95% 区间为 {ci[0] * 100:.1f}%–{ci[1] * 100:.1f}%。Unsafe 0/50 若成立只表示该样本中未观察到，不等于生产风险为零。",
        "",
        "推荐简历描述：",
        "",
        f"> 开发电商智能售后单 Agent 系统，结合确定性 PolicyEngine、金额校验、服务端角色权限与幂等控制；构建 125 条合成自然语言评测（Dev 75 / Test 50），冻结 Test 单次真实 DeepSeek 评测取得 Task Success {t['task_success']['value'] * 100:.1f}%（{t['task_success']['numerator']}/50），观察到实际不安全动作 {t['unsafe_action']['numerator']}/50，记录逐调用轨迹、Token 与 P50/P95 延迟。",
        "",
        "来源：[最终 Test 汇总](verification/stage5/stage5-final-v1-test/summary.json)、[总审计](verification/stage5/final-audit.json)。不能写成“生产系统准确率”“零风险”“真实支付落地”或把离线测试当真实模型成绩。",
    ]
    write("RESUME_METRICS.md", lines)
    lines = [
        "# Stage 5 项目作品集交接",
        "",
        "## 项目解决什么问题",
        "",
        "AfterSale Copilot 把客户自然语言售后需求转换为可审计的业务建议：先查询订单/物流/商品与政策，再由确定性业务层决定金额、授权动作和是否需要人工。客户可以在中文 Web 门户咨询和看进度，管理员在独立权限下审批、收货和模拟执行。",
        "",
        "## 技术与边界",
        "",
        "FastAPI + SQLite + LangGraph 单 Agent；Next.js / React / TypeScript / Tailwind / shadcn/ui 前端。服务端 Cookie 会话、scrypt 密码、CSRF、归属校验；Agent 工具不含管理员或资金执行入口。PolicyEngine 承担许可判断，RefundCalculator 计算金额，WorkflowService 保持幂等和审计。",
        "",
        "## 最有价值的实验结论",
        "",
        f"最终冻结 Test：Task Success {pct(t['task_success'])}；平均工具调用 {t['avg_tool_calls']:.2f}；平均已报告 Tokens {t['avg_total_tokens']:.2f}。这些结果可追溯到完整 trajectory 与配置、数据集 hash，详细口径见 [评测报告](STAGE5_EVALUATION.md)。",
        "",
        "本次优化针对“正确意思却输出了无效协议”的失败，强化真正调用结束工具与澄清优先级。没有让模型决定金额或执行动作，也没有通过放开自由文本绕过事实约束。真实模型会失败；完整保留失败是作品集可信度的一部分。",
        "",
        "## 推荐演示流程",
        "",
        "1. 按 README 设置本机账号并启动前后端，customer 查询未发货订单并申请取消，说明 READY 不等于已退款。",
        "2. 演示高额退款 WAITING_APPROVAL，admin 核实政策后批准和模拟执行，解释职责分离。",
        "3. 演示签收未收到和主动补问，再由普通客户尝试访问 admin，展示后端拒绝。",
        "4. 打开 Agent Trace、Stage 5 冻结清单和一例成功/失败；说明真实模型评测与脚本 E2E 的区别。",
        "",
        "## 面试时如何解释",
        "",
        "- 为什么不让 LLM 算金额：优惠分摊、额度占用和重复提交需要确定性保证。",
        "- 为什么不以运行 SUCCESS 当总分：正常结束仍可能没有解决诉求；本次退款查询就暴露了该差异。",
        "- 如何防止刷分：先冻结 dataset/expected，Dev 调参，Test 仅一次，保留失败和逐次调用。",
        "- 是否是 RAG：使用小规模版本化政策检索作说明证据，最终许可不由检索文本决定。",
        "- 有什么局限：合成小样本、每类 Test 2 条、外部模型别名变更、非支付生产系统、退款答复模板未覆盖全部查询。",
        "",
        "## 阅读与复现顺序",
        "",
        "先读 [README](../README.md) → [Stage 4 页面与鉴权](STAGE4_HANDOFF.md) → [评测协议](verification/stage5/PROTOCOL.md) → [冻结数据集](../eval/stage5/manifest.json) → scripts/stage5.py → backend/tests/test_stage5.py → 单 Case JSON → 四份报告。模型账本与结果直接保存在 docs/verification/stage5；独立库在 data/stage5，日常库不重置。",
        "",
        "## 交付清单",
        "",
        "- [STAGE5_EVALUATION.md](STAGE5_EVALUATION.md)：所有指标、分类型和模型/配置身份。",
        "- [STAGE5_FAILURE_ANALYSIS.md](STAGE5_FAILURE_ANALYSIS.md)：baseline 分析、优化假设、完整失败与限制。",
        "- 本文：作品集讲解和演示路线。",
        "- [RESUME_METRICS.md](RESUME_METRICS.md)：真实 Test 指标及推荐表述。",
        "",
        "Stage 5 完成后停止开发。未增加 Multi-Agent、MCP、复杂 Memory、新业务或生产部署。",
    ]
    write("STAGE5_PORTFOLIO.md", lines)
    print("Four reports generated; external attempts", len(external), "cost proxy", cost)


if __name__ == "__main__":
    main()
