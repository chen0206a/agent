import type { components } from "./generated";
export type Model<K extends keyof components["schemas"]> =
  components["schemas"][K];
let csrf = "";
export const setCsrf = (value: string) => {
  csrf = value;
};
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
  ) {
    super(message);
  }
}
export async function api<T>(
  path: string,
  body?: unknown,
  method = body === undefined ? "GET" : "POST",
): Promise<T> {
  const response = await fetch(`/api${path}`, {
    method,
    credentials: "same-origin",
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...(csrf ? { "X-CSRF-Token": csrf } : {}),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    if (response.status === 401 && path !== "/auth/login" && typeof window !== "undefined") {
      window.dispatchEvent(new Event("asc:session-expired"));
    }
    const error = await response.json().catch(() => null);
    throw new ApiError(
      error?.error?.message || "请求未完成，请重试",
      response.status,
    );
  }
  return response.status === 204 ? (undefined as T) : response.json();
}
