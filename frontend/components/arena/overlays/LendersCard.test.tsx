// The lenders card: five names, every source a real link that opens safely, the disclaimer, and aria-hidden when closed.
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, describe, expect, it } from "vitest";
import { ALSO, AXIOS, DISCLAIMER, LENDERS } from "@/lib/arena/lenders";
import { LendersCard, when } from "./LendersCard";

// vitest compiles the component's JSX with the classic runtime: give it React
beforeAll(() => { (globalThis as { React?: typeof React }).React = React; });

const html = (open = true) => renderToStaticMarkup(<LendersCard open={open} onClose={() => {}} />);

describe("the lenders card", () => {
  it("has a column for each of the five, with their sources as safe links", () => {
    const out = html();
    expect(out.match(/class="lnd-col"/g)).toHaveLength(5);
    for (const l of LENDERS) {
      expect(out, l.name).toContain(l.name);
      for (const s of l.sources) expect(out, s.url).toContain(`href="${s.url.replace(/&/g, "&amp;")}"`);
    }
    expect(out).toContain(`href="${AXIOS.url}"`);
    for (const a of ALSO) expect(out).toContain(a.name);
    for (const m of out.matchAll(/<a [^>]*>/g)) {
      expect(m[0]).toContain('target="_blank"');
      expect(m[0]).toContain('rel="noopener noreferrer"');
    }
  });

  it("carries the disclaimer and says Wells Fargo has no statement", () => {
    const out = html();
    expect(out).toContain(DISCLAIMER);
    expect(out).toMatch(/No statement found/);
  });

  it("is hidden from assistive tech until opened", () => {
    expect(html(false)).toContain('aria-hidden="true"');
    expect(html(true)).toContain("is-open");
  });

  it("writes dates the way the pitch says them", () => {
    expect(when("2026-10-22")).toBe("Oct 22, 2026");
  });
});
