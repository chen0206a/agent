"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useRef, useState } from "react";
import {
  ArrowRight,
  Headset,
  Package,
  Send,
  ShieldCheck,
  Sparkles,
  Truck,
} from "lucide-react";
import { api, Model } from "@/lib/api";
import {
  actionHint,
  date,
  issueLabels,
  money,
  orderLabels,
  stages,
} from "@/lib/labels";
import { Button } from "./ui/button";
import { Badge, Empty, ErrorBox, Loading, PageTitle, useData } from "./shared";

export function ActionCard({ action }: { action: Model<"ActionRead"> }) {
  const label = stages[action.execution_status];
  return (
    <article className="action-card">
      <div className="row between">
        <strong>售后申请 #{action.id}</strong>
        <Badge tone={action.execution_status === "SUCCESS" ? "mint" : "amber"}>
          {label.label}
        </Badge>
      </div>
      <div className="amount">
        {action.authorized_action === "CREATE_LOGISTICS_TICKET"
          ? "物流调查"
          : money(action.amount)}
      </div>
      <p>{actionHint(action)}</p>
      <small>
        订单 #{action.order_id} · {date(action.created_at)}
      </small>
      {["BLOCKED", "REJECTED"].includes(action.execution_status) && (
        <p>{action.explanation}</p>
      )}
    </article>
  );
}

function Orders({
  userId,
  preview = false,
}: {
  userId: number;
  preview?: boolean;
}) {
  const { data, error, refresh } = useData<Model<"OrderRead">[]>(
    `/users/${userId}/orders`,
  );
  if (error) return <ErrorBox message={error} retry={refresh} />;
  if (!data) return <Loading />;
  if (!data.length) return <Empty>还没有订单，您的订单将显示在这里。</Empty>;
  return (
    <div className={preview ? "order-list" : "order-grid"}>
      {(preview ? data.slice(0, 3) : data).map((order) => (
        <Link
          className="order-card"
          href={`/orders/${order.id}`}
          key={order.id}
        >
          <div className="row between">
            <span className="small muted">订单 #{order.id}</span>
            <Badge tone={order.status === "PAID" ? "mint" : "neutral"}>
              {orderLabels[order.status]}
            </Badge>
          </div>
          <div className="row">
            <div className="product-icon">
              <Package />
            </div>
            <div>
              <strong>订单商品</strong>
              <p>{date(order.created_at)}</p>
            </div>
            <span className="price">{money(order.paid_amount)}</span>
          </div>
          <div className="order-bottom">
            查看商品与物流详情 <ArrowRight size={16} />
          </div>
        </Link>
      ))}
    </div>
  );
}

