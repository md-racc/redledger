// Picks the render quality level from the frame rate. Owner: Dev R. Pure, so it is unit-tested (governor.test.ts).
//
// The old rule (drei's PerformanceMonitor: under 20 fps for about 1.5 s, one way only) turned any hiccup into a permanently
// flatter scene: a hidden pane, a shader compile, a window dragged to a bigger screen. This one only steps down after the
// frame rate has stayed low for several whole seconds, ignores stalls and the first seconds after load, and steps back up
// when the machine turns out to have headroom (twice at most, and never again once it has had to step down after stepping up).
export type Level = 0 | 1 | 2 | 3;

export interface GovernorOptions {
  /** average fps below this, for `downSeconds` windows in a row, steps down */
  floorFps: number;
  downSeconds: number;
  /** average fps at or above this, for `upSeconds` windows in a row, steps up */
  upFps: number;
  upSeconds: number;
  /** seconds of normal frames to ignore after the start (the glb decode, shader compiles) */
  settleSeconds: number;
  /** seconds after a step down before a step up is considered */
  cooldownSeconds: number;
  /** a frame longer than this is a stall (hidden tab, breakpoint, window drag), not a measurement */
  stallSeconds: number;
}

export const GOVERNOR_DEFAULTS: GovernorOptions = { floorFps: 24, downSeconds: 4, upFps: 52, upSeconds: 10, settleSeconds: 6, cooldownSeconds: 20, stallSeconds: 0.5 };

export class QualityGovernor {
  level: Level;
  private readonly o: GovernorOptions;
  private settle: number;
  private cooldown = 0;
  private acc = 0;
  private frames = 0;
  private low = 0;
  private high = 0;
  private ups = 0;
  private locked = false;
  private steppedUp = false;

  constructor(readonly start: Level, options: Partial<GovernorOptions> = {}) {
    this.o = { ...GOVERNOR_DEFAULTS, ...options };
    this.level = start;
    this.settle = this.o.settleSeconds;
  }

  /** Feed one rendered frame (`dt` seconds since the previous one). Returns the new level when it changed. */
  frame(dt: number): Level | null {
    if (dt > this.o.stallSeconds || dt <= 0) { this.acc = 0; this.frames = 0; this.low = 0; this.high = 0; return null; }
    if (this.settle > 0) { this.settle -= dt; return null; }
    this.acc += dt;
    this.frames++;
    if (this.acc < 1) return null;
    const fps = this.frames / this.acc;
    this.acc = 0;
    this.frames = 0;
    if (this.cooldown > 0) this.cooldown--;

    if (fps < this.o.floorFps) { this.low++; this.high = 0; }
    else if (fps >= this.o.upFps) { this.high++; this.low = 0; }
    else { this.low = 0; this.high = 0; }

    if (this.low >= this.o.downSeconds && this.level > 0) {
      this.level = (this.level - 1) as Level;
      this.low = 0;
      this.cooldown = this.o.cooldownSeconds;
      if (this.steppedUp) this.locked = true; // it could not hold the higher level: stop trying
      return this.level;
    }
    if (this.high >= this.o.upSeconds && this.level < this.start && !this.locked && this.ups < 2 && this.cooldown === 0) {
      this.level = (this.level + 1) as Level;
      this.high = 0;
      this.ups++;
      this.steppedUp = true;
      return this.level;
    }
    return null;
  }
}
