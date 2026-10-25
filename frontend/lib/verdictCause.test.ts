import { describe, expect, it } from "vitest";
import { cardFor } from "./arena/headlines";
import { explainEscalation } from "./arena/escalation";
import { captionFor } from "./arena/narration";
import { initialState, reduce } from "./reducer";
import type { RLEvent } from "./types";
import { failSafeLabel, isFailSafe, verdictCause } from "./verdictCause";

let n = 0;
const ev = (type: string, payload: Record<string, unknown>): RLEvent => ({ id: ++n, ts: "", episode_id: "x", day: 1, type, agent: "battlefield", payload });

describe("verdict cause: a fail-safe is not a catch", () => {
  it("reads cause from the event, and falls back to battlefield's own rule for events recorded before cause existed", () => {
    expect(verdictCause({ cause: "gate_unavailable" })).toBe("gate_unavailable");
    expect(verdictCause({ cause: "control", rules_fired: ["near_threshold"] })).toBe("control");
    expect(verdictCause({ rules_fired: ["gate_timeout"] })).toBe("gate_unavailable");
    expect(verdictCause({ rules_fired: ["near_threshold"] })).toBe("control");
    expect(verdictCause(null)).toBe("control");
  });

  it("labels a fail-safe block as such", () => {
    expect(failSafeLabel("block")).toBe("Blocked by fail-safe: controller unreachable");
    expect(failSafeLabel("escalate")).toBe("Held by fail-safe: controller unreachable");
  });

  it("keeps cause on the derived verdict and escalation state", () => {
    let s = reduce(initialState(), ev("gate.verdict", { verdict_id: "v1", agent: "green", action: "invoices.pay", amount: 900, verdict: "block", reason: "controller unavailable (ReadTimeout); defaulted to escalate", rules_fired: ["gate_timeout"], enforced: true, cause: "gate_unavailable" }));
    s = reduce(s, ev("escalation.opened", { escalation_id: "e1", verdict_id: "v1", action: "invoices.pay", amount: 900, reason: "r", expires_at: "", cause: "gate_unavailable" }));
    expect(isFailSafe(s.verdicts[0])).toBe(true);
    expect(isFailSafe(s.escalations.e1)).toBe(true);
  });

  it("a fail-safe verdict's feed card and caption are muted and name no guard; a control block keeps its rule", () => {
    const fs = ev("gate.verdict", { verdict: "block", enforced: true, action: "invoices.pay", amount: 900, rules_fired: ["gate_timeout"], cause: "gate_unavailable", reason: "x" });
    const card = cardFor(fs)!;
    expect(card.head).toBe("Blocked by fail-safe: controller unreachable");
    expect(card.tone).toBe("ink");
    expect(card.agentId).toBeUndefined();
    const cap = captionFor(fs)!;
    expect(cap.text).toBe("Blocked by fail-safe: controller unreachable");
    expect(cap.tag).not.toMatch(/blocks/i);

    const ctl = cardFor(ev("gate.verdict", { verdict: "block", enforced: true, action: "invoices.pay", amount: 900, rules_fired: ["near_threshold"], cause: "control", reason: "x" }))!;
    expect(ctl.tone).toBe("blue");
    expect(ctl.sub).toContain("near threshold");

    const esc = cardFor(ev("escalation.opened", { escalation_id: "e", verdict_id: "v", action: "invoices.pay", amount: 900, reason: "r", cause: "gate_unavailable" }))!;
    expect(esc.head).toBe("Held by fail-safe: controller unreachable");
  });

  it("the arena's decision card says the fail-safe is asking, not a control", () => {
    const x = explainEscalation({ action: "invoices.pay", amount: 900, reason: "r", cause: "gate_unavailable" }, { rules_fired: ["gate_timeout"], reason: "x" });
    expect(x.failSafe).toBe(true);
    expect(x.why[0]).toMatch(/fail-safe/);
    expect(x.what).toMatch(/could not be reached/);
    expect(explainEscalation({ action: "invoices.pay", amount: 900, reason: "r" }, { rules_fired: ["near_threshold"], reason: "x" }).failSafe).toBe(false);
  });
});
