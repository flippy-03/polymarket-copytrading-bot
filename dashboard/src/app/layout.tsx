import type { Metadata } from "next";
import "./globals.css";
import Sidebar from "@/components/Sidebar";
import { StrategyProvider } from "@/lib/strategy-context";

export const metadata: Metadata = {
  title: "Polymarket Copytrading",
  description: "Basket Consensus + Scalper Rotator dashboard",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="flex min-h-screen">
        <StrategyProvider>
          <Sidebar />
          <main className="flex-1 ml-56 p-6 overflow-auto">{children}</main>
        </StrategyProvider>
      </body>
    </html>
  );
}
