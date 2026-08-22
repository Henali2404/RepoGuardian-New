"use client";

import { useEffect, useState } from "react";
import { supabase, signOut, getUser } from "@/lib/supabase";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { User } from "@supabase/supabase-js";

export default function Header() {
  const [user, setUser] = useState<User | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const pathname = usePathname();

  useEffect(() => {
    // Get current logged-in user
    getUser().then(setUser);

    // Listen to Auth state changes
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user ?? null);
    });

    return () => subscription.unsubscribe();
  }, []);

  const nav = [
    { href: "/analysis", label: "Analysis" },
    { href: "/history", label: "History" },
    { href: "/reports", label: "Reports" },
    { href: "/settings", label: "Settings" },
  ];
  const displayName = user?.user_metadata?.display_name || user?.email?.split("@")[0] || "Account";

  return (
    <header className="app-header">
      <div className="app-header-inner">
        <Link href="/analysis" className="brand-mark"><span className="brand-shield">RG</span><span>RepoGuardian</span></Link>
        <nav className="main-nav" aria-label="Primary navigation">
          {nav.map((item) => <Link key={item.href} href={item.href} className={pathname === item.href ? "nav-link active" : "nav-link"}>{item.label}</Link>)}
        </nav>
        {user && <div className="account-area">
          <button type="button" className="icon-button" title="Notifications" aria-label="Notifications">◎<span className="notification-dot" /></button>
          <div className="account-menu-wrap">
            <button type="button" className="account-button" onClick={() => setMenuOpen(!menuOpen)} aria-expanded={menuOpen}>
              <span className="avatar">{displayName.slice(0, 1).toUpperCase()}</span><span className="account-name">{displayName}</span><span className="chevron">⌄</span>
            </button>
            {menuOpen && <div className="account-menu">
              <Link href="/settings" onClick={() => setMenuOpen(false)}>Profile</Link>
              <Link href="/settings" onClick={() => setMenuOpen(false)}>Settings</Link>
              <button onClick={async () => { await signOut(); window.location.replace("/login"); }}>Sign Out</button>
            </div>}
          </div>
        </div>}
      </div>
    </header>
  );
}
