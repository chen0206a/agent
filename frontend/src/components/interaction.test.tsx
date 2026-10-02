import {
  render,
  screen,
  fireEvent,
  waitFor,
  act,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { acquireRead, api, setCsrf, type Model } from "@/lib/api";
import { waitForRun } from "@/lib/run-polling";
import { useData } from "./shared";
import { Customer } from "./customer";
import { Admin } from "./admin";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));
afterEach(() => {
  setCsrf("");
  sessionStorage.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});
const response = (data: unknown, status = 200) => ({
  ok: status < 400,
  status,
  json: async () => data,
});
function Probe() {
  const { data, refreshing, refreshError, refresh } = useData<string>("/probe");
  return (
    <>
      <div>{data || "初次加载"}</div>
      <span>{refreshing ? "正在更新" : "更新结束"}</span>
      <div>{refreshError}</div>
      <button onClick={refresh}>刷新</button>
    </>
  );
}

it("并发 GET 共享请求，一个订阅离开不取消其他读者", async () => {
  let finish!: (value: unknown) => void;
  const fetcher = vi.fn().mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  vi.stubGlobal("fetch", fetcher);
  const a = acquireRead<string>("/same");
  const b = acquireRead<string>("/same");
  expect(fetcher).toHaveBeenCalledTimes(1);
  a.release();
  await Promise.resolve();
  expect(fetcher.mock.calls[0][1].signal.aborted).toBe(false);
  finish(response("共享结果"));
  expect(await b.promise).toBe("共享结果");
  b.release();
});

it("最后一个 GET 订阅离开时取消请求", async () => {
  const fetcher = vi.fn().mockImplementation(
    (_url, init) =>
      new Promise((_resolve, reject) => {
        init.signal.addEventListener("abort", () =>
          reject(new DOMException("Cancelled", "AbortError")),
        );
      }),
  );
  vi.stubGlobal("fetch", fetcher);
  const read = acquireRead("/cancel");
  const rejected = expect(read.promise).rejects.toHaveProperty(
    "name",
    "AbortError",
  );
  read.release();
  await rejected;
  expect(fetcher.mock.calls[0][1].signal.aborted).toBe(true);
});

it("完成的 GET 不作为跨导航缓存，后续读取重新核对服务端", async () => {
  const fetcher = vi.fn().mockResolvedValue(response("结果"));
  vi.stubGlobal("fetch", fetcher);
  const first = acquireRead("/fresh");
  await first.promise;
  first.release();
  const second = acquireRead("/fresh");
  await second.promise;
  second.release();
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("切换会话后丢弃旧 GET，即便 mock 忽略 abort 也不错误注销新会话", async () => {
  let finish!: (value: unknown) => void;
  const expired = vi.fn();
  window.addEventListener("asc:session-expired", expired);
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    ),
  );
  setCsrf("old-session");
  const old = acquireRead("/private");
  const rejected = expect(old.promise).rejects.toHaveProperty(
    "name",
    "AbortError",
  );
  setCsrf("new-session");
  finish(response({}, 401));
  await rejected;
  expect(expired).not.toHaveBeenCalled();
  old.release();
  window.removeEventListener("asc:session-expired", expired);
});

it("业务写入后不能复用写入前的未完成 GET", async () => {
  const fetcher = vi.fn().mockImplementation((_url, init) =>
    init.method === "POST"
      ? Promise.resolve(response({ id: 1 }))
      : new Promise((_resolve, reject) => {
          init.signal.addEventListener("abort", () =>
            reject(new DOMException("Cancelled", "AbortError")),
          );
        }),
  );
  vi.stubGlobal("fetch", fetcher);
  const old = acquireRead("/orders/1001");
  const rejected = expect(old.promise).rejects.toHaveProperty(
    "name",
    "AbortError",
  );
  await api("/agent/runs", { message: "查询", idempotency_key: "same-key" });
  await rejected;
  const current = acquireRead("/orders/1001");
  const secondRejected = expect(current.promise).rejects.toHaveProperty(
    "name",
    "AbortError",
  );
  expect(fetcher).toHaveBeenCalledTimes(3);
  current.release();
  await secondRejected;
  old.release();
});

