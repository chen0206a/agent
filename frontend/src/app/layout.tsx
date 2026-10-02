import type { Metadata } from "next";
import "./globals.css";
import "./apple-inspired.css";
import "./interaction.css";
import Portal from "@/components/portal";
export const metadata: Metadata = {
  title: "AfterSale Copilot · 售后服务中心",
  description: "订单、物流与售后服务，全程安心相伴。",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body>
        <Portal>{children}</Portal>
      </body>
    </html>
  );
}
