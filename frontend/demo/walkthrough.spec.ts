import { test, expect } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";

const output = path.resolve(
  process.env.E2E_OUTPUT_DIR || "../docs/verification/portfolio-demo",
);

test("中文售后产品完整演示：客户申请、人工审批、模拟执行与安全边界", async ({
  page,
}) => {
  const start = Date.now();
  const steps: { name: string; elapsed_ms: number; url: string }[] = [];
  const snapshot = async (name: string) => {
    mkdirSync(path.join(output, "screenshots"), { recursive: true });
    await page.screenshot({
      path: path.join(output, "screenshots", `${name}.png`),
      fullPage: true,
    });
    steps.push({ name, elapsed_ms: Date.now() - start, url: page.url() });
  };
  async function login(username: string) {
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
  async function logout() {
    await page.getByLabel("退出登录").click();
    await expect(
      page.getByRole("button", { name: "登录", exact: true }),
    ).toBeVisible();
  }
  async function send(message: string, order?: number) {
    await page.goto(order ? `/chat?order=${order}` : "/chat");
    await page.getByLabel("售后消息").fill(message);
    await page.getByRole("button", { name: "发送消息" }).click();
  }

  await login("customer1");
  await page.goto("/orders");
  await expect(page.getByRole("heading", { name: "我的订单" })).toBeVisible();
  await snapshot("01-orders");
  await send("请为1001正式提交未发货取消退款申请", 1001);
  await expect(
    page.getByText("申请已通过，等待处理，尚未退款", { exact: true }),
  ).toBeVisible();
  const cancelRun = (
    await (await page.request.get("/api/portal/runs")).json()
  )[0];
  await snapshot("02-cancel-application");
  await page.goto("/requests");
  await expect(
    page.getByText("¥112.97", { exact: true }).first(),
  ).toBeVisible();
  await snapshot("03-customer-progress");
  await logout();

  await login("customer6");
  await send("1006不需要了，明确申请取消退款，等待人工审批", 1006);
  await expect(
    page.getByText("退款申请已提交，正在等待人工审核", { exact: true }),
  ).toBeVisible();
  const high = (
    await (await page.request.get("/api/portal/actions")).json()
  )[0];
  expect(high.execution_status).toBe("WAITING_APPROVAL");
  expect(high.amount).toBe("2512.98");
  await snapshot("04-high-amount-pending");
  await logout();

  await login("admin");
  await page.goto("/admin/approvals");
  await expect(
    page.getByRole("button", { name: "批准申请", exact: true }),
  ).toBeVisible();
  await snapshot("05-admin-approval");
  await page.goto(`/admin/tickets/${high.ticket_id}`);
  await page.getByRole("button", { name: "批准申请", exact: true }).click();
  await page
    .getByLabel("处理说明")
    .fill("演示核验：订单、政策与实付金额符合申请，批准后仍需单独执行。");
  await page.getByRole("button", { name: "确认操作" }).click();
  await expect(
    page.getByRole("button", { name: "模拟执行", exact: true }),
  ).toBeEnabled();
  const approved = await (
    await page.request.get(`/api/actions/${high.id}`)
  ).json();
  expect(approved.execution_status).toBe("READY");
  await snapshot("06-approved-not-refunded");
  await page.getByRole("button", { name: "模拟执行", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("不会产生真实资金交易");
  await page.getByRole("button", { name: "确认操作" }).click();
  await expect(
    page.getByText("退款成功（模拟），款项已按申请金额记录", { exact: true }),
  ).toBeVisible();
  const executed = await (
    await page.request.get(`/api/actions/${high.id}`)
  ).json();
  expect(executed.execution_status).toBe("SUCCESS");
  expect(executed.amount).toBe("2512.98");
  await snapshot("07-simulated-success");
  await page.goto(`/admin/runs/${cancelRun.id}`);
  await expect(
    page.getByRole("heading", { name: "工具调用轨迹" }),
  ).toBeVisible();
  const trace = await (
    await page.request.get(`/api/agent/runs/${cancelRun.id}/trace`)
  ).json();
  expect(JSON.stringify(trace)).not.toContain('"role":"system"');
  expect(JSON.stringify(trace)).not.toContain("reasoning_content");
  await snapshot("08-tool-policy-trace");
  await logout();

  await login("customer10");
  await send("1010签收了但实际没收到，请提交物流调查", 1010);
  await expect(
    page.getByText("已提交物流调查建议，等待客服处理；未退款", { exact: true }),
  ).toBeVisible();
  await snapshot("09-logistics-investigation");
  await logout();

  await login("customer4");
  await send("我想取消退款，但暂时没有提供具体订单");
  await expect(
    page.getByText("请提供需要处理的订单号，或先选择您自己的订单。", {
      exact: true,
    }),
  ).toBeVisible();
  await snapshot("10-clarification");
  await logout();

  await login("customer2");
  expect((await page.request.get("/api/orders/1001")).status()).toBe(403);
  expect((await page.request.get("/api/approvals")).status()).toBe(403);
  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "无权访问" })).toBeVisible();
  await snapshot("11-access-denied");
  writeFileSync(
    path.join(output, "walkthrough.json"),
    JSON.stringify(
      {
        mode: "real-browser-isolated-scripted-demo",
        model: "NOT-A-REAL-MODEL",
        paid_api_calls: 0,
        real_payment: false,
        recorded_at: new Date().toISOString(),
        viewport: { width: 1440, height: 1000 },
        steps,
        assertions: {
          cancellation_ready: true,
          high_amount_approval: true,
          approval_is_not_execution: true,
          simulated_execution: true,
          clarification: true,
          logistics: true,
          forbidden_api: true,
          admin_only_trace: true,
        },
      },
      null,
      2,
    ),
  );
});
