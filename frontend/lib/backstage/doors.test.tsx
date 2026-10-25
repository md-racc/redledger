// The doors in the arena: two faint diamonds for an admin, and nothing at all, not even an empty element, for anyone else.
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, describe, expect, it, vi } from "vitest";
import { Doors } from "@/components/arena/overlays/Doors";

// zustand reads its initial state on the server, so the role is stubbed here rather than set on the store
let role: "admin" | "viewer" = "viewer";
vi.mock("@/lib/role", () => ({ useRole: () => role }));
// vitest compiles the component's JSX with the classic runtime: give it React
beforeAll(() => { (globalThis as { React?: typeof React }).React = React; });

const html = (show = true) => renderToStaticMarkup(<Doors show={show} />);

describe("the doors in the arena", () => {
  it("are two buttons for an admin, red and blue", () => {
    role = "admin";
    const out = html();
    expect(out.match(/<button/g)).toHaveLength(2);
    expect(out).toContain("door-red");
    expect(out).toContain("door-blue");
  });

  it("leave nothing in the page for a viewer", () => {
    role = "viewer";
    expect(html()).toBe("");
  });

  it("are not drawn while the show plays or before the arena", () => {
    role = "admin";
    expect(html(false)).toBe("");
  });

  it("carry no words a bystander could read off the page", () => {
    role = "admin";
    expect(html().replace(/<[^>]+>/g, "")).toBe(""); // no visible text at all
  });
});
