"use client";
// /admin: turn this browser into an admin (one of the laptops that may start runs, launch attacks, decide escalations) or back into
// a viewer. Plain, like /ops. The key is posted once to POST /api/admin/login and never stored here; the server sets an HttpOnly cookie.
import Link from "next/link";
import { useState, type FormEvent } from "react";
import { refreshRole, useRole } from "@/lib/role";

export function AdminLogin() {
  const role = useRole();
  const [key, setKey] = useState("");
  const [msg, setMsg] = useState("");
  const [busy, setBusy] = useState(false);

  async function login(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setMsg("");
    try {
      const r = await fetch("/api/admin/login", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ key }), cache: "no-store", signal: AbortSignal.timeout(10_000) });
      setMsg(r.ok ? "ok" : r.status === 401 ? "wrong key" : r.status === 429 ? "too many tries, wait a little" : r.status === 503 ? "admin is disabled on this server (ADMIN_KEY unset)" : `failed (${r.status})`);
      if (r.ok) setKey("");
    } catch {
      setMsg("no answer");
    } finally {
      setBusy(false);
      await refreshRole();
    }
  }

  async function logout() {
    setBusy(true);
    try { await fetch("/api/admin/logout", { method: "POST", cache: "no-store", signal: AbortSignal.timeout(10_000) }); } catch { /* the role check below says where we are */ }
    setBusy(false);
    setMsg("");
    await refreshRole();
  }

  return (
    <main className="p-6 space-y-6 font-mono text-sm">
      <header className="flex items-center gap-4">
        <h1 className="text-xl font-bold">Red Ledger</h1>
        <span>this browser: <b>{role}</b></span>
        <Link className="border px-2" href="/">arena</Link>
      </header>
      {role === "admin" ? (
        <section className="space-y-3">
          <p>This browser may start runs, launch attacks and decide escalations.</p>
          <button className="border px-2" onClick={() => void logout()} disabled={busy}>log out</button>
        </section>
      ) : (
        <form className="flex items-center gap-3" onSubmit={(e) => void login(e)}>
          <label htmlFor="admin-key">admin key</label>
          <input id="admin-key" className="border px-2" type="password" autoComplete="current-password" value={key} onChange={(e) => setKey(e.target.value)} />
          <button className="border px-2" type="submit" disabled={busy || !key}>log in</button>
        </form>
      )}
      {msg && <p className="opacity-70">{msg}</p>}
    </main>
  );
}