function OrderDetail({ id }: { id: string }) {
  const order = useData<Model<"OrderRead">>(`/orders/${id}`);
  const items = useData<Model<"ItemRead">[]>(`/orders/${id}/items`);
  const shipment = useData<Model<"ShipmentRead"> | null>(
    `/orders/${id}/shipment`,
  );
  const refunds = useData<Model<"RefundRead">[]>(`/orders/${id}/refunds`);
  if (order.error)
    return <ErrorBox message={order.error} retry={order.refresh} />;
  if (!order.data) return <Loading />;
  const data = order.data;
  return (
    <>
      <PageTitle
        eyebrow="ORDER DETAILS"
        title={`订单 #${id}`}
        description="商品、物流与退款记录，在这里一目了然。"
      >
        <Link className="primary-link" href={`/chat?order=${id}`}>
          申请售后 <ArrowRight size={16} />
        </Link>
      </PageTitle>
      <div className="detail-grid">
        <section className="card">
          <div className="row between">
            <h2>商品清单</h2>
            <Badge tone="mint">{orderLabels[data.status]}</Badge>
          </div>
          {items.error ? (
            <ErrorBox message={items.error} retry={items.refresh} />
          ) : !items.data ? (
            <Loading />
          ) : (
            items.data.map((item) => (
              <div className="item-row" key={item.id}>
                <div className="product-icon">
                  <Package />
                </div>
                <div className="grow">
                  <strong>
                    {item.product_name.split(" / ")[1] || item.product_name}
                  </strong>
                  <p>
                    商品 #{item.id} · {item.category} · 数量 {item.quantity}
                  </p>
                </div>
                <strong>{money(item.paid_amount)}</strong>
              </div>
            ))
          )}
          <div className="payment">
            <span>商品金额</span>
            <span>{money(data.original_amount)}</span>
            <span>优惠抵扣</span>
            <span>−{money(data.discount_amount)}</span>
            <strong>实付金额</strong>
            <strong>{money(data.paid_amount)}</strong>
          </div>
        </section>
        <section className="card">
          <div className="section-icon">
            <Truck />
            <h2>物流进度</h2>
          </div>
          {shipment.error ? (
            <ErrorBox message={shipment.error} retry={shipment.refresh} />
          ) : shipment.data === undefined ? (
            <Loading />
          ) : (
            <>
              <p className="muted">
                {shipment.data
                  ? `${shipment.data.carrier} · ${shipment.data.tracking_number}`
                  : "商品尚未发出，发货后将在这里更新。"}
              </p>
              <ol className="timeline">
                {[
                  ["订单已创建", data.created_at],
                  ["支付完成", data.paid_at],
                  ["包裹已发出", data.shipped_at],
                  ["物流记录已签收", data.delivered_at],
                ]
                  .filter(([, time]) => time)
                  .reverse()
                  .map(([label, time]) => (
                    <li key={label}>
                      <strong>{label}</strong>
                      <p>{date(time)}</p>
                    </li>
                  ))}
              </ol>
              {shipment.data && (
                <div className="notice">
                  {shipment.data.latest_event}
                  <br />
                  物流签收记录不代表您已实际收到商品。
                </div>
              )}
            </>
          )}
        </section>
      </div>
      <section className="card section-gap">
        <h2>退款记录</h2>
        {refunds.error ? (
          <ErrorBox message={refunds.error} retry={refunds.refresh} />
        ) : !refunds.data ? (
          <Loading />
        ) : !refunds.data.length ? (
          <Empty>暂无退款记录。提交申请后可在“售后进度”查看处理阶段。</Empty>
        ) : (
          refunds.data.map((r) => (
            <div className="item-row" key={r.id}>
              <div className="grow">
                <strong>
                  {r.status === "SUCCESS"
                    ? "退款成功（模拟）"
                    : "退款申请处理中"}
                </strong>
                <p>
                  {date(r.updated_at)} · {r.reason}
                </p>
              </div>
              <strong>{money(r.amount)}</strong>
            </div>
          ))
        )}
      </section>
    </>
  );
}

function Requests() {
  const [offset, setOffset] = useState(0);
  const actions = useData<Model<"ActionRead">[]>(
    `/portal/actions?offset=${offset}`,
  );
  const tickets = useData<Model<"TicketRead">[]>(`/tickets?offset=${offset}`);
  return (
    <>
      <PageTitle
        eyebrow="AFTER-SALES PROGRESS"
        title="每一步进度，都清晰可见"
        description="申请已受理、等待审核和退款成功，是不同的处理阶段。"
      />
      <section>
        <h2>售后申请</h2>
        {actions.error ? (
          <ErrorBox message={actions.error} retry={actions.refresh} />
        ) : !actions.data ? (
          <Loading />
        ) : !actions.data.length ? (
          <Empty>暂无售后申请</Empty>
        ) : (
          <div className="order-grid">
            {actions.data.map((a) => (
              <ActionCard key={a.id} action={a} />
            ))}
          </div>
        )}
      </section>
      <section className="card section-gap">
        <h2>我的工单</h2>
        {tickets.error ? (
          <ErrorBox message={tickets.error} retry={tickets.refresh} />
        ) : !tickets.data ? (
          <Loading />
        ) : !tickets.data.length ? (
          <Empty />
        ) : (
          tickets.data.map((t) => (
            <div className="item-row" key={t.id}>
              <span className="product-icon">
                <Headset />
              </span>
              <div className="grow">
                <strong>
                  {issueLabels[t.issue_type]} · 工单 #{t.id}
                </strong>
                <p>{t.description}</p>
                <small>{date(t.updated_at)}</small>
              </div>
              <Badge>
                {
                  (
                    {
                      OPEN: "已受理",
                      IN_PROGRESS: "处理中",
                      WAITING_CUSTOMER: "待补充信息",
                      WAITING_APPROVAL: "待审核",
                      RESOLVED: "已解决",
                      CLOSED: "已关闭",
                    } as const
                  )[t.status]
                }
              </Badge>
            </div>
          ))
        )}
      </section>
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
          disabled={
            (actions.data?.length || 0) < 50 && (tickets.data?.length || 0) < 50
          }
          onClick={() => setOffset((v) => v + 50)}
        >
          下一页
        </Button>
      </div>
    </>
  );
}

