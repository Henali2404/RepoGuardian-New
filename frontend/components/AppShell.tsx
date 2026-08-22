"use client";

import { usePathname } from "next/navigation";
import Header from "@/components/Header";

const appRoutes = ["/analysis", "/history", "/reports", "/settings", "/dashboard", "/analyze"];

function isApplicationRoute(pathname: string) {
  return appRoutes.some((route) => pathname === route || pathname.startsWith(`${route}/`));
}

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const inApplication = isApplicationRoute(pathname);

  return (
    <div className={inApplication ? "app-shell" : "app-shell standalone-shell"}>
      {inApplication && <Header />}
      <main className={inApplication ? "app-content" : "standalone-content"}>{children}</main>
    </div>
  );
}
