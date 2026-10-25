import { beforeEach, describe, expect, it, vi } from "vitest";
import { isAdmin, refreshRole, useRoleStore } from "./role";

describe("the browser's role", () => {
  beforeEach(() => useRoleStore.setState({ role: "viewer", known: false }));

  it("is a viewer until the server says otherwise", async () => {
    expect(isAdmin()).toBe(false);
    const f = vi.fn(async () => Response.json({ role: "admin" }));
    expect(await refreshRole(f as unknown as typeof fetch)).toBe("admin");
    expect(f).toHaveBeenCalledWith("/api/whoami", expect.objectContaining({ cache: "no-store" }));
    expect(isAdmin()).toBe(true);
    expect(useRoleStore.getState().known).toBe(true);
  });

  it("stays what it was when whoami fails, and never trusts an odd answer", async () => {
    expect(await refreshRole((async () => { throw new TypeError("offline"); }) as unknown as typeof fetch)).toBe("viewer");
    expect(await refreshRole((async () => new Response("", { status: 500 })) as unknown as typeof fetch)).toBe("viewer");
    expect(await refreshRole((async () => Response.json({ role: "root" })) as unknown as typeof fetch)).toBe("viewer");
    expect(isAdmin()).toBe(false);
  });
});