function Chat({ userId }: { userId: number }) {
  const search = useSearchParams();
  const [order, setOrder] = useState(search.get("order") || "");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [parent, setParent] = useState<number | null | undefined>();
  const [latest, setLatest] = useState<Model<"ChatResult">>();
  const pending = useRef<Model<"ChatRequest"> | null>(null);
  const orders = useData<Model<"OrderRead">[]>(`/users/${userId}/orders`);
  const history = useData<Model<"RunRead">[]>(
    `/portal/runs?limit=100${order ? `&order_id=${order}` : ""}`,
  );
  async function send(e: React.FormEvent) {
    e.preventDefault();
    if (!message.trim() || busy) return;
    setBusy(true);
    setError("");
    const body: Model<"ChatRequest"> =
      pending.current?.message === message
        ? pending.current
        : {
            message,
            order_id: order ? Number(order) : null,
            parent_run_id:
              parent === undefined ? history.data?.[0]?.id : parent,
            idempotency_key: crypto.randomUUID(),
            evidence_provided: false,
          };
    pending.current = body;
    try {
      let result = await api<Model<"ChatResult">>("/agent/runs", body);
      for (let i = 0; result.status === "RUNNING" && i < 100; i++) {
        await new Promise((r) => setTimeout(r, 1000));
        result = await api<Model<"ChatResult">>(`/agent/runs/${result.run_id}`);
      }
      if (result.status === "RUNNING")
        throw new Error(
          "服务仍在处理中，请稍后使用相同内容重试，系统不会重复提交。",
        );
      setLatest(result);
      setParent(result.run_id);
      setMessage("");
      pending.current = null;
      history.refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <PageTitle
        eyebrow="YOUR AFTER-SALES ASSISTANT"
        title="您好，有什么可以帮您？"
        description="告诉我们遇到的问题，我们会查询订单并协助提交售后申请。"
      />
      <div className="chat-layout">
        <section className="chat-panel">
          <div className="chat-header">
            <span className="assistant-icon">
              <Headset />
            </span>
            <div>
              <strong>售后服务助手</strong>
              <small>
                <span className="live-dot" />
                为您查询与跟进
              </small>
            </div>
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => {
                setParent(null);
                setLatest(undefined);
                pending.current = null;
                setMessage("");
              }}
            >
              新对话
            </Button>
          </div>
          <div className="messages" aria-live="polite">
            <div className="bubble assistant">
              欢迎来到售后服务中心。您可以查询物流、取消未发货订单，或申请退换货。请告诉我订单和具体情况。
            </div>
            {history.error ? (
              <ErrorBox message={history.error} retry={history.refresh} />
            ) : !history.data ? (
              <Loading />
            ) : parent === null ? null : (
              [...history.data].reverse().map((r) => (
                <div key={r.id}>
                  <div className="bubble user">{r.user_query}</div>
                  <div className="bubble assistant">
                    <div>{r.reply || "正在处理…"}</div>
                    <small>{date(r.created_at)}</small>
                  </div>
                </div>
              ))
            )}
            {busy && (
              <div className="bubble assistant">
                <span className="typing">● ● ●</span> 正在查询与核对，请稍候…
              </div>
            )}
            {latest?.action && <ActionCard action={latest.action} />}
          </div>
          <div className="composer">
            <div className="suggestions">
              {[
                "我想取消订单并退款",
                "物流签收了，但我没收到",
                "我需要申请退货",
              ].map((s) => (
                <button key={s} disabled={busy} onClick={() => setMessage(s)}>
                  {s}
                </button>
              ))}
            </div>
            {error && <ErrorBox message={error} />}
            <form onSubmit={send}>
              <textarea
                aria-label="售后消息"
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                placeholder="请描述您的售后问题…"
                maxLength={4000}
                disabled={busy}
                required
              />
              <Button
                type="submit"
                aria-label="发送消息"
                disabled={busy || !message.trim()}
              >
                <Send size={18} />
                发送
              </Button>
            </form>
            <small>
              <ShieldCheck size={12} />
              退款金额与处理结果，以实际售后记录为准。
            </small>
          </div>
        </section>
        <aside className="chat-context">
          <section className="card">
            <h3>本次咨询的订单</h3>
            <p>选择订单，帮助我们更快了解情况。</p>
            <label>
              关联订单
              <select
                aria-label="关联订单"
                value={order}
                disabled={busy}
                onChange={(e) => {
                  setOrder(e.target.value);
                  setParent(null);
                  setLatest(undefined);
                  pending.current = null;
                }}
              >
                <option value="">暂未选择</option>
                {orders.data?.map((o) => (
                  <option key={o.id} value={o.id}>
                    #{o.id} · {orderLabels[o.status]} · {money(o.paid_amount)}
                  </option>
                ))}
              </select>
            </label>
            {orders.error && (
              <ErrorBox message={orders.error} retry={orders.refresh} />
            )}
          </section>
          <section className="care-steps">
            <h3>售后处理流程</h3>
            <ol>
              <li>
                <span>01</span>
                <div>
                  <strong>告诉我们问题</strong>
                  <p>选择订单，描述具体情况</p>
                </div>
              </li>
              <li>
                <span>02</span>
                <div>
                  <strong>核对并提交申请</strong>
                  <p>查询订单与适用售后政策</p>
                </div>
              </li>
              <li>
                <span>03</span>
                <div>
                  <strong>等待处理与更新</strong>
                  <p>审核、退货或退款进度随时可查</p>
                </div>
              </li>
            </ol>
          </section>
          <div className="soft-note">
            <ShieldCheck />
            申请受理不等于退款成功。需要人工审核或退货入库时，我们会明确提示您。
          </div>
        </aside>
      </div>
    </>
  );
}

