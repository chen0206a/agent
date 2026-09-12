import { NextRequest } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const maxDuration = 210;

async function proxy(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  const allowed = new Set([
    "auth",
    "portal",
    "users",
    "orders",
    "tickets",
    "actions",
    "approvals",
    "agent",
    "health",
  ]);
  if (
    !allowed.has(path[0]) ||
    path.some((p) => p.includes("..") || p.includes("/") || p.includes("\\"))
  ) {
    return Response.json({ error: { message: "接口不存在" } }, { status: 404 });
  }
  const url = new URL(
    "/" + path.map(encodeURIComponent).join("/"),
    process.env.BACKEND_URL || "http://127.0.0.1:8000",
  );
  url.search = request.nextUrl.search;
  const headers = new Headers();
  for (const key of [
    "content-type",
    "cookie",
    "x-csrf-token",
    "origin",
    "idempotency-key",
  ]) {
    const value = request.headers.get(key);
    if (value) headers.set(key, value);
  }
  try {
    const upstream = await fetch(url, {
      method: request.method,
      headers,
      cache: "no-store",
      redirect: "error",
      body: ["GET", "HEAD"].includes(request.method)
        ? undefined
        : await request.text(),
      signal: AbortSignal.timeout(205000),
    });
    const output = new Headers({
      "Content-Type":
        upstream.headers.get("content-type") || "application/json",
      "Cache-Control": "no-store",
    });
    for (const cookie of upstream.headers.getSetCookie())
      output.append("Set-Cookie", cookie);
    return new Response(upstream.body, {
      status: upstream.status,
      headers: output,
    });
  } catch {
    return Response.json(
      { error: { message: "服务暂时无法连接，请稍后重试" } },
      { status: 502 },
    );
  }
}
export { proxy as GET, proxy as POST, proxy as PATCH };
