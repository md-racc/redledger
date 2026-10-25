"use client";
// The browser's idea of who it is: "admin" (one of our laptops, holding the admin cookie) or "viewer" (anyone with the URL). Owner: Dev R.
//
//   useRole()     the role, for hiding/disabling controls; viewer until GET /api/whoami answers (admin at once in mock mode)
//   isAdmin()     the same, read outside React (lib/sync/client.ts, lib/arena/useFeed.ts)
//   refreshRole() ask again (after logging in or out on /admin)
//
// A hint only: the server decides (lib/admin.ts) and the /api/bf proxy and /api/sync refuse a viewer's writes whatever this says.
import { useEffect } from "react";
import { create } from "zustand";

export type Role = "admin" | "viewer";

const MOCK_ONLY = process.env.NEXT_PUBLIC_MOCK === "true";

interface RoleState { role: Role; known: boolean }

export const useRoleStore = create<RoleState>(() => ({ role: MOCK_ONLY ? "admin" : "viewer", known: MOCK_ONLY }));

let inflight: Promise<Role> | null = null;

/** Ask the server. Any failure leaves the role as it was (a viewer stays a viewer). */
export function refreshRole(fetchImpl: typeof fetch = fetch): Promise<Role> {
  if (MOCK_ONLY) return Promise.resolve("admin");
  inflight ??= (async () => {
    try {
      const r = await fetchImpl("/api/whoami", { cache: "no-store", signal: AbortSignal.timeout(5000) });
      if (r.ok) {
        const body = (await r.json()) as { role?: unknown };
        const role: Role = body.role === "admin" ? "admin" : "viewer";
        useRoleStore.setState({ role, known: true });
      }
    } catch { /* keep what we have */ }
    return useRoleStore.getState().role;
  })().finally(() => { inflight = null; });
  return inflight;
}

export const isAdmin = (): boolean => useRoleStore.getState().role === "admin";

let asked = false;

export function useRole(): Role {
  useEffect(() => {
    if (asked) return;
    asked = true;
    void refreshRole();
  }, []);
  return useRoleStore((s) => s.role);
}
