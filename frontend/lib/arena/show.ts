// The 90-second show: a director that walks the whole site in order. Owner: Dev R.
//
//   0:00  open      the flight over the Palace, the title
//   0:06  cast      the scroll tour at film speed: guards, clients, fraudsters
//   0:22  arena     everyone converges on the rotunda
//   0:27  off       controller OFF: the same attacks, nothing gated, the money walks out
//   0:43  on        rewind, controller ON: blue gates every dollar, one case goes to a human
//   1:05  compare   the two runs side by side
//   1:15  evolve    the agents rewrite their playbooks between generations
//   1:28  yours     hand over: launch an attack, flip the switch, click anyone
//
// The director only decides *when*; everything it does to the world goes through `ShowHost`, so it runs under vitest with a
// fake host and the React side (ArenaExperience) supplies the real one.

export type BeatId = "open" | "cast" | "arena" | "off" | "on" | "compare" | "evolve" | "yours";

export interface Beat {
  id: BeatId;
  /** short label for the progress bar */
  label: string;
  /** seconds from the start of the show */
  at: number;
  end: number;
  /** the line under the progress bar, while this beat plays; `from`/`to` are seconds into the beat */
  captions: { from: number; to: number; text: string; sub?: string }[];
}

export const SHOW_SECONDS = 90;

export const SHOW_BEATS: Beat[] = [
  { id: "open", label: "Open", at: 0, end: 6, captions: [] },
  { id: "cast", label: "The cast", at: 6, end: 22, captions: [] },
  { id: "arena", label: "Arena", at: 22, end: 27, captions: [{ from: 0.4, to: 5, text: "One company, three agents, one ledger.", sub: "Red steals. Green pays the bills. Blue guards the gate." }] },
  { id: "off", label: "Controller off", at: 27, end: 43, captions: [{ from: 0.4, to: 16, text: "Controller off. Fraud walks out.", sub: "Nothing checks a payment before it moves." }] },
  { id: "on", label: "Controller on", at: 43, end: 65, captions: [
    { from: 0.4, to: 12, text: "Rewind. Same seed. Controller on.", sub: "Blue checks every payment first." },
    { from: 12, to: 22, text: "Blue isn't sure, so it asks a person.", sub: "You decide: approve it and the money goes out; block it and it stays." },
  ] },
  { id: "compare", label: "Compare", at: 65, end: 75, captions: [{ from: 0.4, to: 10, text: "Same seed. Same fraud. Different ending." }] },
  { id: "evolve", label: "Evolve", at: 75, end: 88, captions: [{ from: 0.4, to: 13, text: "Then they learn.", sub: "Each agent rewrites its playbook between generations." }] },
  { id: "yours", label: "Your turn", at: 88, end: SHOW_SECONDS, captions: [{ from: 0, to: 2, text: "Your turn.", sub: "Launch an attack. Flip the controller. Click any agent." }] },
];

export type ShowStatus = "off" | "playing" | "paused" | "done";

/** Everything the director does to the world. */
export interface ShowHost {
  /** restart the intro flight from the top (cancel scripts, empty the arena of its showpieces) */
  restartIntro(): void;
  /** put the tour back at the top of the page, agents back on their lawns; ends the flight if it is still playing */
  restartTour(): void;
  /** the tour is on screen and scrolling (the intro flight has finished) */
  tourReady(): boolean;
  /** drive the page scroll, 0..1 */
  setScroll(frac: number): void;
  /** send everyone into the rotunda */
  converge(): void;
  /** begin an act: clears the scoreboard and plays the recorded run through the arena */
  startAct(act: "off" | "on"): void;
  setPanel(panel: "compare" | "evolve" | null): void;
  /** the evolution card advances through generations; 0..1 across the beat */
  evolveProgress(p: number): void;
  setCaption(text: string | null, sub?: string | null): void;
  /** called on every beat change, with the beat the show is now in */
  onBeat(beat: Beat, index: number): void;
  /** the last beat has run its course (the show hands over) */
  onDone(): void;
}

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));

export class ShowDirector {
  status: ShowStatus = "off";
  t = 0;
  index = -1;
  private captionKey = "";

  constructor(private host: ShowHost, readonly beats: Beat[] = SHOW_BEATS) {}

  get beat(): Beat | null { return this.index >= 0 ? this.beats[this.index] : null; }

  start() {
    this.status = "playing";
    this.t = 0;
    this.index = -1;
    this.captionKey = "";
    this.enter(0);
  }

  pause() { if (this.status === "playing") this.status = "paused"; }
  resume() { if (this.status === "paused") this.status = "playing"; }
  stop() { this.status = "off"; this.index = -1; this.host.setCaption(null); this.host.setPanel(null); }

  /** jump to the start of beat `i` */
  seek(i: number) {
    const k = Math.min(this.beats.length - 1, Math.max(0, i));
    this.status = this.status === "paused" ? "paused" : "playing";
    this.t = this.beats[k].at;
    this.enter(k);
  }
  next() { this.seek(this.index + 1); }
  prev() {
    // within the first two seconds of a beat, "back" means the beat before; later it restarts this one
    const b = this.beat;
    this.seek(b && this.t - b.at > 2 ? this.index : this.index - 1);
  }

  /** advance the clock; called once per animation frame with the frame time in seconds */
  update(dt: number) {
    if (this.status !== "playing") return;
    this.t += dt;
    const k = this.beats.findIndex((b) => this.t >= b.at && this.t < b.end);
    if (k < 0) {
      if (this.t >= this.beats[this.beats.length - 1].end) { this.status = "done"; this.host.setCaption(null); this.host.onDone(); }
      return;
    }
    if (k !== this.index) this.enter(k);
    this.drive();
  }

  private enter(k: number) {
    this.index = k;
    const b = this.beats[k];
    this.captionKey = "";
    this.host.onBeat(b, k);
    switch (b.id) {
      case "open":
        this.host.setPanel(null);
        this.host.restartIntro();
        break;
      case "cast":
        // the tour at the top of the page (skipping the flight if it is still going, rewinding if we jumped back here)
        this.host.restartTour();
        this.host.setPanel(null);
        break;
      case "arena":
        this.host.setPanel(null);
        this.host.setScroll(1);
        this.host.converge();
        break;
      case "off":
        this.host.setScroll(1);
        this.host.converge();
        this.host.setPanel(null);
        this.host.startAct("off");
        break;
      case "on":
        this.host.setPanel(null);
        this.host.startAct("on");
        break;
      case "compare":
        this.host.setPanel("compare");
        break;
      case "evolve":
        this.host.setPanel("evolve");
        break;
      case "yours":
        this.host.setPanel(null);
        break;
    }
    this.drive();
  }

  /** per-frame work inside the current beat: the tour scroll, the evolution card, the caption */
  private drive() {
    const b = this.beat;
    if (!b) return;
    const into = this.t - b.at;
    const len = b.end - b.at;
    if (b.id === "cast" && this.host.tourReady()) this.host.setScroll(clamp01(into / len));
    if (b.id === "evolve") this.host.evolveProgress(clamp01(into / len));
    const c = b.captions.find((x) => into >= x.from && into < x.to);
    const key = c ? `${b.id}:${c.text}` : "";
    if (key !== this.captionKey) { this.captionKey = key; this.host.setCaption(c?.text ?? null, c?.sub ?? null); }
  }
}
