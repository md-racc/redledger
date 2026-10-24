// Arena simulation: where every agent is and what it is doing. Owner: Dev R.
// Pure TypeScript with no three.js, so it runs under vitest and is driven by the render loop (`sim.update(dt)`).
//
// Layout: agents start on the perimeter (SPAWN), `converge()` sends each one along an A* path to its slot in the
// rotunda (greens inner ring, guards middle, fraudsters outer), and `launchAttack()` plays out one fraud attempt
// at a time: a red walks up to a green, works it, and either walks away with the money or is run down by a guard.
import { AGENT_CLEARANCE, CENTER, DASH_SPEED, SLOT_RING, SPAWN, SPEED } from "./config";
import { findPath, isWalkable, mulberry32, nearestWalkable, pushOutOfColumns, scatterWalkable, type NavGrid, type Vec2 } from "./nav";
import type { AgentMode, AgentSpec, AgentStatus, ArenaPhase, AttackOutcome, Team } from "./types";

export interface SimAgent {
  spec: AgentSpec;
  x: number;
  z: number;
  /** yaw: forward = (sin h, cos h) in (x, z) */
  heading: number;
  mode: AgentMode;
  modeT: number;
  path: Vec2[];
  pi: number;
  maxSpeed: number;
  /** smoothed ground speed, m/s; the renderer blends idle/walk animation on this */
  vel: number;
  home: Vec2;
  slot: Vec2;
  status: AgentStatus;
  /** 0..1 pulse, decays; the renderer turns it into an emissive kick */
  flash: number;
  side: 1 | -1;
  /** seconds before this agent leaves on converge/disperse (staggers the stampede) */
  delay: number;
  wanderT: number;
  wander: Vec2 | null;
  /** seconds spent moving slower than it should; a stalled agent skips its current waypoint */
  stall: number;
}

export type FxTone = "red" | "blue" | "green" | "amber";
export type Fx =
  | { kind: "pop"; x: number; z: number; text: string; tone: FxTone }
  | { kind: "ring"; x: number; z: number; tone: FxTone };

export type SceneStage = "queued" | "approach" | "pitch" | "resolve" | "after" | "done";
export interface Scene {
  id: number;
  attackId: string;
  redId: string;
  greenId: string;
  guardId: string | null;
  outcome: AttackOutcome | null;
  amount: number | null;
  stage: SceneStage;
  t: number;
  /** 0..1: how far the money has travelled from green to red (renderer draws coins on it) */
  flow: number;
  /** beam intensity 0..1 (renderer) */
  beam: number;
  impact: boolean;
}

export interface LaunchOpts {
  attackId: string;
  redId: string;
  greenId: string;
  guardId?: string | null;
  outcome?: AttackOutcome | null;
  amount?: number | null;
}

const TAU = Math.PI * 2;
const angDiff = (a: number, b: number) => Math.atan2(Math.sin(b - a), Math.cos(b - a));
const lerpAngle = (a: number, b: number, t: number) => a + angDiff(a, b) * t;
const dist = (a: { x: number; z: number }, b: { x: number; z: number }) => Math.hypot(a.x - b.x, a.z - b.z);

export const GOOD_OUTCOMES: AttackOutcome[] = ["extracted", "partial"];
export const isGuardWin = (o: AttackOutcome | null) => o === "blocked" || o === "flagged" || o === "failed";

export class ArenaSim {
  readonly agents = new Map<string, SimAgent>();
  readonly scenes: Scene[] = [];
  phase: ArenaPhase = "idle";
  time = 0;
  private fx: Fx[] = [];
  private rng: () => number;
  private sceneSeq = 1;
  private grid: NavGrid;

