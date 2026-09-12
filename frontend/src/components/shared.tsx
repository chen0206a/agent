"use client";
import { useEffect, useState } from "react";
import { LoaderCircle, AlertCircle, PackageOpen } from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";

export function useData<T>(path: string) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState("");
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let active = true;
    api<T>(path)
      .then((v) => {
        if (active) {
          setData(v);
          setError("");
        }
      })
      .catch((e) => {
        if (active) setError(e.message);
      });
    return () => {
      active = false;
    };
  }, [path, version]);
  return {
    data,
    error,
    refresh: () => {
      setError("");
      setVersion((v) => v + 1);
    },
  };
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
