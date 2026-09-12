import { test, expect, Page } from "@playwright/test";
import path from "node:path";
const screenshots = path.resolve("../docs/verification/stage4/screenshots");
async function login(page: Page, username: string) {
  await page.goto("/login");
  await page.getByLabel("账号", { exact: true }).fill(username);
  await page
    .getByLabel("密码", { exact: true })
    .fill(
      username === "admin" ? "E2e-admin-password-42" : "E2e-only-password-42",
    );
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByLabel("退出登录")).toBeVisible();
}
async function chat(
  page: Page,
  user: string,
  order: number | null,
  message: string,
) {
  await login(page, user);
  await page.goto(order ? `/chat?order=${order}` : "/chat");
  await page.getByRole("textbox", { name: "售后消息" }).fill(message);
  await page.getByRole("button", { name: "发送消息" }).click();
  await expect(page.getByRole("button", { name: "发送消息" })).toBeDisabled();
  await expect(page.getByRole("textbox", { name: "售后消息" })).toHaveValue("");
}
test("登录页截图与未登录保护", async ({ page }) => {
  await page.goto("/orders");
  await expect(page).toHaveURL(/login/);
  await page.screenshot({
    path: path.join(screenshots, "01-login.png"),
    fullPage: true,
  });
  expect(
    (
      await page.request.get("/api/orders/1001", {
        headers: { "X-Demo-Role": "admin", "X-Demo-User-Id": "1" },
      })
    ).status(),
  ).toBe(401);
});
test("A 普通未发货取消退款；刷新保留状态", async ({ page }) => {
  await chat(page, "customer1", 1001, "请取消订单1001并退款");
  await expect(
    page.getByText("申请已通过，等待处理，尚未退款", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: path.join(screenshots, "03-chat.png"),
    fullPage: true,
  });
  await page.goto("/requests");
  await expect(
    page.getByText("¥112.97", { exact: true }).first(),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByText("申请已通过，等待处理，尚未退款", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: path.join(screenshots, "04-progress.png"),
    fullPage: true,
  });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "售后有回应，购物更安心" }),
  ).toBeVisible();
  await page.screenshot({
    path: path.join(screenshots, "02-customer-home.png"),
    fullPage: true,
  });
});
test("B 高金额退款→人工审批→模拟执行", async ({ page }) => {
  await chat(page, "customer6", 1006, "订单1006不想要了，取消并退款");
  await expect(
    page.getByText("退款申请已提交，正在等待人工审核", { exact: true }),
  ).toBeVisible();
  const actions = await (await page.request.get("/api/portal/actions")).json();
  const action = actions[0];
  await page.getByLabel("退出登录").click();
  await login(page, "admin");
  await page.goto("/admin/approvals");
  await expect(page.getByRole("button", { name: "待审批申请", exact: true })).toHaveClass("selected");
  await expect(page.getByRole("button", { name: "批准申请", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "高风险申请", exact: true }).click();
  await expect(page.getByRole("button", { name: "批准申请", exact: true })).toBeVisible();
  await page.screenshot({ path: path.join(screenshots, "11-approval-queue.png"), fullPage: true });
  await page.goto(`/admin/tickets/${action.ticket_id}`);
  await page.getByRole("button", { name: "批准申请", exact: true }).click();
  await page.getByLabel("处理说明").fill("已核验订单及退款依据");
  await page.getByRole("button", { name: "确认操作" }).click();
  await page.getByRole("button", { name: "模拟执行", exact: true }).click();
  await page.getByRole("button", { name: "确认操作" }).click();
  await expect(
    page.getByText("退款成功（模拟），款项已按申请金额记录", { exact: true }),
  ).toBeVisible();
  const saved = await (
    await page.request.get(`/api/actions/${action.id}`)
  ).json();
  expect(saved.execution_status).toBe("SUCCESS");
  expect(saved.amount).toBe("2512.98");
  await page.screenshot({
    path: path.join(screenshots, "06-admin-ticket.png"),
    fullPage: true,
  });
});
test("C 签收未收到→物流调查", async ({ page }) => {
  await chat(page, "customer10", 1010, "物流显示签收但我没收到，申请退款");
  await expect(
    page.getByText("已提交物流调查建议，等待客服处理；未退款", { exact: true }),
  ).toBeVisible();
  await page.goto("/orders/1010");
  await expect(page.getByText("物流记录已签收", { exact: true })).toBeVisible();
  await page.screenshot({
    path: path.join(screenshots, "05-order.png"),
    fullPage: true,
  });
});
test("D 信息不足→补问→多轮续聊", async ({ page }) => {
  await chat(page, "customer4", null, "我想取消订单，尚未选择具体订单");
  await expect(
    page.getByText("请提供需要处理的订单号，或先选择您自己的订单。", {
      exact: true,
    }),
  ).toBeVisible();
  const first = await (await page.request.get("/api/portal/runs")).json();
  await page
    .getByRole("textbox", { name: "售后消息" })
    .fill("订单1014，请查询并取消");
  await page.getByRole("button", { name: "发送消息" }).click();
  await expect(page.getByRole("textbox", { name: "售后消息" })).toHaveValue("");
  const second = await (await page.request.get("/api/portal/runs")).json();
  expect(second[0].parent_run_id).toBe(first[0].id);
});
test("E/F 越权API和管理员页面被拒绝", async ({ page }) => {
  await login(page, "customer2");
  expect((await page.request.get("/api/orders/1001")).status()).toBe(403);
  expect(
    (
      await page.request.get("/api/approvals", {
        headers: { "X-Demo-Role": "admin" },
      })
    ).status(),
  ).toBe(403);
  expect((await page.request.get("/api/agent/runs/1/trace")).status()).toBe(
    403,
  );
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "无权访问" })).toBeVisible();
  await page.screenshot({
    path: path.join(screenshots, "09-access-denied.png"),
    fullPage: true,
  });
});
test("退货收货→执行；管理员Trace与实时统计", async ({ page }) => {
  await chat(page, "customer3", 1003, "订单1003商品10031退一件，无理由退货");
  await expect(
    page.getByText("等待仓库确认收到退货，尚未退款", { exact: true }),
  ).toBeVisible();
  const action = (
    await (await page.request.get("/api/portal/actions")).json()
  )[0];
  await page.getByLabel("退出登录").click();
  await login(page, "admin");
  await page.goto(`/admin/tickets/${action.ticket_id}`);
  await page.getByRole("button", { name: "确认退货收货", exact: true }).click();
  await page.getByLabel("处理说明").fill("仓库已核对商品与数量");
  await page.getByRole("button", { name: "确认操作" }).click();
  await page.getByRole("button", { name: "模拟执行", exact: true }).click();
  await page.getByRole("button", { name: "确认操作" }).click();
  await expect(
    page.getByText("退款成功（模拟），款项已按申请金额记录", { exact: true }),
  ).toBeVisible();
  await page.goto("/admin");
  await expect(
    page.getByRole("heading", { name: "售后服务，一览全局" }),
  ).toBeVisible();
  await page.screenshot({
    path: path.join(screenshots, "07-dashboard.png"),
    fullPage: true,
  });
  const stats = await (await page.request.get("/api/portal/dashboard")).json();
  expect(stats.total_runs).toBeGreaterThanOrEqual(6);
  expect(stats.input_tokens).toBe(0);
  await page.goto("/admin/runs");
  await expect(page.getByRole("link", { name: "查看 Trace →" }).first()).toBeVisible();
  await page.screenshot({ path: path.join(screenshots, "12-run-list.png"), fullPage: true });
  await page.goto("/admin/runs/1");
  await expect(
    page.getByRole("heading", { name: "工具调用轨迹" }),
  ).toBeVisible();
  const trace = await (
    await page.request.get("/api/agent/runs/1/trace")
  ).json();
  expect(JSON.stringify(trace)).not.toContain('"role":"system"');
  expect(JSON.stringify(trace)).not.toContain("reasoning_content");
  await page.screenshot({
    path: path.join(screenshots, "08-trace.png"),
    fullPage: true,
  });
});
test("手机宽度与退出登录", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await login(page, "customer5");
  await page.goto("/orders");
  await expect(page.getByRole("heading", { name: "我的订单" })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: path.join(screenshots, "10-mobile.png"),
    fullPage: true,
  });
  await page.getByLabel("退出登录").click();
  await expect(page).toHaveURL(/login/);
  expect((await page.request.get("/api/auth/me")).status()).toBe(401);
});