it("刷新中和刷新失败均保留上次记录，并明确说明数据尚未更新", async () => {
  let finish!: (value: unknown) => void;
  const fetcher = vi
    .fn()
    .mockResolvedValueOnce(response("服务端原记录"))
    .mockImplementation(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
  vi.stubGlobal("fetch", fetcher);
  render(<Probe />);
  await screen.findByText("服务端原记录");
  fireEvent.click(screen.getByText("刷新"));
  expect(screen.getByText("服务端原记录")).toBeVisible();
  expect(screen.getByText("正在更新")).toBeVisible();
  finish(response({ error: { message: "网络暂不可用" } }, 503));
  await screen.findByText("网络暂不可用");
  expect(screen.getByText("服务端原记录")).toBeVisible();
});

it("发送后即刻显示用户消息，不在等待期间虚构退款结果", async () => {
  let finish!: (value: unknown) => void;
  const fetcher = vi.fn().mockImplementation((_url, init) =>
    init.method === "POST"
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : Promise.resolve(response([])),
  );
  vi.stubGlobal("fetch", fetcher);
  render(<Customer path="/chat" me={{ user_id: 1 } as Model<"AccountRead">} />);
  fireEvent.change(screen.getByLabelText("售后消息"), {
    target: { value: "请先核对退款进度" },
  });
  fireEvent.click(screen.getByRole("button", { name: "发送消息" }));
  expect(
    screen.getByText("请先核对退款进度", { selector: ".bubble.user" }),
  ).toBeVisible();
  expect(screen.getByLabelText("售后消息")).toBeDisabled();
  expect(
    screen.queryByText(/退款成功/, { selector: ".messages .bubble.assistant" }),
  ).not.toBeInTheDocument();
  expect(document.querySelector(".action-card")).toBeNull();
  finish(
    response({
      run_id: 77,
      status: "SUCCESS",
      reply: "服务器确认：没有退款记录",
      parent_run_id: null,
      created_at: "2026-10-02T00:00:00Z",
    }),
  );
  await screen.findByText("服务器确认：没有退款记录");
  expect(
    screen.getAllByText("请先核对退款进度", { selector: ".bubble.user" }),
  ).toHaveLength(1);
});

it("离开对话取消浏览器轮询，但保留原请求与已知 run_id", async () => {
  const fetcher = vi
    .fn()
    .mockImplementation((_url, init) =>
      Promise.resolve(
        response(
          init.method === "POST" ? { run_id: 42, status: "RUNNING" } : [],
        ),
      ),
    );
  vi.stubGlobal("fetch", fetcher);
  const view = render(
    <Customer path="/chat" me={{ user_id: 1 } as Model<"AccountRead">} />,
  );
  fireEvent.change(screen.getByLabelText("售后消息"), {
    target: { value: "查询原记录" },
  });
  fireEvent.click(screen.getByRole("button", { name: "发送消息" }));
  await waitFor(() =>
    expect(
      JSON.parse(sessionStorage.getItem("aftersale:pending:1")!).runId,
    ).toBe(42),
  );
  view.unmount();
  await act(() => new Promise((resolve) => setTimeout(resolve, 25)));
  expect(
    fetcher.mock.calls.some((call) => call[0] === "/api/agent/runs/42"),
  ).toBe(false);
  expect(JSON.parse(sessionStorage.getItem("aftersale:pending:1")!).runId).toBe(
    42,
  );
  expect(
    fetcher.mock.calls.find((call) => call[1].method === "POST")![1].signal
      .aborted,
  ).toBe(true);
});

it("隐藏或离线时暂停已知 run_id 的轮询，恢复后只做 GET", async () => {
  vi.useFakeTimers();
  const visibility = vi
    .spyOn(document, "visibilityState", "get")
    .mockReturnValue("hidden");
  const online = vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
  const fetcher = vi
    .fn()
    .mockResolvedValue(response({ run_id: 42, status: "SUCCESS" }));
  vi.stubGlobal("fetch", fetcher);
  const controller = new AbortController();
  const result = waitForRun(
    { run_id: 42, status: "RUNNING" } as Model<"ChatResult">,
    controller.signal,
  );
  await vi.advanceTimersByTimeAsync(1000);
  expect(fetcher).not.toHaveBeenCalled();
  visibility.mockReturnValue("visible");
  document.dispatchEvent(new Event("visibilitychange"));
  await vi.advanceTimersByTimeAsync(0);
  expect(fetcher).not.toHaveBeenCalled();
  online.mockReturnValue(true);
  window.dispatchEvent(new Event("online"));
  expect((await result).status).toBe("SUCCESS");
  expect(fetcher.mock.calls[0][0]).toBe("/api/agent/runs/42");
  expect(fetcher.mock.calls[0][1].method).toBe("GET");
});

it("折叠 Trace 的详细 JSON 在展开前不渲染", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue(
      response({
        run: { status: "SUCCESS", outcome: "ANSWERED", latency_ms: 0 },
        model_calls: [],
        tool_calls: [
          {
            id: 1,
            name: "first",
            status: "SUCCESS",
            arguments: {},
            result: {},
          },
          {
            id: 2,
            name: "second",
            status: "SUCCESS",
            arguments: {},
            result: { marker: "展开后才出现" },
          },
        ],
      }),
    ),
  );
  const view = render(<Admin path="/admin/runs/1" />);
  await screen.findByText("second");
  expect(view.container.querySelectorAll("pre.json")).toHaveLength(2);
  expect(screen.queryByText(/展开后才出现/)).not.toBeInTheDocument();
  const details = view.container.querySelectorAll("details")[1];
  details.open = true;
  fireEvent(details, new Event("toggle"));
  await screen.findByText(/展开后才出现/);
  expect(view.container.querySelectorAll("pre.json")).toHaveLength(4);
});
