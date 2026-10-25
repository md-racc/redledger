import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { RLEvent } from "../types";
import { recordingScript, RECORDING } from "./recording";

const ev = (id: number, sec: number, type = "ledger.mutation"): RLEvent => ({ id, ts: new Date(Date.UTC(2026, 9, 24, 22, 0, sec)).toISOString(), episode_id: "ep", day: 0, type, agent: "battlefield", payload: {} });

describe("the recorded run as raw messages", () => {
  it("keeps order and fits the window", () => {
    const items = recordingScript([ev(1, 0), ev(2, 1), ev(3, 2), ev(4, 3)], 10_000);
    expect(items.map((i) => i.e.id)).toEqual([1, 2, 3, 4]);
    for (let k = 1; k < items.length; k++) expect(items[k]!.at).toBeGreaterThan(items[k - 1]!.at);
    expect(items[0]!.at).toBe(0);
    expect(items[items.length - 1]!.at).toBeLessThan(10_000);
  });

  it("keeps the rhythm: a burst stays a burst and a pause stays a pause", () => {
    // three events in 0.2 s, then a 3 s pause, then one more
    const items = recordingScript([ev(1, 0), { ...ev(2, 0), id: 2, ts: new Date(Date.UTC(2026, 9, 24, 22, 0, 0, 100)).toISOString() }, { ...ev(3, 0), id: 3, ts: new Date(Date.UTC(2026, 9, 24, 22, 0, 0, 200)).toISOString() }, ev(4, 3)], 6_000);
    const burst = items[2]!.at - items[0]!.at;
    const pause = items[3]!.at - items[2]!.at;
    expect(pause).toBeGreaterThan(burst * 5);
  });

  it("cuts a very long pause so a console never sits silent", () => {
    const items = recordingScript([ev(1, 0), ev(2, 1), ev(3, 120), ev(4, 121)], 10_000);
    const first = items[1]!.at - items[0]!.at;
    const long = items[2]!.at - items[1]!.at;
    expect(long).toBeLessThan(first * 5); // 119 s capped at 4 s, against a 1 s gap
  });

  it("stamps every item as a replay, so a second round is not dropped as a duplicate", () => {
    expect(recordingScript([ev(1, 0), ev(2, 1)], 1000).every((i) => i.e.replay === true)).toBe(true);
  });
});

describe("the recording the consoles ship with", () => {
  const root = join(__dirname, "../../..");
  const shipped = readFileSync(join(__dirname, `../../public/mocks/${RECORDING}.jsonl`), "utf8");

  it("is the one in recordings, byte for byte (copy it again if that changes)", () => {
    expect(shipped).toBe(readFileSync(join(root, "recordings", `${RECORDING}.jsonl`), "utf8"));
  });

  it("is a live-red enforce run with the messy parts: tool calls, thinking, ledger writes, verdicts", () => {
    const events = shipped.split("\n").filter(Boolean).map((l) => JSON.parse(l) as RLEvent);
    const types = new Set(events.map((e) => e.type));
    for (const t of ["agent.tool_call", "agent.tool_result", "agent.thinking", "ledger.mutation", "gate.verdict", "escalation.opened", "episode.ended"]) expect(types.has(t), t).toBe(true);
    const items = recordingScript(events, 90_000);
    expect(items).toHaveLength(events.length);
    expect(items[items.length - 1]!.at).toBeLessThan(90_000);
  });
});
