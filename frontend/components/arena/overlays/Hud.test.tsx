// The escalation card as each audience sees it: an admin decides, a viewer watches a person decide (and, on a phone, gets one line).
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeAll, describe, expect, it } from "vitest";
import { EscalationCard, type EscalationCardProps } from "@/components/arena/overlays/Hud";
import type { EscalationExplained } from "@/lib/arena/escalation";

// vitest compiles the component's JSX with the classic runtime: give it React
beforeAll(() => { (globalThis as { React?: typeof React }).React = React; });

const x: EscalationExplained = {
  title: "Pay this invoice?",
  what: "Green wants to pay $4,200 to a vendor added two days ago.",
  why: ["The vendor is less than a week old"],
  approve: { label: "Approve", result: "the payment is sent" },
  block: { label: "Block", result: "nothing is paid" },
  failSafe: false,
};
const html = (p: Partial<EscalationCardProps>) => renderToStaticMarkup(<EscalationCard x={x} admin={false} approvable left={42} total={90} onResolve={() => {}} {...p} />);

describe("the escalation card", () => {
  it("gives an admin the decision: 'Your decision' with Approve and Block", () => {
    const out = html({ admin: true });
    expect(out).toContain("Your decision");
    expect(out).toContain("esc-btn approve");
    expect(out).toContain("esc-btn block");
    expect(out).not.toContain("disabled");
    expect(out).toContain("Why the controller stopped it");
  });

  it("an admin keeps the full card on a narrow screen too", () => {
    const out = html({ admin: true, compact: true });
    expect(out).toContain("Your decision");
    expect(out).toContain("esc-btn block");
  });

  it("tells a viewer a person decides, with no buttons they cannot press", () => {
    const out = html({ admin: false });
    expect(out).toContain("A person decides");
    expect(out).not.toContain("Your decision");
    expect(out).not.toContain("<button");
    expect(out).toContain("Pay this invoice?");
    expect(out).toContain("The operator decides");
    expect(out).toContain("<b>42</b> s left");
  });

  it("is one line and a countdown for a viewer on a phone", () => {
    const out = html({ admin: false, compact: true });
    expect(out).toContain("A person decides");
    expect(out).toContain("Pay this invoice?");
    expect(out).toContain("<b style=\"font-size:18px\">42</b> s");
    expect(out).not.toContain("<button");
    expect(out).not.toContain("<h3>");
    expect(out).not.toContain("escalation-why");
  });

  it("names the fail-safe for a viewer without promising them the decision", () => {
    const out = html({ admin: false, x: { ...x, failSafe: true } });
    expect(out).toContain("Fail-safe · a person decides");
    expect(out).not.toContain("your decision");
  });
});