  constructor(roster: AgentSpec[], grid: NavGrid, seed = 7) {
    this.grid = grid;
    this.rng = mulberry32(seed);
    const byTeam: Record<Team, AgentSpec[]> = { red: [], blue: [], green: [] };
    roster.forEach((s) => byTeam[s.team].push(s));

    for (const team of ["red", "blue", "green"] as const) {
      const specs = byTeam[team];
      const a = SPAWN[team];
      const spots = scatterWalkable(grid, a.x, a.z, a.r, specs.length, 3.4, this.rng);
      while (spots.length < specs.length) spots.push(nearestWalkable(grid, a.x, a.z) ?? [a.x, a.z]);
      const slots = this.slotRing(team, specs.length, spots);
      const [smin, smax] = SPEED[team];
      specs.forEach((spec, i) => {
        const [x, z] = spots[i];
        this.agents.set(spec.id, {
          spec, x, z,
          heading: Math.atan2(CENTER.x - x, CENTER.z - z),
          mode: "idle", modeT: 0, path: [], pi: 0,
          maxSpeed: smin + this.rng() * (smax - smin),
          vel: 0,
          home: [x, z], slot: slots[i],
          status: "ok", flash: 0,
          side: this.rng() < 0.5 ? 1 : -1,
          delay: 0, wanderT: this.rng() * 3, wander: null, stall: 0,
        });
      });
    }
  }

  /** Slot positions on the team's ring, matched to spawn points by bearing so paths fan out instead of crossing. */
  private slotRing(team: Team, n: number, spots: Vec2[]): Vec2[] {
    const r = SLOT_RING[team];
    const offset = team === "green" ? 0.2 : team === "blue" ? 0.45 : 0;
    const slots: Vec2[] = Array.from({ length: n }, (_, k) => {
      const ang = (k / n) * TAU + offset;
      const [x, z] = nearestWalkable(this.grid, CENTER.x + Math.cos(ang) * r, CENTER.z + Math.sin(ang) * r, 4) ?? [CENTER.x + Math.cos(ang) * r, CENTER.z + Math.sin(ang) * r];
      return [x, z];
    });
    const bearing = (p: Vec2) => Math.atan2(p[1] - CENTER.z, p[0] - CENTER.x);
    const agentOrder = spots.map((p, i) => ({ i, b: bearing(p) })).sort((a, b) => a.b - b.b);
    const slotOrder = slots.map((p, k) => ({ k, b: bearing(p) })).sort((a, b) => a.b - b.b);
    // choose the rotation of the sorted slot list that minimises total bearing error
    let bestRot = 0, bestCost = Infinity;
    for (let rot = 0; rot < n; rot++) {
      let cost = 0;
      for (let j = 0; j < n; j++) cost += Math.abs(angDiff(agentOrder[j].b, slotOrder[(j + rot) % n].b));
      if (cost < bestCost) { bestCost = cost; bestRot = rot; }
    }
    const out: Vec2[] = new Array(n);
    for (let j = 0; j < n; j++) out[agentOrder[j].i] = slots[slotOrder[(j + bestRot) % n].k];
    return out;
  }

  // ---- commands --------------------------------------------------------------------------------------------------

  /** Everyone leaves the perimeter and pathfinds to their slot in the centre. */
  converge() {
    if (this.phase === "converging" || this.phase === "engaged") return;
    this.phase = "converging";
    let order = 0;
    for (const a of this.agents.values()) {
      a.delay = order++ * 0.05 + this.rng() * 0.3;
      this.sendTo(a, a.slot, "travel");
    }
  }

  /** Between acts: drop every live scene and put everyone back on their slot, un-caught and un-drained. */
  reset() {
    this.scenes.length = 0;
    for (const a of this.agents.values()) {
      a.status = "ok";
      if (a.mode !== "hold" && a.mode !== "idle" && a.mode !== "travel") { a.delay = 0; this.sendTo(a, a.slot, "return"); }
    }
  }

  /** Everyone walks back to the perimeter. */
  disperse() {
    this.phase = "dispersing";
    this.scenes.length = 0;
    for (const a of this.agents.values()) {
      a.status = "ok";
      a.delay = this.rng() * 1.2;
      this.sendTo(a, a.home, "travel");
    }
  }

  launchAttack(o: LaunchOpts): Scene | null {
    const red = this.agents.get(o.redId), green = this.agents.get(o.greenId);
    if (!red || !green) return null;
    const existing = this.scenes.find((s) => s.attackId === o.attackId);
    if (existing) return existing;
    const sc: Scene = {
      id: this.sceneSeq++, attackId: o.attackId, redId: o.redId, greenId: o.greenId,
      guardId: o.guardId ?? null, outcome: o.outcome ?? null, amount: o.amount ?? null,
      stage: "queued", t: 0, flow: 0, beam: 0, impact: false,
    };
    this.scenes.push(sc);
    if (this.phase === "idle" || this.phase === "dispersing") this.converge();
    return sc;
  }

