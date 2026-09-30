import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { ActionCard, Customer } from "./customer";
import Portal from "./portal";
import { Admin } from "./admin";
import { api, setCsrf } from "@/lib/api";
import type { Model } from "@/lib/api";
import { useData } from "./shared";
const navigation = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => "/login",
  useRouter: () => navigation,
  useSearchParams: () => new URLSearchParams(),
}));
afterEach(() => {
  sessionStorage.clear();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  setCsrf("");
});

const pastRuns = [
  {
    id: 10,
    order_id: 1001,
    user_query: "最新的补问",
    reply: "请说明诉求",
    parent_run_id: 8,
    status: "SUCCESS",
  },
  {
    id: 9,
    order_id: 1011,
    user_query: "无关的另一段对话",
    reply: "历史回复",
    parent_run_id: null,
    status: "SUCCESS",
  },
  {
    id: 8,
    order_id: 1001,
    user_query: "原始咨询",
    reply: "请提供订单",
    parent_run_id: null,
    status: "SUCCESS",
  },
];

it.each(["new", "resume", "switch"])(
  "历史上下文需显式续聊：%s",
  async (mode) => {
    const fetcher = vi.fn().mockImplementation(async (url, init) => {
      if (init?.method === "POST") throw new Error("请求中断");
      return {
        ok: true,
        json: async () =>
          url.includes("/users/")
            ? [
                { id: 1001, status: "PAID", paid_amount: "112.97" },
                { id: 1011, status: "DELIVERED", paid_amount: "112.97" },
              ]
            : pastRuns,
      };
    });
    vi.stubGlobal("fetch", fetcher);
    render(
      <Customer path="/chat" me={{ user_id: 1 } as Model<"AccountRead">} />,
    );
    const resume = await screen.findByRole("button", { name: "继续最近对话" });
    if (mode !== "new") {
      fireEvent.click(resume);
      await waitFor(() =>
        expect(screen.queryByText("无关的另一段对话")).not.toBeInTheDocument(),
      );
    }
    if (mode === "switch")
      fireEvent.change(screen.getByLabelText("关联订单"), {
        target: { value: "1011" },
      });
    fireEvent.change(screen.getByLabelText("售后消息"), {
      target: { value: "先查一下" },
    });
    fireEvent.click(screen.getByRole("button", { name: "发送消息" }));
    await screen.findByText("请求中断");
    const body = JSON.parse(
      fetcher.mock.calls.find((c) => c[1]?.method === "POST")![1].body,
    );
    expect(body.parent_run_id).toBe(mode === "resume" ? 10 : null);
    expect(body.order_id).toBe(
      mode === "resume" ? 1001 : mode === "switch" ? 1011 : null,
    );
  },
);
const action = {
  id: 1,
  order_id: 1001,
  amount: "112.97",
  execution_status: "READY",
  authorized_action: "CANCEL_AND_REFUND",
  created_at: "2026-09-09T12:00:00Z",
} as Model<"ActionRead">;

function DataProbe({ path }: { path: string }) {
  const { data } = useData<string>(path);
  return <div>{data ?? "等待新订单数据"}</div>;
}

it("切换查询路径时不会把上一订单的数据当成当前结果", async () => {
  let resolve!: (value: unknown) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(async (url) => {
      if (url === "/api/order-a")
        return { ok: true, json: async () => "订单A数据" };
      return new Promise((r) => {
        resolve = r;
      });
    }),
  );
  const view = render(<DataProbe path="/order-a" />);
  await screen.findByText("订单A数据");
  view.rerender(<DataProbe path="/order-b" />);
  expect(screen.queryByText("订单A数据")).not.toBeInTheDocument();
  expect(screen.getByText("等待新订单数据")).toBeVisible();
  resolve({ ok: true, json: async () => "订单B数据" });
  await screen.findByText("订单B数据");
});
describe("真实业务状态文案", () => {
  it("申请通过不能展示退款成功", () => {
    render(<ActionCard action={action} />);
    expect(screen.getByText("申请已通过，等待处理，尚未退款")).toBeVisible();
    expect(screen.queryByText(/退款成功/)).not.toBeInTheDocument();
  });
  it("仅执行成功才显示退款成功", () => {
    render(
      <ActionCard
        action={{
          ...action,
          execution_status: "SUCCESS",
          final_action: "CANCEL_AND_REFUND",
        }}
      />,
    );
    expect(screen.getByText(/退款成功（模拟）/)).toBeVisible();
  });
  it("物流执行成功不能冒充退款成功", () => {
    render(
      <ActionCard
        action={{
          ...action,
          authorized_action: "CREATE_LOGISTICS_TICKET",
          execution_status: "SUCCESS",
        }}
      />,
    );
    expect(screen.getByText(/仍需等待调查结果；未退款/)).toBeVisible();
    expect(screen.queryByText(/退款成功/)).not.toBeInTheDocument();
  });
});
it("登录错误可见且密码不会作为URL或身份参数发送", async () => {
  const fetcher = vi.fn().mockResolvedValue({
    ok: false,
    status: 401,
    json: async () => ({ error: { message: "账号或密码不正确" } }),
  });
  vi.stubGlobal("fetch", fetcher);
  render(<Portal />);
  await screen.findByLabelText("账号");
  fireEvent.change(screen.getByLabelText("账号"), {
    target: { value: "customer1" },
  });
  fireEvent.change(screen.getByLabelText("密码"), {
    target: { value: "incorrect-password" },
  });
  fireEvent.click(screen.getByRole("button", { name: "登录" }));
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent("账号或密码不正确"),
  );
  const call = fetcher.mock.calls.find((c) => c[0] === "/api/auth/login")!;
  expect(JSON.parse(call[1].body)).toEqual({
    username: "customer1",
    password: "incorrect-password",
  });
  expect(call[1].headers).not.toHaveProperty("X-Demo-Role");
});
it("API写入携带CSRF并保留Cookie；不替用户决定金额", async () => {
  const fetcher = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ id: 7 }),
  });
  vi.stubGlobal("fetch", fetcher);
  setCsrf("test-csrf");
  await api("/agent/runs", {
    message: "取消订单",
    idempotency_key: "fixed-key",
  });
  expect(fetcher.mock.calls[0][1].credentials).toBe("same-origin");
  expect(fetcher.mock.calls[0][1].headers["X-CSRF-Token"]).toBe("test-csrf");
  expect(fetcher.mock.calls[0][1].body).not.toContain("amount");
});

