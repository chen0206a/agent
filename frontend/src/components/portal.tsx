"use client";
import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  ArrowUpRight,
  Box,
  ChartNoAxesCombined,
  Headset,
  LayoutDashboard,
  LogOut,
  MessagesSquare,
  Package,
  ShieldCheck,
  TicketCheck,
  Workflow,
} from "lucide-react";
import { api, Model, setCsrf } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Badge, ErrorBox, Loading } from "./shared";
import { Customer } from "./customer";
import { Admin } from "./admin";

function Login({ onLogin }: { onLogin: (me: Model<"AccountRead">) => void }) {
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError("");
    try {
      onLogin(
        await api<Model<"AccountRead">>("/auth/login", {
          username: form.get("username"),
          password: form.get("password"),
        }),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="login">
      <section className="login-story">
        <div className="brand">
          <span className="logo">
            <Headset />
          </span>
          AfterSale<span className="brand-light">Copilot</span>
        </div>
        <div className="story-copy">
          <Badge tone="mint">让每一次售后，都有回应</Badge>
          <h1>
            好服务，
            <br />
            不止于签收。
          </h1>
          <p>
            从订单查询到售后处理，
            <br />
            我们陪您走好每一步。
          </p>
          <div className="parcel-art">
            <Box size={108} strokeWidth={1} />
            <span className="art-note">
              <ShieldCheck size={19} />
              进度清晰 · 服务安心
            </span>
          </div>
        </div>
        <div className="story-bottom">
          AFTERSALE / CUSTOMER CARE <span>01 — 04</span>
        </div>
      </section>
      <section className="login-form">
        <div className="login-card">
          <div className="eyebrow">WELCOME BACK</div>
          <h2>欢迎回来</h2>
          <p>登录您的账户，继续查看订单与售后进度。</p>
          <form onSubmit={submit}>
            <label>
              账号
              <input
                name="username"
                autoComplete="username"
                placeholder="请输入您的账号"
                required
                maxLength={80}
              />
            </label>
            <label>
              密码
              <input
                name="password"
                type="password"
                autoComplete="current-password"
                placeholder="请输入密码"
                required
                maxLength={128}
              />
            </label>
            {error && <ErrorBox message={error} />}
            <Button type="submit" disabled={busy} className="wide">
              {busy ? "正在登录…" : "登录"}
              <ArrowUpRight size={18} />
            </Button>
          </form>
          <div className="login-note">
            <ShieldCheck size={16} />
            您的订单与售后记录仅对本人和授权客服可见。
          </div>
          <p className="setup-note">首次使用？请由本机维护者初始化账户。</p>
        </div>
        <footer>本地演示环境 · 不产生真实资金交易</footer>
      </section>
    </div>
  );
}

function Workspace() {
  const path = usePathname();
  const router = useRouter();
  const [me, setMe] = useState<Model<"AccountRead"> | null>();
  useEffect(() => {
    const expired = () => {
      setCsrf("");
      setMe(null);
    };
    window.addEventListener("asc:session-expired", expired);
    return () => window.removeEventListener("asc:session-expired", expired);
  }, []);

  const [error, setError] = useState("");
  useEffect(() => {
    api<Model<"AccountRead">>("/auth/me")
      .then((v) => {
        setCsrf(v.csrf_token);
        setMe(v);
      })
      .catch(() => setMe(null));
  }, []);
  useEffect(() => {
    if (me === null && path !== "/login") router.replace("/login");
    if (me && path === "/login")
      router.replace(me.role === "admin" ? "/admin" : "/");
  }, [me, path, router]);
  function signedIn(v: Model<"AccountRead">) {
    setCsrf(v.csrf_token);
    setMe(v);
    router.replace(v.role === "admin" ? "/admin" : "/");
  }
  if (me === undefined) return <Loading />;
  if (!me) return <Login onLogin={signedIn} />;
  const admin = me.role === "admin";
  const nav = admin
    ? ([
        ["/admin", "工作概览", LayoutDashboard],
        ["/admin/tickets", "工单管理", TicketCheck],
        ["/admin/approvals", "审核与处理", ShieldCheck],
        ["/admin/runs", "Agent 运行", Workflow],
      ] as const)
    : ([
        ["/", "服务中心", Headset],
        ["/chat", "售后咨询", MessagesSquare],
        ["/orders", "我的订单", Package],
        ["/requests", "售后进度", TicketCheck],
      ] as const);
  return (
    <div className="workspace">
      <aside className="sidebar">
        <Link href={admin ? "/admin" : "/"} className="brand">
          <span className="logo">
            <Headset />
          </span>
          <span>
            AfterSale<small>Copilot</small>
          </span>
        </Link>
        <div className="nav-caption">
          {admin ? "SERVICE OPERATIONS" : "CUSTOMER CENTER"}
        </div>
        <nav>
          {nav.map(([href, name, Icon]) => {
            const active =
              path === href ||
              (href !== "/" &&
                href !== "/admin" &&
                path.startsWith(href + "/"));
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={active ? "active" : ""}
              >
                <Icon size={19} />
                {name}
              </Link>
            );
          })}
        </nav>
        <div className="sidebar-bottom">
          <div className="care-box">
            <ShieldCheck />
            <strong>
              {admin ? "每个决定，都有据可查" : "安心服务，全程相伴"}
            </strong>
            <p>
              {admin
                ? "审批、收货与执行各自留痕"
                : "申请、审核与退款进度清晰可见"}
            </p>
          </div>
          <div className="profile">
            <span className="avatar">{admin ? "管" : "客"}</span>
            <div>
              <strong>{me.username}</strong>
              <small>{admin ? "服务管理员" : "客户账户"}</small>
            </div>
            <button
              aria-label="退出登录"
              onClick={async () => {
                try {
                  await api("/auth/logout", {});
                  setCsrf("");
                  setMe(null);
                } catch (e) {
                  setError((e as Error).message);
                }
              }}
            >
              <LogOut size={18} />
            </button>
          </div>
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          <span>
            <span className="live-dot" />{" "}
            {admin ? "售后运营工作台" : "您的专属售后服务"}
          </span>
          <span>
            <ChartNoAxesCombined size={16} />{" "}
            {admin ? "数据实时读取" : "服务始终在线"}
            <Badge>本地演示</Badge>
          </span>
        </header>
        <main>
          {error && <ErrorBox message={error} />}
          <div key={path}>
            {!admin && path.startsWith("/admin") ? (
              <section className="card">
                <h1>无权访问</h1>
                <p>此页面仅管理员可见。</p>
                <Link href="/">返回服务中心</Link>
              </section>
            ) : admin ? (
              <Admin path={path} />
            ) : (
              <Customer path={path} me={me} />
            )}
          </div>
        </main>
        <footer className="page-footer">
          AfterSale Copilot · 本地模拟售后服务{" "}
          <span>申请通过不等于退款成功</span>
        </footer>
      </div>
    </div>
  );
}
export default function Portal() {
  return (
    <Suspense fallback={<Loading />}>
      <Workspace />
    </Suspense>
  );
}