  resolveAttack(attackId: string, outcome: AttackOutcome, guardId?: string | null, amount?: number | null) {
    const sc = this.scenes.find((s) => s.attackId === attackId);
    if (!sc) return;
    sc.outcome = outcome;
    if (guardId) sc.guardId = guardId;
    if (amount != null) sc.amount = amount;
  }

  /** Make a guard (or anyone) pulse and, optionally, pop a label over it. */
  pulse(id: string, tone: FxTone, text?: string) {
    const a = this.agents.get(id);
    if (!a) return;
    a.flash = 1;
    this.fx.push({ kind: "ring", x: a.x, z: a.z, tone });
    if (text) this.fx.push({ kind: "pop", x: a.x, z: a.z, text, tone });
  }

  setStatus(id: string, status: AgentStatus) {
    const a = this.agents.get(id);
    if (a) a.status = status;
  }

  drainFx(): Fx[] {
    if (!this.fx.length) return this.fx;
    const out = this.fx;
    this.fx = [];
    return out;
  }

  get allSettled() {
    for (const a of this.agents.values()) if (a.mode === "travel") return false;
    return true;
  }

  // ---- movement --------------------------------------------------------------------------------------------------

  private sendTo(a: SimAgent, to: Vec2, mode: AgentMode) {
    const path = findPath(this.grid, [a.x, a.z], to);
    a.path = path ?? [to];
    a.pi = 0;
    a.mode = mode;
    a.modeT = 0;
  }

  private nearPoint(from: SimAgent, target: SimAgent, gap: number): Vec2 {
    const dx = from.x - target.x, dz = from.z - target.z;
    const d = Math.hypot(dx, dz) || 1;
    return nearestWalkable(this.grid, target.x + (dx / d) * gap, target.z + (dz / d) * gap, 6) ?? [target.x, target.z];
  }

  private follow(a: SimAgent, dt: number, speed: number): boolean {
    let step = speed * dt;
    while (a.pi < a.path.length) {
      const [tx, tz] = a.path[a.pi];
      const dx = tx - a.x, dz = tz - a.z;
      const d = Math.hypot(dx, dz);
      const last = a.pi === a.path.length - 1;
      if (d <= step || (!last && d < 1.3)) {
        // intermediate waypoints are only steering hints (a column may sit on one): clip them at 1.3 m
        if (last || d <= step) { a.x = tx; a.z = tz; step = Math.max(0, step - d); }
        a.pi++;
        continue;
      }
      a.x += (dx / d) * step;
      a.z += (dz / d) * step;
      a.heading = lerpAngle(a.heading, Math.atan2(dx, dz), 1 - Math.exp(-dt * 9));
      return false;
    }
    return true;
  }

  private idleWander(a: SimAgent, dt: number, around: Vec2, radius: number) {
    a.wanderT -= dt;
    if (a.wander) {
      const dx = a.wander[0] - a.x, dz = a.wander[1] - a.z;
      const d = Math.hypot(dx, dz);
      if (d < 0.2) { a.wander = null; a.wanderT = 2.5 + this.rng() * 4; }
      else {
        const sp = Math.min(1.1, d / dt);
        a.x += (dx / d) * sp * dt; a.z += (dz / d) * sp * dt;
        a.heading = lerpAngle(a.heading, Math.atan2(dx, dz), 1 - Math.exp(-dt * 5));
        a.vel += (sp - a.vel) * Math.min(1, dt * 8);
        return;
      }
    } else if (a.wanderT <= 0) {
      const ang = this.rng() * TAU, r = this.rng() * radius;
      const p: Vec2 = [around[0] + Math.cos(ang) * r, around[1] + Math.sin(ang) * r];
      if (isWalkable(this.grid, p[0], p[1])) a.wander = p; else a.wanderT = 0.5;
    }
    // settle facing: reds and greens face the middle, guards face outward
    const toC = Math.atan2(CENTER.x - a.x, CENTER.z - a.z);
    const face = a.mode === "hold" ? (a.spec.team === "blue" ? toC + Math.PI : toC) : toC;
    a.heading = lerpAngle(a.heading, face, 1 - Math.exp(-dt * 2));
    a.vel += (0 - a.vel) * Math.min(1, dt * 10);
  }