it("咨询模式发送后端约束，失败重试保留原请求", async () => {
  const fetcher = vi.fn().mockImplementation(async (_url, init) => {
    if (init?.method === "POST") throw new Error("连接中断");
    return { ok: true, status: 200, json: async () => [] };
  });
  vi.stubGlobal("fetch", fetcher);
  render(<Customer path="/chat" me={{ user_id: 1 } as Model<"AccountRead">} />);
  const mode = screen.getByRole("checkbox", { name: "仅咨询，不提交申请" });
  fireEvent.click(mode);
  fireEvent.change(screen.getByLabelText("售后消息"), {
    target: { value: "能退款吗" },
  });
  fireEvent.click(screen.getByRole("button", { name: "发送消息" }));
  await screen.findByText("连接中断");
  expect(mode).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "发送消息" }));
  await waitFor(() =>
    expect(
      fetcher.mock.calls.filter((c) => c[1]?.method === "POST"),
    ).toHaveLength(2),
  );
  const calls = fetcher.mock.calls.filter((c) => c[1]?.method === "POST");
  expect(JSON.parse(calls[0][1].body).read_only).toBe(true);
  expect(calls[0][1].body).toBe(calls[1][1].body);
  expect(screen.getByRole("button", { name: "新对话" })).toBeDisabled();
  expect(screen.getByLabelText("售后消息")).toBeDisabled();
  expect(screen.getByLabelText("关联订单")).toBeDisabled();
});

it("已获得运行编号时断线重试只查询原运行，不重复POST", async () => {
  let queries = 0;
  const fetcher = vi.fn().mockImplementation(async (url, init) => {
    if (init?.method === "POST")
      return {
        ok: true,
        json: async () => ({ run_id: 77, status: "RUNNING" }),
      };
    if (url === "/api/agent/runs/77") {
      if (++queries === 1) throw new Error("查询连接中断");
      return {
        ok: true,
        json: async () => ({
          run_id: 77,
          status: "SUCCESS",
          reply: "已完成查询",
        }),
      };
    }
    return { ok: true, json: async () => [] };
  });
  vi.stubGlobal("fetch", fetcher);
  render(<Customer path="/chat" me={{ user_id: 1 } as Model<"AccountRead">} />);
  fireEvent.change(screen.getByLabelText("售后消息"), {
    target: { value: "查进度" },
  });
  fireEvent.click(screen.getByRole("button", { name: "发送消息" }));
  await screen.findByText("查询连接中断", {}, { timeout: 3000 });
  fireEvent.click(screen.getByRole("button", { name: "发送消息" }));
  await waitFor(() =>
    expect(screen.getByLabelText("售后消息")).toHaveValue(""),
  );
  expect(
    fetcher.mock.calls.filter((c) => c[1]?.method === "POST"),
  ).toHaveLength(1);
  expect(queries).toBe(2);
  expect(screen.getByRole("button", { name: "新对话" })).toBeEnabled();
});

it("运行失败但申请已落库时保留申请卡片，不把失败当成未提交", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(async (_url, init) => ({
      ok: true,
      json: async () =>
        init?.method === "POST" ? { run_id: 99, status: "FAILED", action } : [],
    })),
  );
  render(<Customer path="/chat" me={{ user_id: 1 } as Model<"AccountRead">} />);
  fireEvent.change(screen.getByLabelText("售后消息"), {
    target: { value: "取消退款" },
  });
  fireEvent.click(screen.getByRole("button", { name: "发送消息" }));
  await screen.findByText(/已有售后申请已保留/);
  expect(screen.getByText("申请已通过，等待处理，尚未退款")).toBeVisible();
  expect(sessionStorage.getItem("aftersale:pending:1")).toBeNull();
});

it("管理员恢复操作遵守后端活跃运行保护，不调用执行接口", async () => {
  const fetcher = vi
    .fn()
    .mockImplementation(async (_url, init) =>
      init?.method === "POST"
        ? {
            ok: false,
            status: 409,
            json: async () => ({
              error: {
                code: "RUN_STILL_ACTIVE",
                message: "运行仍可能活跃，暂不能恢复",
              },
            }),
          }
        : {
            ok: true,
            json: async () => ({
              run: {
                run_id: 8,
                status: "RUNNING",
                outcome: "RUNNING",
                action: null,
              },
              tool_calls: [],
              model_calls: [],
            }),
          },
    );
  vi.stubGlobal("fetch", fetcher);
  render(<Admin path="/admin/runs/8" />);
  fireEvent.click(
    await screen.findByRole("button", { name: "核对并恢复中断记录" }),
  );
  await screen.findByText("运行仍可能活跃，暂不能恢复");
  expect(
    fetcher.mock.calls.filter((c) => c[1]?.method === "POST").map((c) => c[0]),
  ).toEqual(["/api/agent/runs/8/recover"]);
});
