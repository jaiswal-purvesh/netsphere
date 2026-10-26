"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { login, ApiError } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("admin@netsphere.local");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await login(email, password);
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? String(err.detail) : "login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-surface-0">
      <div className="pointer-events-none absolute -top-32 left-1/2 h-96 w-[46rem] -translate-x-1/2 rounded-full bg-indigo-600/20 blur-[100px]" />
      <div className="pointer-events-none absolute bottom-0 right-0 h-72 w-72 rounded-full bg-violet-600/10 blur-[100px]" />

      <div className="relative w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center text-center">
          {/* eslint-disable-next-line @next/next/no-img-element -- a static
              brand asset from /public, not worth next/image's config here */}
          <img src="/bajaj-logo.png" alt="Bajaj Finance" className="mb-4 h-8 w-auto rounded-sm" />
          <h1 className="text-2xl font-semibold tracking-tight text-zinc-50">NetSphere</h1>
          <p className="mt-1 text-sm text-zinc-500">Enterprise Network Management &amp; Automation</p>
        </div>

        <form
          onSubmit={onSubmit}
          className="rounded-2xl border border-white/[0.08] bg-surface-2/90 p-7 shadow-elevated backdrop-blur"
        >
          <label className="mb-4 block text-sm">
            <span className="mb-1.5 block font-medium text-zinc-300">Email</span>
            <input
              className="w-full rounded-lg border border-white/[0.08] bg-white/[0.03] px-3 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-indigo-500/60 focus:outline-none focus:ring-1 focus:ring-indigo-500/40"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              type="email"
              required
            />
          </label>
          <label className="mb-5 block text-sm">
            <span className="mb-1.5 block font-medium text-zinc-300">Password</span>
            <input
              className="w-full rounded-lg border border-white/[0.08] bg-white/[0.03] px-3 py-2.5 text-sm text-zinc-100 placeholder:text-zinc-600 focus:border-indigo-500/60 focus:outline-none focus:ring-1 focus:ring-indigo-500/40"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              type="password"
              required
            />
          </label>

          {error && (
            <p className="mb-4 rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-sm text-red-400">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={busy}
            className="w-full rounded-lg bg-gradient-to-b from-indigo-500 to-indigo-600 px-4 py-2.5 text-sm font-medium text-white shadow-card transition hover:from-indigo-400 hover:to-indigo-500 disabled:opacity-60"
          >
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>

        <p className="mt-5 text-center text-xs text-zinc-600">
          Local dev seed: admin@netsphere.local / ChangeMe123!
        </p>
      </div>
    </div>
  );
}