  // ---- tick ------------------------------------------------------------------------------------------------------

  update(dtRaw: number) {
    const dt = Math.min(dtRaw, 0.1);
    this.time += dt;
    const prev = new Map<string, Vec2>();
    for (const a of this.agents.values()) prev.set(a.spec.id, [a.x, a.z]);

    for (const a of this.agents.values()) {
      a.modeT += dt;
      a.flash = Math.max(0, a.flash - dt * 1.4);
      switch (a.mode) {
        case "idle":
          this.idleWander(a, dt, a.home, 2.2);
          break;
        case "hold":
          this.idleWander(a, dt, a.slot, 0.7);
          break;
        case "travel":
        case "return":
        case "approach":
        case "dash": {
          if (a.delay > 0) { a.delay -= dt; a.vel += (0 - a.vel) * Math.min(1, dt * 10); break; }
          const sp = a.mode === "dash" ? DASH_SPEED : a.maxSpeed * (a.mode === "approach" ? 0.9 : 1);
          const arrived = this.follow(a, dt, sp);
          if (arrived) this.onArrive(a);
          break;
        }
        case "pitch":
          // working the target: shuffle in place, face the green
          a.vel += (0 - a.vel) * Math.min(1, dt * 10);
          break;
        case "caught":
          a.vel += (0 - a.vel) * Math.min(1, dt * 10);
          break;
      }
    }

    this.separate(dt);

    // measured speed → animation
    for (const a of this.agents.values()) {
      const p = prev.get(a.spec.id)!;
      const v = Math.hypot(a.x - p[0], a.z - p[1]) / Math.max(dt, 1e-4);
      if (a.mode === "travel" || a.mode === "return" || a.mode === "approach" || a.mode === "dash") {
        a.vel += (v - a.vel) * Math.min(1, dt * 10);
        // stalled against a column or a crowd: skip the waypoint (or accept arrival) rather than hang the scene
        if (a.delay <= 0 && v < 0.35) a.stall += dt; else a.stall = 0;
        if (a.stall > 1.4) {
          a.stall = 0;
          if (a.pi < a.path.length - 1) a.pi++;
          else { a.pi = a.path.length; this.onArrive(a); }
        }
      }
    }

    this.updateScenes(dt);

    if (this.phase === "converging" && this.allSettled) this.phase = "engaged";
    if (this.phase === "dispersing" && this.allSettled) this.phase = "idle";
  }

  private onArrive(a: SimAgent) {
    if (a.mode === "travel" || a.mode === "return") {
      a.mode = this.phase === "dispersing" || (this.phase === "idle") ? "idle" : "hold";
      a.wander = null; a.wanderT = 1 + this.rng() * 2;
    } else if (a.mode === "approach") {
      a.mode = "pitch"; a.modeT = 0;
    } else if (a.mode === "dash") {
      a.mode = "hold"; // the scene logic takes over on contact
    }
  }

  /** Soft push so agents don't stack, then slide out of columns and back onto walkable ground. */
  private separate(dt: number) {
    const list = [...this.agents.values()];
    const R = 2.1;
    for (let i = 0; i < list.length; i++) {
      const a = list[i];
      for (let j = i + 1; j < list.length; j++) {
        const b = list[j];
        if (a.mode === "dash" || b.mode === "dash" || a.mode === "pitch" || b.mode === "pitch") continue;
        const dx = b.x - a.x, dz = b.z - a.z;
        const d2 = dx * dx + dz * dz;
        if (d2 >= R * R || d2 < 1e-6) continue;
        const d = Math.sqrt(d2);
        const push = ((R - d) / 2) * Math.min(1, dt * 7);
        const nx = dx / d, nz = dz / d;
        a.x -= nx * push; a.z -= nz * push;
        b.x += nx * push; b.z += nz * push;
      }
    }
    for (const a of list) {
      const [px, pz] = pushOutOfColumns(a.x, a.z, AGENT_CLEARANCE * 0.55, a.side);
      if (isWalkable(this.grid, px, pz)) { a.x = px; a.z = pz; }
    }
  }

  // ---- fraud scenes ----------------------------------------------------------------------------------------------