export function Customer({
  path,
  me,
}: {
  path: string;
  me: Model<"AccountRead">;
}) {
  if (path === "/chat") return <Chat userId={me.user_id!} />;
  if (path.startsWith("/orders/"))
    return <OrderDetail id={path.split("/")[2]} />;
  if (path === "/orders")
    return (
      <>
        <PageTitle
          eyebrow="MY ORDERS"
          title="我的订单"
          description="查看每笔订单，轻松找到需要帮助的商品。"
        />
        <Orders userId={me.user_id!} />
      </>
    );
  if (path === "/requests") return <Requests />;
  return (
    <>
      <PageTitle
        eyebrow="CUSTOMER CARE"
        title="售后有回应，购物更安心"
        description="订单、物流与售后进度，一站式为您跟进。"
      />
      <section className="welcome-card">
        <div>
          <Badge tone="mint">
            <Sparkles size={13} />
            您的专属售后助手
          </Badge>
          <h2>
            遇到问题，
            <br />
            让我们一起解决。
          </h2>
          <p>无需反复查找入口，描述问题即可开始。</p>
          <Link className="primary-link" href="/chat">
            开始售后咨询 <ArrowRight size={17} />
          </Link>
        </div>
        <div className="welcome-art">
          <Headset size={104} strokeWidth={1} />
          <span>
            <ShieldCheck size={16} />
            服务全程可追踪
          </span>
        </div>
      </section>
      <div className="quick-links">
        <Link href="/orders">
          <Package />
          <strong>我的订单</strong>
          <span>查看商品与物流</span>
          <ArrowRight />
        </Link>
        <Link href="/requests">
          <Truck />
          <strong>售后进度</strong>
          <span>查看申请与退款</span>
          <ArrowRight />
        </Link>
      </div>
      <div className="section-heading">
        <h2>最近订单</h2>
        <Link href="/orders">
          查看全部 <ArrowRight size={14} />
        </Link>
      </div>
      <Orders userId={me.user_id!} preview />
    </>
  );
}
