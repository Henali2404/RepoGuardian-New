"use client";

import React, { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { supabase } from "@/lib/supabase";

export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [status, setStatus] = useState<"loading" | "authenticated" | "unauthenticated">("loading");

  useEffect(() => {
    let mounted = true;
    const publicRoute = pathname === "/" || pathname === "/login" || pathname === "/signup" || pathname === "/auth";

    supabase.auth.getSession().then(({ data: { session } }) => {
      if (!mounted) return;
      setStatus(session ? "authenticated" : "unauthenticated");
      if (!session && !publicRoute) {
        router.replace("/login");
        return;
      }
    });

    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      if (!mounted) return;
      setStatus(session ? "authenticated" : "unauthenticated");
      if (!session && !publicRoute) router.replace("/login");
    });
    return () => { mounted = false; subscription.unsubscribe(); };
  }, [pathname, router]);

  const publicRoute = pathname === "/" || pathname === "/login" || pathname === "/signup" || pathname === "/auth";
  if (status === "loading" || (!publicRoute && status !== "authenticated")) {
    return <main className="min-h-screen flex items-center justify-center bg-[#020817] text-cyan-400">Checking session...</main>;
  }
  return <>{children}</>;
}