  private updateScenes(dt: number) {
    for (const sc of this.scenes) {
      const red = this.agents.get(sc.redId), green = this.agents.get(sc.greenId);
      if (!red || !green) { sc.stage = "done"; continue; }
      sc.t += dt;
      switch (sc.stage) {
        case "queued": {
          // one live scene per red, and only once the arena is formed
          const busy = this.scenes.some((o) => o !== sc && o.redId === sc.redId && o.stage !== "queued" && o.stage !== "done");
          if (this.phase === "engaged" && !busy && red.mode === "hold") {
            this.sendTo(red, this.nearPoint(red, green, 3.3), "approach");
            sc.stage = "approach"; sc.t = 0;
            this.fx.push({ kind: "pop", x: red.x, z: red.z, text: red.spec.name.toUpperCase(), tone: "red" });
          }
          break;
        }
        case "approach":
          sc.beam = Math.min(1, sc.beam + dt * 0.8);
          if (red.mode === "pitch") { sc.stage = "pitch"; sc.t = 0; this.fx.push({ kind: "ring", x: red.x, z: red.z, tone: "red" }); }
          else if (sc.t > 25) { red.mode = "pitch"; red.modeT = 0; }
          break;
        case "pitch":
          sc.beam = 1;
          if (sc.outcome && sc.outcome !== "pending" && sc.t > 2.2) {
            sc.stage = "resolve"; sc.t = 0; sc.impact = false;
            if (isGuardWin(sc.outcome)) {
              const g = (sc.guardId && this.agents.get(sc.guardId)) || this.nearestGuard(red);
              if (g) { sc.guardId = g.spec.id; g.delay = 0; this.sendTo(g, this.nearPoint(g, red, 1.9), "dash"); }
            }
          }
          break;
        case "resolve":
          if (GOOD_OUTCOMES.includes(sc.outcome!)) {
            sc.flow = Math.min(1, sc.t / 2.2);
            green.status = "drained";
            if (!sc.impact && sc.flow >= 1) {
              sc.impact = true;
              red.flash = 1; green.flash = 1;
              const amt = sc.amount != null ? `+$${Math.round(sc.amount).toLocaleString()}` : "EXTRACTED";
              this.fx.push({ kind: "pop", x: red.x, z: red.z, text: amt, tone: "red" }, { kind: "ring", x: green.x, z: green.z, tone: "red" });
            }
            if (sc.t > 3) this.endScene(sc, red);
          } else {
            const g = sc.guardId ? this.agents.get(sc.guardId) : null;
            sc.beam = Math.max(0, sc.beam - dt * 1.5);
            if (!g) { sc.t = 99; }
            if (g && !sc.impact && (dist(g, red) < 2.8 || (g.mode !== "dash" && sc.t > 1))) {
              sc.impact = true;
              g.mode = "hold"; g.flash = 1; red.flash = 1;
              red.status = "caught"; red.mode = "caught"; red.modeT = 0;
              this.fx.push({ kind: "ring", x: red.x, z: red.z, tone: "blue" }, { kind: "pop", x: red.x, z: red.z, text: sc.outcome === "flagged" ? "FLAGGED" : "BLOCKED", tone: "blue" });
              sc.t = 0;
            }
            if ((sc.impact && sc.t > 3.2) || sc.t > 12) { if (g) this.sendTo(g, g.slot, "return"); this.endScene(sc, red); }
          }
          break;
        case "after":
          if (sc.t > 0.4 && red.mode === "hold") sc.stage = "done";
          if (sc.t > 18) sc.stage = "done";
          break;
      }
    }
    for (let i = this.scenes.length - 1; i >= 0; i--) if (this.scenes[i].stage === "done") this.scenes.splice(i, 1);
  }

  private endScene(sc: Scene, red: SimAgent) {
    sc.stage = "after"; sc.t = 0; sc.beam = 0;
    const green = this.agents.get(sc.greenId);
    if (green && green.status === "drained") green.status = "ok";
    red.status = "ok";
    this.sendTo(red, red.slot, "return");
  }

  private nearestGuard(from: SimAgent): SimAgent | null {
    let best: SimAgent | null = null, bd = Infinity;
    for (const a of this.agents.values()) {
      if (a.spec.team !== "blue" || a.mode === "dash") continue;
      const d = dist(a, from);
      if (d < bd) { bd = d; best = a; }
    }
    return best;
  }
}
