// The "auto-cam" shot: while a fraud attempt plays out (a fraudster walking up to a client, working it, and the guard
// that runs it down or the money flowing away), the arena camera frames the action. ArenaWorld writes this each frame from
// the sim; CameraRig reads it. Pure data, no three.js.
export const cinema = {
  /** true while there is a scene to frame (and for a short hold after the last one ends) */
  active: false,
  /** centre of the action, world space */
  x: 0,
  y: 2.5,
  z: 0,
  /** camera distance that frames everyone involved */
  dist: 30,
  /** seconds left to keep the shot after the last scene ended */
  hold: 0,
  /** 0..1: how far into the moment the scene is (the shot dollies in a little as it plays) */
  push: 0,
};

/** the cut-in is quick: it ends a beat after the outcome */
export const HOLD_SECONDS = 0.9;
