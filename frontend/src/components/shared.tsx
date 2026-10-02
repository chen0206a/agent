"use client";
import { useEffect, useState } from "react";
import { LoaderCircle, AlertCircle, PackageOpen } from "lucide-react";
import { acquireRead } from "@/lib/api";
import { Button } from "@/components/ui/button";

export function useData<T>(path: string) {
  const [snapshot, setSnapshot] = useState<{
    path: string;
    data?: T;
    error: string;
    version: number;
  }>();
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let active = true;
    const read = acquireRead<T>(path);
    read.promise
      .then((v) => {
        if (active) {
          setSnapshot({ path, data: v, error: "", version });
        }
      })
      .catch((e) => {
        if (active && e.name !== "AbortError")
          setSnapshot((current) => ({
            path,
            data: current?.path === path ? current.data : undefined,
            error: e.message,
            version,
          }));
      });
    return () => {
      active = false;
      read.release();
    };
  }, [path, version]);
  useEffect(() => {
    const refresh = () => {
      if (document.visibilityState !== "hidden") setVersion((v) => v + 1);
    };
    window.addEventListener("asc:data-changed", refresh);
    window.addEventListener("online", refresh);
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      window.removeEventListener("asc:data-changed", refresh);
      window.removeEventListener("online", refresh);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, []);
  const current = snapshot?.path === path ? snapshot : undefined;
  return {
    data: current?.data,
    error: current?.data === undefined ? current?.error || "" : "",
    refreshError: current?.data !== undefined ? current.error : "",
    refreshing: !current || current.version !== version,
    refresh: () => {
      setSnapshot((current) =>
        current?.path === path ? { ...current, error: "" } : current,
      );
      setVersion((v) => v + 1);
    },
  };
}
export function RefreshStatus({
  refreshing,
  error,
}: {
  refreshing: boolean;
  error?: string;
}) {
  return (
    <div className="refresh-status" role="status">
      {error
        ? `更新未完成，当前显示上次记录：${error}`
        : refreshing
          ? "正在更新记录…"
          : ""}
    </div>
  );
}
export function Loading() {
  return (
    <div className="state" role="status">
      <LoaderCircle className="spin" />
      正在加载，请稍候…
    </div>
  );
}
export function Empty({
  children = "这里还没有记录",
}: {
  children?: React.ReactNode;
}) {
  return (
    <div className="state">
      <PackageOpen />
      <span>{children}</span>
    </div>
  );
}
export function ErrorBox({
  message,
  retry,
}: {
  message: string;
  retry?: () => void;
}) {
  return (
    <div className="error" role="alert">
      <AlertCircle size={18} />
      <span>{message}</span>
      {retry && (
        <Button variant="outline" onClick={retry}>
          重试
        </Button>
      )}
    </div>
  );
}
export function Badge({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: string;
}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
export function PageTitle({
  eyebrow,
  title,
  description,
  children,
}: {
  eyebrow: string;
  title: string;
  description: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="page-title">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {children}
    </div>
  );
}
export function JsonView({ value }: { value: unknown }) {
  return <pre className="json">{JSON.stringify(value, null, 2)}</pre>;
}
