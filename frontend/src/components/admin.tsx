"use client";
import Link from "next/link";
import { useState } from "react";
import {
  Activity,
  ArrowRight,
  CheckCircle2,
  Clock3,
  ShieldCheck,
  TicketCheck,
  Zap,
} from "lucide-react";
import { api, Model } from "@/lib/api";
import { actionHint, date, issueLabels, money, stages } from "@/lib/labels";
import {
  Badge,
  Empty,
  ErrorBox,
  JsonView,
  Loading,
  PageTitle,
  useData,
} from "./shared";
import { Button } from "./ui/button";

function Operations({
  action,
  refresh,
}: {
  action: Model<"ActionRead">;
  refresh: () => void;
}) {
  const [mode, setMode] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function execute() {
    setBusy(true);
    setError("");
    try {
      if (mode === "approve" || mode === "reject") {
        let approval: Model<"ApprovalRead"> | undefined;
        for (let offset = 0; ; offset += 100) {
          const page = await api<Model<"ApprovalRead">[]>(
            `/approvals?status=PENDING&limit=100&offset=${offset}`,
          );
          approval = page.find((a) => a.action_request_id === action.id);
          if (approval || page.length < 100) break;
        }
        if (!approval) throw new Error("审批状态已更新，请刷新后查看");
        await api(`/approvals/${approval.id}/review`, {
          approve: mode === "approve",
          reason: note,
        });
      } else if (mode === "return")
        await api(`/actions/${action.id}/return-receipt`, { note });
      else
        await api(`/actions/${action.id}/simulate-execution`, {
          outcome: "SUCCESS",
        });
      setMode("");
      setNote("");
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <div className="operations">
        {action.execution_status === "WAITING_APPROVAL" && (
          <>
            <Button onClick={() => setMode("approve")}>批准申请</Button>
            <Button variant="outline" onClick={() => setMode("reject")}>
              拒绝申请
            </Button>
          </>
        )}
        {action.execution_status === "WAITING_RETURN" && (
          <Button onClick={() => setMode("return")}>确认退货收货</Button>
        )}
        {["READY", "FAILED"].includes(action.execution_status) && (
          <Button onClick={() => setMode("execute")}>模拟执行</Button>
        )}
      </div>
      {mode && (
        <div className="modal-backdrop">
          <section
            className="modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
          >
            <h2 id="confirm-title">
              {
                (
                  {
                    approve: "批准售后申请",
                    reject: "拒绝售后申请",
                    return: "确认仓库收到退货",
                    execute: "确认模拟执行",
                  } as Record<string, string>
                )[mode]
              }
            </h2>
            <p>
              申请 #{action.id} · 订单 #{action.order_id}
            </p>
            <div className="notice">
              {mode === "execute"
                ? "此操作会改变本地业务状态并记录模拟执行结果，不会产生真实资金交易。"
                : "操作将以当前管理员身份记录审计。批准申请不等于已退款。"}
            </div>
            {mode !== "execute" && (
              <label>
                处理说明
                <textarea
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                  placeholder="请填写核验依据或处理原因"
                  maxLength={4000}
                />
              </label>
            )}
            {error && <ErrorBox message={error} />}
            <div className="operations">
              <Button
                variant="outline"
                disabled={busy}
                onClick={() => setMode("")}
              >
                取消
              </Button>
              <Button
                disabled={busy || (mode !== "execute" && !note.trim())}
                onClick={execute}
              >
                {busy ? "处理中…" : "确认操作"}
              </Button>
            </div>
          </section>
        </div>
      )}
    </>
  );
}

function Dashboard() {
  const { data, error, refresh } =
    useData<Model<"DashboardRead">>("/portal/dashboard");
  if (error) return <ErrorBox message={error} retry={refresh} />;
  if (!data) return <Loading />;
  const cards = [
    ["Agent 请求总数", data.total_runs, Activity, "所有已记录运行"],
    ["处理成功", data.successful_runs, CheckCircle2, "运行成功，不代表已退款"],
    [
      "人工审核申请",
      data.human_review_count,
      ShieldCheck,
      "与 Agent 关联的审核申请",
    ],
    [
      "拒绝 / 补问",
      data.rejected_or_clarified_count,
      TicketCheck,
      "安全拒绝、政策拒绝与补问",
    ],
  ] as const;
  return (
    <>
      <PageTitle
        eyebrow="OPERATIONS OVERVIEW"
        title="售后服务，一览全局"
        description="从真实业务记录出发，关注处理质量与每一次客户体验。"
      >
        <Button variant="outline" onClick={refresh}>
          刷新数据
        </Button>
      </PageTitle>
      <div className="metrics">
        {cards.map(([label, value, Icon, hint]) => (
          <section className="metric" key={label}>
            <div className="row between">
              <span>{label}</span>
              <Icon size={19} />
            </div>
            <strong>{value}</strong>
            <small>{hint}</small>
          </section>
        ))}
      </div>
      <div className="dashboard-grid">
        <section className="card">
          <div className="row between">
            <h2>处理效率</h2>
            <Badge>累计数据</Badge>
          </div>
          <div className="rate">
            <div>
              <Zap />
              <span>自动完成建议率</span>
              <strong>{(data.automation_rate * 100).toFixed(1)}%</strong>
            </div>
            <progress max={1} value={data.automation_rate} />
            <p>无需人工审批的有效建议 ÷ 已结束运行；不代表自动退款。</p>
          </div>
          <div className="rate">
            <div>
              <ShieldCheck />
              <span>人工审核率</span>
              <strong>{(data.human_review_rate * 100).toFixed(1)}%</strong>
            </div>
            <progress max={1} value={data.human_review_rate} />
            <p>关联人工审核申请 ÷ 已结束运行。</p>
          </div>
        </section>
        <section className="attention-card">
          <span className="assistant-icon">
            <Clock3 />
          </span>
          <h2>待您处理</h2>
          <div className="attention-count">
            {data.pending_approvals}
            <small>笔待审核申请</small>
          </div>
          <p>
            审核依据、授权金额与政策判断
            <br />
            均可在申请详情中查看。
          </p>
          <Link href="/admin/approvals">
            前往审核队列 <ArrowRight size={17} />
          </Link>
        </section>
      </div>
      <section className="card section-gap">
        <h2>Agent 运行与用量</h2>
        <div className="usage-grid">
          {[
            ["平均模型调用", data.avg_llm_calls.toFixed(2)],
            ["平均工具调用", data.avg_tool_calls.toFixed(2)],
            ["输入 Tokens", data.input_tokens.toLocaleString()],
            ["输出 Tokens", data.output_tokens.toLocaleString()],
            ["平均耗时", `${(data.avg_latency_ms / 1000).toFixed(2)} s`],
            ["运行错误", data.agent_error_count],
          ].map(([label, value]) => (
            <div key={label}>
              <span>{label}</span>
              <strong>{value}</strong>
            </div>
          ))}
        </div>
        <p className="muted small">
          Token 仅统计真实模型已报告用量；{data.unknown_usage_calls}{" "}
          次调用用量未知。平均耗时按已结束运行统计。
        </p>
      </section>
    </>
  );
}

function Tickets() {
  const [offset, setOffset] = useState(0);
  const { data, error, refresh } = useData<Model<"TicketRead">[]>(
    `/tickets?offset=${offset}`,
  );
  return (
    <>
      <PageTitle
        eyebrow="TICKET MANAGEMENT"
        title="工单管理"
        description="查看客户诉求，串联申请、政策与处理过程。"
      />
      {error ? (
        <ErrorBox message={error} retry={refresh} />
      ) : !data ? (
        <Loading />
      ) : (
        <section className="card table-card">
          <table>
            <thead>
              <tr>
                <th>工单 / 订单</th>
                <th>客户</th>
                <th>售后诉求</th>
                <th>状态</th>
                <th>更新时间</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.map((t) => (
                <tr key={t.id}>
                  <td>
                    <strong>#{t.id}</strong>
                    <small>订单 #{t.order_id || "—"}</small>
                  </td>
                  <td>客户 {t.user_id}</td>
                  <td>
                    {issueLabels[t.issue_type]}
                    <small className="truncate">{t.description}</small>
                  </td>
                  <td>
                    <Badge>{t.status}</Badge>
                  </td>
                  <td>{date(t.updated_at)}</td>
                  <td>
                    <Link href={`/admin/tickets/${t.id}`}>查看详情 →</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!data.length && <Empty />}
        </section>
      )}
      <div className="pager">
        <Button
          variant="outline"
          disabled={!offset}
          onClick={() => setOffset((v) => v - 50)}
        >
          上一页
        </Button>
        <Button
          variant="outline"
          disabled={(data?.length || 0) < 50}
          onClick={() => setOffset((v) => v + 50)}
        >
          下一页
        </Button>
      </div>
    </>
  );
}

function ActionDetail({
  action,
  refresh,
}: {
  action: Model<"ActionRead">;
  refresh: () => void;
}) {
  return (
    <section className="card section-gap">
      <div className="row between">
        <h2>申请 #{action.id}</h2>
        <Badge tone="amber">{stages[action.execution_status].label}</Badge>
      </div>
      <div className="policy-grid">
        <div>
          <span>授权金额</span>
          <strong>{money(action.amount)}</strong>
        </div>
        <div>
          <span>政策判断</span>
          <strong>{action.decision}</strong>
        </div>
        <div>
          <span>风险等级</span>
          <strong>{action.risk_level}</strong>
        </div>
        <div>
          <span>授权动作</span>
          <strong>{action.authorized_action || "—"}</strong>
        </div>
      </div>
      <div className="notice">{actionHint(action)}</div>
      <p>{action.explanation}</p>
      <div className="row wrap">
        {action.rule_codes.map((c) => (
          <Badge key={c}>{c}</Badge>
        ))}
        <small>政策版本 {action.policy_version}</small>
      </div>
      <Operations action={action} refresh={refresh} />
      <details>
        <summary>查看政策快照</summary>
        <JsonView value={action.snapshot_json} />
      </details>
    </section>
  );
}
function TicketDetail({ id }: { id: string }) {
  const ticket = useData<Model<"TicketRead">>(`/tickets/${id}`);
  const actions = useData<Model<"ActionRead">[]>(`/tickets/${id}/actions`);
  const runs = useData<Model<"RunRead">[]>("/portal/runs?limit=100");
  if (ticket.error)
    return <ErrorBox message={ticket.error} retry={ticket.refresh} />;
  if (!ticket.data) return <Loading />;
  return (
    <>
      <PageTitle
        eyebrow="TICKET DETAILS"
        title={`工单 #${id}`}
        description={`客户 ${ticket.data.user_id} · 订单 ${ticket.data.order_id} · ${issueLabels[ticket.data.issue_type]}`}
      />
      <section className="card">
        <h2>客户诉求</h2>
        <p>{ticket.data.description}</p>
        <small>{date(ticket.data.created_at)}</small>
      </section>
      {actions.error ? (
        <ErrorBox message={actions.error} retry={actions.refresh} />
      ) : !actions.data ? (
        <Loading />
      ) : !actions.data.length ? (
        <Empty>该工单尚未提交售后申请</Empty>
      ) : (
        actions.data.map((a) => (
          <ActionDetail key={a.id} action={a} refresh={actions.refresh} />
        ))
      )}
      <section className="card section-gap">
        <h2>关联 Agent 运行</h2>
        {runs.error ? (
          <ErrorBox message={runs.error} retry={runs.refresh} />
        ) : !runs.data ? (
          <Loading />
        ) : (
          runs.data
            .filter((r) => r.ticket_id === Number(id))
            .map((r) => (
              <Link
                className="item-row"
                href={`/admin/runs/${r.id}`}
                key={r.id}
              >
                运行 #{r.id} · {r.outcome}
                <ArrowRight size={16} />
              </Link>
            ))
        )}
      </section>
    </>
  );
}

function Approvals() {
  const [filter, setFilter] = useState("pending");
  const [offset, setOffset] = useState(0);
  const requests = useData<Model<"ActionRead">[]>(
    `/portal/actions?offset=${offset}${filter === "high" ? "&risk=HIGH" : filter === "pending" ? "&status=WAITING_APPROVAL" : ""}`,
  );
  return (
    <>
      <PageTitle
        eyebrow="REVIEW & PROCESS"
        title="审核与处理"
        description="核实依据后再做决定。审批、退货收货与模拟执行分别记录。"
      />
      <div className="tabs">
        {[
          ["pending", "待审批申请"],
          ["all", "全部申请"],
          ["high", "高风险申请"],
        ].map(([key, label]) => (
          <button
            key={key}
            className={filter === key ? "selected" : ""}
            onClick={() => {
              setFilter(key);
              setOffset(0);
            }}
          >
            {label}
          </button>
        ))}
      </div>
      {requests.error ? (
        <ErrorBox message={requests.error} retry={requests.refresh} />
      ) : !requests.data ? (
        <Loading />
      ) : !requests.data.length ? (
        <Empty>当前没有待展示的申请</Empty>
      ) : (
        requests.data.map((a) => (
          <div key={a.id}>
            <Link className="small" href={`/admin/tickets/${a.ticket_id}`}>
              查看工单 #{a.ticket_id} →
            </Link>
            <ActionDetail action={a} refresh={requests.refresh} />
          </div>
        ))
      )}
      <div className="pager">
        <Button
          variant="outline"
          disabled={!offset}
          onClick={() => setOffset((v) => v - 50)}
        >
          上一页
        </Button>
        <Button
          variant="outline"
          disabled={(requests.data?.length || 0) < 50}
          onClick={() => setOffset((v) => v + 50)}
        >
          下一页
        </Button>
      </div>
    </>
  );
}

function Runs() {
  const [offset, setOffset] = useState(0);
  const { data, error, refresh } = useData<Model<"RunRead">[]>(
    `/portal/runs?offset=${offset}`,
  );
  return (
    <>
      <PageTitle
        eyebrow="AGENT OBSERVABILITY"
        title="Agent 运行记录"
        description="每一次工具选择、政策判断与业务结果，都可追溯。"
      />
      {error ? (
        <ErrorBox message={error} retry={refresh} />
      ) : !data ? (
        <Loading />
      ) : (
        <section className="card table-card">
          <table>
            <thead>
              <tr>
                <th>运行</th>
                <th>客户诉求</th>
                <th>业务结果</th>
                <th>模型调用</th>
                <th>耗时</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {data.map((r) => (
                <tr key={r.id}>
                  <td>
                    #{r.id}
                    <small>{date(r.created_at)}</small>
                  </td>
                  <td className="truncate">{r.user_query}</td>
                  <td>
                    <Badge tone={r.status === "FAILED" ? "danger" : "mint"}>
                      {r.outcome}
                    </Badge>
                  </td>
                  <td>{r.llm_calls}</td>
                  <td>{(r.latency_ms / 1000).toFixed(2)} s</td>
                  <td>
                    <Link href={`/admin/runs/${r.id}`}>查看 Trace →</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!data.length && <Empty />}
        </section>
      )}
      <div className="pager">
        <Button
          variant="outline"
          disabled={!offset}
          onClick={() => setOffset((v) => v - 50)}
        >
          上一页
        </Button>
        <Button
          variant="outline"
          disabled={(data?.length || 0) < 50}
          onClick={() => setOffset((v) => v + 50)}
        >
          下一页
        </Button>
      </div>
    </>
  );
}

function Trace({ id }: { id: string }) {
  const { data, error, refresh } = useData<Model<"AgentTrace">>(
    `/agent/runs/${id}/trace`,
  );
  if (error) return <ErrorBox message={error} retry={refresh} />;
  if (!data) return <Loading />;
  const run = data.run;
  return (
    <>
      <PageTitle
        eyebrow="AGENT TRACE"
        title={`运行 #${id}`}
        description="展示工具轨迹与执行证据，不展示内部提示词或模型思考内容。"
      />
      <section className="card">
        <div className="row between">
          <h2>运行结果</h2>
          <Badge tone={run.status === "FAILED" ? "danger" : "mint"}>
            {run.outcome}
          </Badge>
        </div>
        <p>{run.reply}</p>
        <div className="usage-grid">
          {[
            ["LLM Calls", run.llm_calls],
            ["Tool Calls", run.tool_calls],
            ["Input Tokens", run.input_tokens ?? "未知"],
            ["Output Tokens", run.output_tokens ?? "未知"],
            ["Latency", `${run.latency_ms} ms`],
            ["模型", run.model],
          ].map(([k, v]) => (
            <div key={k}>
              <span>{k}</span>
              <strong>{v}</strong>
            </div>
          ))}
        </div>
        {run.error_type && <ErrorBox message={run.error_type} />}
      </section>
      {run.action && <ActionDetail action={run.action} refresh={refresh} />}
      <section className="card section-gap">
        <h2>工具调用轨迹</h2>
        {!data.tool_calls.length ? (
          <Empty>没有工具调用</Empty>
        ) : (
          data.tool_calls.map((call, index) => (
            <details className="trace-step" key={index} open={index === 0}>
              <summary>
                <span className="step-number">{index + 1}</span>
                <strong>{String(call.name)}</strong>
                <Badge>{String(call.status)}</Badge>
                <small>{String(call.latency_ms)} ms</small>
              </summary>
              <div className="trace-columns">
                <div>
                  <h3>Tool Arguments</h3>
                  <JsonView value={call.arguments} />
                </div>
                <div>
                  <h3>Tool Results</h3>
                  <JsonView value={call.result} />
                </div>
              </div>
            </details>
          ))
        )}
      </section>
      <section className="card section-gap">
        <h2>模型调用用量</h2>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>轮次</th>
                <th>输入</th>
                <th>输出</th>
                <th>耗时</th>
                <th>状态</th>
              </tr>
            </thead>
            <tbody>
              {data.model_calls.map((c, i) => (
                <tr key={i}>
                  <td>{String(c.sequence)}</td>
                  <td>{String(c.input_tokens ?? "未知")}</td>
                  <td>{String(c.output_tokens ?? "未知")}</td>
                  <td>{String(c.latency_ms)} ms</td>
                  <td>{String(c.status)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

export function Admin({ path }: { path: string }) {
  if (path.startsWith("/admin/tickets/"))
    return <TicketDetail id={path.split("/")[3]} />;
  if (path === "/admin/tickets") return <Tickets />;
  if (path === "/admin/approvals") return <Approvals />;
  if (path.startsWith("/admin/runs/")) return <Trace id={path.split("/")[3]} />;
  if (path === "/admin/runs") return <Runs />;
  return <Dashboard />;
}
