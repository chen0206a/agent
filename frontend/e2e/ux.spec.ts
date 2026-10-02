import { test, expect, type Page } from "@playwright/test";
import { writeFileSync, mkdirSync } from "node:fs";
import path from "node:path";

const mode = process.env.UX_MEASURE_MODE || "optimized";
const output = path.resolve(
  process.env.E2E_OUTPUT_DIR || "../docs/verification/frontend-ux",
);
async function record(name: string, value: unknown) {
  mkdirSync(output, { recursive: true });
  writeFileSync(
    path.join(output, `${name}.json`),
    JSON.stringify({ mode, ...(value as object) }, null, 2),
  );
}
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
  await expect(
    page.getByRole("heading", {
      name:
        username === "admin" ? "售后服务，一览全局" : "售后有回应，购物更安心",
    }),
  ).toBeVisible();
}

test("UX navigation measurement with the same local fixture", async ({
  page,
}) => {
  await login(page, "customer9");
  let checks = 0;
  page.on("request", (request) => {
    if (request.url().endsWith("/api/auth/me")) checks++;
  });
  const samples = [];
  for (const [name, heading] of [
    ["我的订单", "我的订单"],
    ["售后进度", "每一步进度，都清晰可见"],
    ["服务中心", "售后有回应，购物更安心"],
    ["售后咨询", "您好，有什么可以帮您？"],
    ["我的订单", "我的订单"],
  ]) {
    const start = performance.now();
    await page
      .locator(".sidebar nav")
      .getByRole("link", { name, exact: true })
      .click();
    await expect(page.getByRole("heading", { name: heading })).toBeVisible();
    samples.push({ name, heading_latency_ms: performance.now() - start });
  }
  await record("navigation", { auth_me_requests: checks, samples });
  if (mode !== "baseline") expect(checks).toBe(0);
});

test("UX immediate message feedback under a held response", async ({
  page,
}) => {
  await login(page, "customer9");
  await page.goto("/chat?order=1009");
  await page.getByRole("checkbox", { name: "仅咨询，不提交申请" }).check();
  const query = "查询退款进度，交互测量";
  await page.route("**/api/agent/runs", async (route) => {
    const response = await route.fetch();
    await new Promise((resolve) => setTimeout(resolve, 1200));
    await route.fulfill({ response });
  });
  await page.getByLabel("售后消息").fill(query);
  const start = performance.now();
  await page.getByRole("button", { name: "发送消息" }).click();
  await page.waitForTimeout(150);
  const early = await page
    .locator(".messages .bubble.user")
    .filter({ hasText: query })
    .count();
  const beforeReply = {
    visible_after_150ms: early > 0,
    textarea_locked: await page.getByLabel("售后消息").isDisabled(),
  };
  await expect(
    page.locator(".messages .bubble.user").filter({ hasText: query }),
  ).toBeVisible();
  const feedback = performance.now() - start;
  if (mode !== "baseline")
    await page.screenshot({
      path: path.join(output, "customer-pending.png"),
      fullPage: true,
    });
  await expect(page.getByLabel("售后消息")).toHaveValue("");
  await expect(page.getByText(/订单 1009 当前没有退款记录/)).toBeVisible();
  await record("chat-feedback", {
    ...beforeReply,
    message_feedback_ms: feedback,
    injected_response_delay_ms: 1200,
  });
  if (mode !== "baseline") expect(beforeReply.visible_after_150ms).toBe(true);
});

test("UX known run recovery after navigation stays GET-only", async ({
  page,
}) => {
  test.skip(mode === "baseline");
  await login(page, "customer8");
  await page.goto("/chat?order=1008");
  await page.getByRole("checkbox", { name: "仅咨询，不提交申请" }).check();
  let posts = 0;
  page.on("request", (request) => {
    if (
      request.method() === "POST" &&
      request.url().endsWith("/api/agent/runs")
    )
      posts++;
  });
  await page.route("**/api/agent/runs", async (route) => {
    const response = await route.fetch();
    const result = await response.json();
    await route.fulfill({
      json: { ...result, status: "RUNNING", outcome: "RUNNING", reply: "" },
    });
  });
  await page.getByLabel("售后消息").fill("查询退款进度，离开页面后恢复");
  await page.getByLabel("售后消息").press("Control+Enter");
  await expect
    .poll(() =>
      page.evaluate(
        () =>
          JSON.parse(sessionStorage.getItem("aftersale:pending:8") || "null")
            ?.runId,
      ),
    )
    .toBeGreaterThan(0);
  const saved = await page.evaluate(() =>
    JSON.parse(sessionStorage.getItem("aftersale:pending:8")!),
  );
  await page
    .locator(".sidebar nav")
    .getByRole("link", { name: "我的订单", exact: true })
    .click();
  await expect(page.getByRole("heading", { name: "我的订单" })).toBeVisible();
  await page.waitForTimeout(1200);
  await page
    .locator(".sidebar nav")
    .getByRole("link", { name: "售后咨询", exact: true })
    .click();
  await page.getByRole("button", { name: "恢复待确认请求" }).click();
  await expect(page.getByLabel("售后消息")).toHaveValue("");
  await expect(page.getByText(/退款处理中，尚未确认成功/)).toBeVisible();
  expect(posts).toBe(1);
  expect(
    await page.evaluate(() => sessionStorage.getItem("aftersale:pending:8")),
  ).toBeNull();
  await record("navigation-recovery", {
    original_run_id: saved.runId,
    post_count: posts,
    original_request_preserved: true,
  });
});

