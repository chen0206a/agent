"use client";
import { useSyncExternalStore } from "react";
import type { Model } from "./api";

export type PendingRequest = {
  request: Model<"ChatRequest">;
  runId: number | null;
};
const event = "aftersale:pending-request";
const key = (userId: number) => `aftersale:pending:${userId}`;
function subscribe(callback: () => void) {
  window.addEventListener(event, callback);
  window.addEventListener("storage", callback);
  return () => {
    window.removeEventListener(event, callback);
    window.removeEventListener("storage", callback);
  };
}
function snapshot(userId: number) {
  try {
    return sessionStorage.getItem(key(userId));
  } catch {
    return null;
  }
}
export function savePending(userId: number, value: PendingRequest | null) {
  try {
    if (value) sessionStorage.setItem(key(userId), JSON.stringify(value));
    else sessionStorage.removeItem(key(userId));
  } catch {
    /* Storage-disabled browsers retain the in-page retry protection. */
  }
  window.dispatchEvent(new Event(event));
}
export function usePending(userId: number): PendingRequest | null {
  const raw = useSyncExternalStore(
    subscribe,
    () => snapshot(userId),
    () => null,
  );
  try {
    const parsed = raw ? JSON.parse(raw) : null;
    return typeof parsed?.request?.message === "string" &&
      typeof parsed.request.idempotency_key === "string" &&
      (parsed.runId === null || Number.isSafeInteger(parsed.runId))
      ? parsed
      : null;
  } catch {
    return null;
  }
}
