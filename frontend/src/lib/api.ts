import type { components } from "./generated";
export type Model<K extends keyof components["schemas"]> =
  components["schemas"][K];
let csrf = "";
let generation = 0;
type ReadEntry = {
  controller: AbortController;
  promise: Promise<unknown>;
  readers: number;
};
const reads = new Map<string, ReadEntry>();
export function invalidateReads() {
  generation++;
  for (const entry of reads.values()) entry.controller.abort();
  reads.clear();
  if (typeof window !== "undefined")
    window.dispatchEvent(new Event("asc:data-changed"));
}
export const setCsrf = (value: string) => {
  if (csrf !== value || !value) invalidateReads();
  csrf = value;
};

// In-flight GET sharing only. No completed responses or private data survive a session reset.
export function acquireRead<T>(path: string) {
  let entry = reads.get(path);
  if (!entry) {
    const controller = new AbortController();
    const epoch = generation;
    const created: ReadEntry = {
      controller,
      readers: 0,
      promise: Promise.resolve(),
    };
    created.promise = api<T>(path, undefined, "GET", {
      signal: controller.signal,
    })
      .then((value) => {
        if (epoch !== generation || controller.signal.aborted)
          throw new DOMException("Read cancelled", "AbortError");
        return value;
      })
      .finally(() => {
        if (reads.get(path) === created) reads.delete(path);
      });
    reads.set(path, created);
    entry = created;
  }
  entry.readers++;
  const acquired = entry;
  let released = false;
  return {
    promise: acquired.promise as Promise<T>,
    release() {
      if (released) return;
      released = true;
      acquired.readers--;
      queueMicrotask(() => {
        if (!acquired.readers && reads.get(path) === acquired) {
          reads.delete(path);
          acquired.controller.abort();
        }
      });
    },
  };
}
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: string,
  ) {
    super(message);
  }
}
export async function api<T>(
  path: string,
  body?: unknown,
  method = body === undefined ? "GET" : "POST",
  options: { signal?: AbortSignal } = {},
): Promise<T> {
  const epoch = generation;
  const response = await fetch(`/api${path}`, {
    method,
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
    signal: options.signal,
  });
  if (options.signal?.aborted || (method === "GET" && epoch !== generation))
    throw new DOMException("Request cancelled", "AbortError");
  if (!response.ok) {
    if (
      response.status === 401 &&
      epoch === generation &&
      path !== "/auth/login" &&
      typeof window !== "undefined"
    ) {
      window.dispatchEvent(new Event("asc:session-expired"));
    }
    const error = await response.json().catch(() => null);
    throw new ApiError(
      error?.error?.message || "请求未完成，请重试",
      response.status,
      error?.error?.code,
    );
  }
  const value =
    response.status === 204 ? (undefined as T) : await response.json();
  if (method !== "GET" && !path.startsWith("/auth/")) invalidateReads();
  return value;
}
