"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { supabase } from "@/lib/supabase";

const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

type AuthMode = "login" | "signup";

export default function AuthForm({ mode }: { mode: AuthMode }) {
  const router = useRouter();
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [rememberMe, setRememberMe] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    setMessage("");
    if (mode === "signup") {
      if (fullName.trim().length < 2) return setError("Enter your full name.");
      if (password.length < 8) return setError("Password must be at least 8 characters.");
      if (!/[A-Z]/.test(password) || !/[0-9]/.test(password)) return setError("Password must include an uppercase letter and a number.");
      if (password !== confirmPassword) return setError("Passwords do not match.");
    }
    setLoading(true);
    try {
      if (mode === "login") {
        const response = await fetch(`${BACKEND}/auth/login`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password }),
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.detail || "Invalid email or password.");
        const { data: sessionData, error: sessionError } = await supabase.auth.setSession({
          access_token: body.access_token,
          refresh_token: body.refresh_token,
        });
        if (sessionError) throw sessionError;
        if (!sessionData.session) throw new Error("Authentication session could not be created.");
        router.replace("/analysis");
        router.refresh();
      } else {
        const response = await fetch(`${BACKEND}/auth/signup`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password, full_name: fullName.trim() }),
        });
        const body = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(body.detail || "Unable to create account.");
        setMessage("Account created successfully. Sign in to continue.");
        setTimeout(() => router.replace("/login"), 900);
      }
    } catch (authError) {
      setError(authError instanceof Error ? authError.message : "Authentication failed.");
    } finally {
      setLoading(false);
    }
  };

  const resetPassword = async () => {
    setError("");
    if (!email) return setError("Enter your email first.");
    const { error: resetError } = await supabase.auth.resetPasswordForEmail(email);
    if (resetError) setError("Unable to send a reset email.");
    else setMessage("If an account exists for that email, a reset link is on its way.");
  };

  return (
    <main className="auth-page min-h-screen flex items-center justify-center p-6">
      <div className="auth-layout">
        <section className="auth-brand-panel">
          <Link href="/login" className="auth-brand">RepoGuardian</Link>
          <p className="auth-tagline">Autonomous AI for code review, security &amp; reliability</p>
          <div className="auth-illustration" aria-hidden="true"><div className="illustration-window"><div className="window-bar"><i /><i /><i /></div><div className="code-line"><b>01</b><span className="code-blue">const</span> audit = <span className="code-green">await</span> repo.scan();</div><div className="code-line"><b>02</b><span className="code-purple">pipeline</span>.run(audit);</div><div className="code-line"><b>03</b><span className="code-green">return</span> security.report;</div><div className="illustration-score"><span>Repository health</span><strong>86</strong><small>/100</small></div></div><span className="illustration-node node-one" /><span className="illustration-node node-two" /><span className="illustration-line line-one" /><span className="illustration-line line-two" /></div>
          <p className="auth-description">Turn complex repositories into clear engineering decisions with one intelligent analysis workspace.</p>
        </section>
        <section className="auth-form-panel">
          <div className="auth-form-heading"><h1>{mode === "login" ? "Welcome Back" : "Create your account"}</h1><p>{mode === "login" ? "Sign in to continue to RepoGuardian" : "Start analyzing and securing your repositories with RepoGuardian."}</p></div>
          <div className="auth-card">
          <div className="flex gap-2 mb-6 p-1 auth-tabs">
            <Link href="/login" className={`flex-1 text-center py-2 rounded-lg text-xs font-bold ${mode === "login" ? "auth-tab-active" : "text-slate-500"}`}>Login</Link>
            <Link href="/signup" className={`flex-1 text-center py-2 rounded-lg text-xs font-bold ${mode === "signup" ? "auth-tab-active" : "text-slate-500"}`}>Sign Up</Link>
          </div>
          {error && <div role="alert" className="mb-4 rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700">{error}{error.includes("No account found") && <Link className="mt-2 block font-bold text-blue-600" href="/signup">Create Account →</Link>}</div>}
          {message && <div role="status" className="mb-4 rounded-xl border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-700">{message}</div>}
          <form onSubmit={submit} className="space-y-4">
            {mode === "signup" && <div><label htmlFor="full-name" className="mb-1 block text-xs text-slate-300">Full Name</label><input id="full-name" value={fullName} onChange={(e) => setFullName(e.target.value)} autoComplete="name" className="auth-input" required /></div>}
            <div><label htmlFor="email" className="mb-1 block text-xs text-slate-300">Email</label><input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" className="auth-input" required /></div>
            <div><label htmlFor="password" className="mb-1 block text-xs text-slate-300">Password</label><div className="relative"><input id="password" type={showPassword ? "text" : "password"} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={mode === "login" ? "current-password" : "new-password"} className="auth-input pr-20" required /><button type="button" onClick={() => setShowPassword(!showPassword)} className="absolute right-3 top-2 text-xs text-cyan-400">{showPassword ? "Hide" : "Show"}</button></div></div>
            {mode === "signup" && <div><label htmlFor="confirm-password" className="mb-1 block text-xs text-slate-300">Confirm Password</label><input id="confirm-password" type={showPassword ? "text" : "password"} value={confirmPassword} onChange={(e) => setConfirmPassword(e.target.value)} autoComplete="new-password" className="auth-input" required /></div>}
            {mode === "login" && <div className="auth-options"><label><input type="checkbox" checked={rememberMe} onChange={(event) => setRememberMe(event.target.checked)} /> Remember me</label><button type="button" onClick={resetPassword}>Forgot password?</button></div>}
            <button type="submit" disabled={loading} className="primary-button w-full">{loading ? "Please wait..." : mode === "login" ? "Sign In  →" : "Create Account"}</button>
          </form>
          <p className="auth-switch">{mode === "login" ? "Don't have an account?" : "Already have an account?"} <Link href={mode === "login" ? "/signup" : "/login"}>{mode === "login" ? "Sign Up" : "Sign In"}</Link></p>
        </div>
        </section>
      </div>
    </main>
  );
}
