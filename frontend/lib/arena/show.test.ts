import { describe, expect, it } from "vitest";
import { SHOW_BEATS, SHOW_SECONDS, ShowDirector, type ShowHost } from "./show";

function fakeHost() {
  const log: string[] = [];
  const scrolls: number[] = [];
  let ready = false;
  const host: ShowHost = {
    restartIntro: () => log.push("intro"),
    restartTour: () => { log.push("tour"); ready = true; },
    tourReady: () => ready,
    setScroll: (f) => scrolls.push(f),
    converge: () => log.push("converge"),
    startAct: (a) => log.push(`act:${a}`),
    setPanel: (p) => log.push(`panel:${p}`),
    evolveProgress: () => {},
    setCaption: (t) => log.push(`cap:${t}`),
    onBeat: (b) => log.push(`beat:${b.id}`),
    onDone: () => log.push("done"),
  };
  return { host, log, scrolls };
}

const play = (d: ShowDirector, seconds: number, dt = 1 / 30) => { for (let t = 0; t < seconds; t += dt) d.update(dt); };

describe("the 90-second show", () => {
  it("covers the whole site in about a minute and a half, with no gaps between beats", () => {
    expect(SHOW_SECONDS).toBe(90);
    expect(SHOW_BEATS[0].at).toBe(0);
    for (let i = 1; i < SHOW_BEATS.length; i++) expect(SHOW_BEATS[i].at).toBe(SHOW_BEATS[i - 1].end);
    expect(SHOW_BEATS[SHOW_BEATS.length - 1].end).toBe(SHOW_SECONDS);
  });

  it("plays every beat in order and then hands over", () => {
    const { host, log } = fakeHost();
    const d = new ShowDirector(host);
    d.start();
    play(d, 95);
    expect(log.filter((l) => l.startsWith("beat:"))).toEqual(SHOW_BEATS.map((b) => `beat:${b.id}`));
    expect(log).toContain("act:off");
    expect(log.indexOf("act:off")).toBeLessThan(log.indexOf("act:on"));
    expect(log.indexOf("panel:compare")).toBeLessThan(log.indexOf("panel:evolve"));
    expect(log[log.length - 1]).toBe("done");
    expect(d.status).toBe("done");
  });

  it("scrolls the tour from top to bottom across the cast beat", () => {
    const { host, scrolls } = fakeHost();
    const d = new ShowDirector(host);
    d.start();
    play(d, 22);
    const tour = scrolls.filter((s) => s < 1);
    expect(tour.length).toBeGreaterThan(100);
    for (let i = 1; i < tour.length; i++) expect(tour[i]).toBeGreaterThanOrEqual(tour[i - 1] - 1e-9);
    expect(tour[0]).toBeLessThan(0.05);
    expect(tour[tour.length - 1]).toBeGreaterThan(0.95);
  });

  it("holds still while paused and resumes where it left off", () => {
    const { host } = fakeHost();
    const d = new ShowDirector(host);
    d.start();
    play(d, 10);
    d.pause();
    const t = d.t;
    play(d, 5);
    expect(d.t).toBe(t);
    d.resume();
    play(d, 1);
    expect(d.t).toBeGreaterThan(t);
  });

  it("jumps: next goes to the next beat, back restarts a beat or steps to the one before", () => {
    const { host, log } = fakeHost();
    const d = new ShowDirector(host);
    d.start();
    d.next();
    expect(d.beat!.id).toBe("cast");
    expect(log).toContain("tour");
    d.seek(3);
    expect(d.beat!.id).toBe("off");
    expect(d.t).toBe(SHOW_BEATS[3].at);
    play(d, 5);
    d.prev(); // 5 s in: restarts the beat
    expect(d.beat!.id).toBe("off");
    d.prev(); // right at the start: the one before
    expect(d.beat!.id).toBe("arena");
  });

  it("shows a caption while the controller is off, and clears it when stopped", () => {
    const { host, log } = fakeHost();
    const d = new ShowDirector(host);
    d.start();
    d.seek(3);
    play(d, 2);
    expect(log.filter((l) => l.startsWith("cap:")).pop()).toMatch(/Controller off/);
    d.stop();
    expect(log.filter((l) => l.startsWith("cap:")).pop()).toBe("cap:null");
    expect(d.status).toBe("off");
  });
});
