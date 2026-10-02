import { api, type Model } from "./api";

export function delay(ms: number, signal: AbortSignal) {
  return new Promise<void>((resolve, reject) => {
    if (signal.aborted)
      return reject(new DOMException("Wait cancelled", "AbortError"));
    const abort = () => {
      clearTimeout(timer);
      reject(new DOMException("Wait cancelled", "AbortError"));
    };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", abort);
      resolve();
    }, ms);
    signal.addEventListener("abort", abort, { once: true });
  });
}

async function visibleAndOnline(signal: AbortSignal) {
  const ready = () => document.visibilityState !== "hidden" && navigator.onLine;
  if (signal.aborted) throw new DOMException("Wait cancelled", "AbortError");
  if (ready()) return;
  await new Promise<void>((resolve, reject) => {
    const clean = () => {
      window.removeEventListener("online", check);
      document.removeEventListener("visibilitychange", check);
      signal.removeEventListener("abort", abort);
    };
    const check = () => {
      if (ready()) {
        clean();
        resolve();
      }
    };
    const abort = () => {
      clean();
      reject(new DOMException("Wait cancelled", "AbortError"));
    };
    window.addEventListener("online", check);
    document.addEventListener("visibilitychange", check);
    signal.addEventListener("abort", abort, { once: true });
  });
}

// Never POST from a polling loop. Browser cancellation does not cancel backend business work.
export async function waitForRun(
  initial: Model<"ChatResult">,
  signal: AbortSignal,
) {
  let result = initial;
  const end = Date.now() + 120_000;
  for (let attempt = 0; result.status === "RUNNING"; attempt++) {
    await delay(Math.min(1000 * 1.5 ** attempt, 4000), signal);
    await visibleAndOnline(signal);
    result = await api<Model<"ChatResult">>(
      `/agent/runs/${initial.run_id}`,
      undefined,
      "GET",
      { signal },
    );
    if (result.status === "RUNNING" && Date.now() >= end)
      throw new Error(
        "服务仍在处理中，请稍后查询原请求结果，系统不会重复提交。",
      );
  }
  return result;
}
