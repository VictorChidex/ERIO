// How the globe decides to draw each country, kept pure so the rotation-sweep
// test (spec step 11) checks exactly what the globe does.

export const HALF_PI = Math.PI / 2;
/** Countries smaller than this (radians) are skipped when they touch the horizon. */
export const TINY = 0.06;

export type TraceMode = "skip" | "fast" | "clip";

/**
 * ``distance``: angle from the view centre to the country's centroid;
 * ``radius``: the country's angular radius from that centroid.
 * - wholly behind the globe: skip it;
 * - wholly in front: draw without horizon clipping (fast, and no clip artefacts);
 * - crossing the horizon: clip it, unless it is tiny (sub-pixel there, and
 *   clipping tiny rings can flood the whole sphere: the "full-sphere flash").
 */
export function traceMode(distance: number, radius: number): TraceMode {
  if (distance - radius > HALF_PI) return "skip";
  if (distance + radius < HALF_PI - 0.02) return "fast";
  if (radius < TINY) return "skip";
  return "clip";
}

/**
 * Whether a part clipped at the horizon came out right. An orthographic view
 * never makes a shape larger than its area on the sphere (scaled by the
 * globe's radius squared), so a clipped part that projects bigger than that
 * has been inverted by the clipper and would flood the globe. Such a part is
 * only a sliver at the horizon; skipping it for that frame is invisible.
 */
export function clipIsSound(projectedArea: number, sphereArea: number, radius: number): boolean {
  return projectedArea <= sphereArea * radius * radius * 1.05 + 2;
}
