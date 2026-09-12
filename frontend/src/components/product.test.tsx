import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { ActionCard } from "./customer";
import Portal from "./portal";
import { api, setCsrf } from "@/lib/api";
import type { Model } from "@/lib/api";
const navigation = vi.hoisted(() => ({ replace: vi.fn() }));
vi.mock("next/navigation", () => ({
  usePathname: () => "/login",
  useRouter: () => navigation,
  useSearchParams: () => new URLSearchParams(),
}));
afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  setCsrf("");
});
const action = {
  id: 1,
  order_id: 1001,
  amount: "112.97",
  execution_status: "READY",
  authorized_action: "CANCEL_AND_REFUND",
  created_at: "2026-09-09T12:00:00Z",
} as Model<"ActionRead">;
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
  const fetcher = vi
    .fn()
    .mockResolvedValue({
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
  const fetcher = vi
    .fn()
    .mockResolvedValue({
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
