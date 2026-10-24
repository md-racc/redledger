import { describe, expect, it } from "vitest";
import { buildNavGrid, findPath, isWalkable, lineClear, nearestWalkable, pathLength, pushOutOfColumns } from "./nav";
import { ArenaSim } from "./sim";
import { SLOT_RING, SPAWN } from "./config";
import { ROSTER, ROSTER_BY_ID } from "./roster";

const grid = buildNavGrid();

describe("nav grid", () => {
  it("knows the lagoon, the hall and the rotunda floor", () => {
    expect(isWalkable(grid, 0, 0)).toBe(true); // rotunda floor
    expect(isWalkable(grid, 0, -70)).toBe(false); // lagoon
    expect(isWalkable(grid, 0, 80)).toBe(false); // exploratorium hall
    expect(isWalkable(grid, 4, 46)).toBe(true); // lawn behind the rotunda
  });

  it("finds a clear path from every perimeter anchor to the arena", () => {
    for (const team of ["red", "blue", "green"] as const) {
      const from = nearestWalkable(grid, SPAWN[team].x, SPAWN[team].z)!;
      const path = findPath(grid, from, [SLOT_RING[team], 0]);
      expect(path, team).not.toBeNull();
      let prev: [number, number] = from;
      for (const p of path!) {
        expect(isWalkable(grid, p[0], p[1])).toBe(true);
        expect(lineClear(grid, prev, p)).toBe(true);
        prev = p;
      }
      expect(pathLength(from, path!)).toBeLessThan(260);
    }
  });

  it("does not route through the lagoon", () => {
    // north embayment: the straight line crosses water, the path must go round
    const p = findPath(grid, [-66, 12], [0, 0])!;
    expect(pathLength([-66, 12], p)).toBeGreaterThan(Math.hypot(66, 12) + 5);
  });

  it("slides points out of columns", () => {
    const [x, z] = pushOutOfColumns(-25, 29.7, 0.6); // on top of the first colonnade column
    expect(Math.hypot(x + 25, z - 29.62)).toBeGreaterThan(1.0);
  });
});

describe("arena sim", () => {
  const run = (sim: ArenaSim, seconds: number, hz = 30) => { for (let i = 0; i < seconds * hz; i++) sim.update(1 / hz); };

  it("spawns all 30 agents on walkable perimeter ground", () => {
    const sim = new ArenaSim(ROSTER, grid, 7);
    expect(sim.agents.size).toBe(30);
    for (const a of sim.agents.values()) expect(isWalkable(grid, a.x, a.z)).toBe(true);
  });

  it("converges every agent onto its slot", () => {
    const sim = new ArenaSim(ROSTER, grid, 7);
    sim.converge();
    run(sim, 60);
    expect(sim.phase).toBe("engaged");
    for (const a of sim.agents.values()) {
      expect(a.mode).toBe("hold");
      expect(Math.hypot(a.x - a.slot[0], a.z - a.slot[1])).toBeLessThan(2.5);
    }
  });

  it("plays an extraction and a block, then everyone returns to hold", () => {
    const sim = new ArenaSim(ROSTER, grid, 7);
    sim.converge();
    run(sim, 60);
    sim.launchAttack({ attackId: "a1", redId: "red:ghost_vendor", greenId: "green:client_03", outcome: "extracted", amount: 4920 });
    sim.launchAttack({ attackId: "a2", redId: "red:bank_swap", greenId: "green:client_07", outcome: "blocked", guardId: "blue:recent_bank_change" });
    run(sim, 40);
    expect(sim.scenes.length).toBe(0);
    for (const id of ["red:ghost_vendor", "red:bank_swap", "blue:recent_bank_change"]) expect(sim.agents.get(id)!.mode).toBe("hold");
    const fx = sim.drainFx();
    expect(fx.some((f) => f.kind === "pop" && f.text.startsWith("+$4,920"))).toBe(true);
    expect(fx.some((f) => f.kind === "pop" && f.text === "BLOCKED")).toBe(true);
  });

  it("holds an attack open until the outcome arrives", () => {
    const sim = new ArenaSim(ROSTER, grid, 7);
    sim.converge();
    run(sim, 60);
    sim.launchAttack({ attackId: "a3", redId: "red:po_mismatch", greenId: "green:client_01" });
    run(sim, 20);
    expect(sim.scenes[0].stage).toBe("pitch");
    sim.resolveAttack("a3", "blocked");
    run(sim, 20);
    expect(sim.scenes.length).toBe(0);
  });

  it("disperses back to the perimeter", () => {
    const sim = new ArenaSim(ROSTER, grid, 7);
    sim.converge();
    run(sim, 60);
    sim.disperse();
    run(sim, 60);
    expect(sim.phase).toBe("idle");
    for (const a of sim.agents.values()) expect(Math.hypot(a.x - a.home[0], a.z - a.home[1])).toBeLessThan(3);
  });

  it("roster ids are unique", () => {
    expect(new Set(ROSTER.map((r) => r.id)).size).toBe(ROSTER.length);
    expect(ROSTER_BY_ID["blue:duplicate_invoice"].team).toBe("blue");
  });
});