test("UX incoming history does not steal scroll; reduced motion respected", async ({
  page,
}) => {
  test.skip(mode === "baseline");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await login(page, "customer9");
  let reads = 0;
  await page.route("**/api/portal/runs?limit=100*", (route) => {
    reads++;
    return route.fulfill({
      json: Array.from({ length: reads === 1 ? 60 : 61 }, (_, i) => ({
        id: 10000 - i,
        user_id: 9,
        order_id: 1009,
        status: "SUCCESS",
        outcome: "ANSWERED",
        parent_run_id: null,
        user_query: `长记录受控夹具 ${i}`,
        reply: "这条数据仅用于验证长列表滚动行为。",
        created_at: "2026-10-02T00:00:00Z",
      })).map((run, i) =>
        i === 0 && reads > 1
          ? { ...run, id: 10001, reply: "新记录已更新" }
          : run,
      ),
    });
  });
  await page.goto("/chat?order=1009");
  await expect(
    page.getByText("长记录受控夹具 0", { exact: true }),
  ).toBeVisible();
  const log = page.getByRole("log", { name: "售后对话" });
  await log.evaluate((element) => {
    element.scrollTop = 0;
    element.dispatchEvent(new Event("scroll"));
  });
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(
    page.getByRole("button", { name: "查看最新消息" }),
  ).toBeVisible();
  expect(await log.evaluate((element) => element.scrollTop)).toBe(0);
  await page.getByRole("button", { name: "查看最新消息" }).click();
  await expect
    .poll(() =>
      log.evaluate(
        (element) =>
          element.scrollHeight - element.clientHeight - element.scrollTop,
      ),
    )
    .toBeLessThan(72);
  expect(
    await page
      .locator(".page-enter")
      .evaluate((element) => getComputedStyle(element).animationName),
  ).toBe("none");
  await record("scroll", {
    controlled_history_records: 61,
    preserved_reading_position: true,
    jump_to_latest: true,
    reduced_motion: true,
  });
});

test("UX logout removes privileged views and unknown paths remain 404", async ({
  page,
}) => {
  test.skip(mode === "baseline");
  await login(page, "admin");
  await page
    .locator(".sidebar nav")
    .getByRole("link", { name: "Agent 运行", exact: true })
    .click();
  await expect(
    page.getByRole("heading", { name: "Agent 运行记录" }),
  ).toBeVisible();
  await page.getByLabel("退出登录").click();
  await login(page, "customer2");
  await page.goto("/admin/runs");
  await expect(page.getByRole("heading", { name: "无权访问" })).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Agent 运行记录" }),
  ).not.toBeVisible();
  await page.goto("/does-not-exist");
  await expect(
    page.getByRole("heading", { name: "404", exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel("退出登录")).not.toBeVisible();
});

test("UX collapsed Trace DOM measurement with controlled large payload", async ({
  page,
}) => {
  await login(page, "admin");
  await page.route("**/api/agent/runs/900/trace", (route) =>
    route.fulfill({
      json: {
        run: {
          run_id: 900,
          status: "SUCCESS",
          outcome: "ANSWERED",
          reply: "仅用于渲染性能测试的受控数据",
          llm_calls: 0,
          tool_calls: 80,
          latency_ms: 0,
          model: "NOT-A-REAL-MODEL",
        },
        model_calls: [],
        tool_calls: Array.from({ length: 80 }, (_, i) => ({
          name: `fixture_tool_${i}`,
          status: "SUCCESS",
          latency_ms: 0,
          arguments: { order_id: 1001 },
          result: { fixture: "受控测试数据".repeat(800) },
        })),
      },
    }),
  );
  await page.goto("/admin/runs/900");
  await expect(
    page.getByRole("heading", { name: "工具调用轨迹" }),
  ).toBeVisible();
  const initial = await page.locator("pre.json").count();
  await page.locator(".trace-step summary").last().click();
  if (mode !== "baseline")
    await expect(page.locator("pre.json")).toHaveCount(4);
  const expanded = await page.locator("pre.json").count();
  await record("trace-dom", {
    synthetic_tool_calls: 80,
    initially_rendered_json_blocks: initial,
    after_last_expand_json_blocks: expanded,
  });
  if (mode !== "baseline") {
    expect(initial).toBe(2);
    expect(expanded).toBe(4);
  }
});
