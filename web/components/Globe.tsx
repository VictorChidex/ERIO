"use client";

// The interactive globe, ported from the prototype with all of its fixes
// (spec section 8): simplified Natural Earth data with zero-area rings
// removed, pre-rendered lighting layers, countries behind the globe skipped
// and fully visible ones drawn without horizon clipping, tiny countries at
// the horizon skipped (clipping them could flood the whole sphere),
// time-based eased motion with drag inertia, and no drawing while off-screen.

import {
  type GeoPermissibleObjects,
  geoArea,
  geoCentroid,
  geoContains,
  geoDistance,
  geoGraticule,
  geoInterpolate,
  geoOrthographic,
  geoPath,
} from "d3-geo";
import type { Feature, Geometry, LineString, MultiLineString, Polygon } from "geojson";
import { useEffect, useRef, useState } from "react";
import { feature, mesh } from "topojson-client";
import type { GeometryCollection, Topology } from "topojson-specification";

import { clipIsSound, traceMode } from "@/lib/globe-geometry";

export type Pin = { lat: number; lon: number; count: number };
export type GlobeProps = {
  /** Country name -> ISO code, for names the map uses. */
  codes: Record<string, string>;
  /** Jobs a filter on each country returns, by ISO code. */
  counts: Record<string, number>;
  worldwide: number;
  pins: Pin[];
  selected?: string[];
  spin?: number;
  arcs?: boolean;
  start?: [number, number];
  hint: string;
  label: string;
  onPick: (code: string) => void;
  /** Country to turn towards, e.g. the last one selected. */
  focus?: string | null;
};

type CountryProps = { n: string; c: number; ll: [number, number] };
type CountryFeature = Feature<Geometry, CountryProps>;
type Part = { g: Polygon; c: [number, number]; r: number; area: number };
type LinePiece = { g: LineString; c: [number, number]; r: number };
type Cap = { f: CountryFeature; c: [number, number]; r: number; col: string; parts: Part[] };
type Arc = { i: (t: number) => [number, number]; t: number; sp: number; h: number };

const PALETTE = ["#f2d779", "#bcd98c", "#f3b8a6", "#f5c077", "#ecdfb2", "#d5c3e4"];
const H = Math.PI / 2;
let worldPromise: Promise<Topology> | null = null;

function loadWorld(): Promise<Topology> {
  worldPromise ??= fetch("/geo/world.json").then((r) => r.json() as Promise<Topology>);
  return worldPromise;
}

function polygons(geometry: Geometry): Polygon[] {
  if (geometry.type === "Polygon") return [geometry];
  if (geometry.type === "MultiPolygon") return geometry.coordinates.map((coordinates) => ({ type: "Polygon", coordinates }));
  return [];
}

function maxDistance(c: [number, number], coords: unknown): number {
  if (Array.isArray(coords) && typeof coords[0] === "number") return geoDistance(c, coords as [number, number]);
  return Array.isArray(coords) ? Math.max(0, ...coords.map((x) => maxDistance(c, x))) : 0;
}

export default function Globe(props: GlobeProps) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const live = useRef(props);
  live.current = props;
  const api = useRef<{ flyTo: (code: string) => void } | null>(null);
  const [tip, setTip] = useState<{ x: number; y: number; name: string; count: number } | null>(null);

  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    let stopped = false;
    let cleanup = () => {};
    loadWorld().then((world) => {
      if (stopped) return;
      cleanup = run(el, world);
    });
    return () => {
      stopped = true;
      cleanup();
    };

    function run(node: HTMLCanvasElement, world: Topology): () => void {
      const ctx = node.getContext("2d");
      if (!ctx) return () => {};
      const object = world.objects.countries as GeometryCollection<CountryProps>;
      const features = (feature(world, object) as unknown as { features: CountryFeature[] }).features;
      const caps: Cap[] = features.map((f) => ({
        f,
        c: f.properties.ll,
        r: maxDistance(f.properties.ll, (f.geometry as { coordinates?: unknown }).coordinates),
        col: PALETTE[f.properties.c] ?? PALETTE[0]!,
        parts: polygons(f.geometry).map((g) => {
          const c = geoCentroid(g);
          return { g, c, r: maxDistance(c, g.coordinates), area: geoArea(g) };
        }),
      }));
      const capOf = new Map(caps.map((k) => [k.f, k]));
      const byColour = new Map<string, Cap[]>();
      for (const k of caps) byColour.set(k.col, [...(byColour.get(k.col) ?? []), k]);
      const byCode = new Map<string, CountryFeature>();
      for (const f of features) {
        const code = live.current.codes[f.properties.n];
        if (code) byCode.set(code, f);
      }
      // Borders and coastlines as separate line pieces, each with a bounding
      // cap, so pieces behind the globe are skipped like countries are.
      const pieces = (lines: MultiLineString): LinePiece[] =>
        lines.coordinates.map((coordinates) => {
          const g: LineString = { type: "LineString", coordinates };
          const c = geoCentroid(g);
          return { g, c, r: maxDistance(c, coordinates) };
        });
      const borders = pieces(mesh(world, object, (a, b) => a !== b) as MultiLineString);
      const coast = pieces(mesh(world, object, (a, b) => a === b) as MultiLineString);
      const grat = geoGraticule().step([15, 15])();
      const equator: GeoPermissibleObjects = { type: "LineString", coordinates: [[-180, 0], [-90, 0], [0, 0], [90, 0], [180, 0]] };

      const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      const spin = reduced ? 0 : (live.current.spin ?? 7);
      const showArcs = !reduced && (live.current.arcs ?? true);
      const proj = geoOrthographic().clipAngle(90).precision(0);
      const path = geoPath(proj, ctx);
      // No horizon clipping: only used for countries known to be fully visible.
      const projFast = geoOrthographic().clipAngle(null).precision(0);
      const pathFast = geoPath(projFast, ctx);

      const start = live.current.start ?? [-10, -18];
      const rot: [number, number, number] = [start[0], start[1], 0];
      let target: [number, number] | null = null;
      let hover: CountryFeature | null = null;
      let idleUntil = 0;
      let drag: { x: number; y: number; r: [number, number, number]; moved: boolean; lx: number; ly: number; lt: number; vx: number; vy: number } | null = null;
      let arcs: Arc[] = [];
      let W = 0, R = 0, cx = 0, cy = 0, dpr = 1, t = 0, last = 0, vel = 0, spawnClock = 0;
      let momentum: [number, number] = [0, 0];
      let onScreen = true, needSize = true, frameId = 0;
      const drawTimes: number[] = [];
      let pendingPick: { clientX: number; clientY: number } | null = null;
      let back: HTMLCanvasElement | null = null, front: HTMLCanvasElement | null = null, layerKey = "";

      const resize = new ResizeObserver(() => { needSize = true; });
      resize.observe(node);
      const seen = new IntersectionObserver((es) => { onScreen = es[0]?.isIntersecting ?? true; }, { rootMargin: "80px" });
      seen.observe(node);

      function size(): boolean {
        const w = node.clientWidth;
        if (!w) return false;
        dpr = Math.min(window.devicePixelRatio || 1, 2);
        if (W !== w || node.width !== Math.round(w * dpr)) {
          W = w;
          node.width = Math.round(w * dpr);
          node.height = Math.round(w * dpr);
          layerKey = "";
        }
        R = W * 0.42; cx = W / 2; cy = W * 0.47; needSize = false;
        return true;
      }
      function layer(fn: (x: CanvasRenderingContext2D) => void): HTMLCanvasElement {
        const c = document.createElement("canvas");
        c.width = node.width; c.height = node.height;
        const x = c.getContext("2d")!;
        x.setTransform(dpr, 0, 0, dpr, 0, 0);
        fn(x);
        return c;
      }
      // Lighting is rendered once per size and theme, not every frame.
      function buildLayers(dark: boolean) {
        const key = `${W}|${dpr}|${dark}`;
        if (key === layerKey) return;
        layerKey = key;
        back = layer((x) => {
          x.save(); x.translate(cx, cy + R * 1.1); x.scale(1, 0.12);
          let g = x.createRadialGradient(0, 0, 0, 0, 0, R * 0.8);
          g.addColorStop(0, dark ? "rgba(0,0,0,.55)" : "rgba(15,30,60,.32)"); g.addColorStop(1, "rgba(0,0,0,0)");
          x.fillStyle = g; x.beginPath(); x.arc(0, 0, R * 0.8, 0, Math.PI * 2); x.fill(); x.restore();
          g = x.createRadialGradient(cx, cy, R * 0.96, cx, cy, R * 1.14);
          g.addColorStop(0, dark ? "rgba(110,170,255,.45)" : "rgba(80,140,230,.28)"); g.addColorStop(1, "rgba(110,170,255,0)");
          x.fillStyle = g; x.beginPath(); x.arc(cx, cy, R * 1.14, 0, Math.PI * 2); x.fill();
          g = x.createRadialGradient(cx - R * 0.3, cy - R * 0.35, R * 0.05, cx, cy, R);
          g.addColorStop(0, "#b6e1f6"); g.addColorStop(0.45, "#79b9e6"); g.addColorStop(0.85, "#4a8bcb"); g.addColorStop(1, "#2f68a6");
          x.fillStyle = g; x.beginPath(); x.arc(cx, cy, R, 0, Math.PI * 2); x.fill();
        });
        front = layer((x) => {
          let g = x.createRadialGradient(cx - R * 0.42, cy - R * 0.48, 0, cx - R * 0.1, cy - R * 0.1, R * 1.3);
          g.addColorStop(0, "rgba(255,255,255,.42)"); g.addColorStop(0.3, "rgba(255,255,255,.08)"); g.addColorStop(0.62, "rgba(0,0,0,0)"); g.addColorStop(1, "rgba(4,18,46,.62)");
          x.fillStyle = g; x.beginPath(); x.arc(cx, cy, R, 0, Math.PI * 2); x.fill();
          g = x.createRadialGradient(cx - R * 0.45, cy - R * 0.52, 0, cx - R * 0.45, cy - R * 0.52, R * 0.22);
          g.addColorStop(0, "rgba(255,255,255,.5)"); g.addColorStop(1, "rgba(255,255,255,0)");
          x.fillStyle = g; x.beginPath(); x.arc(cx - R * 0.45, cy - R * 0.52, R * 0.22, 0, Math.PI * 2); x.fill();
          x.beginPath(); x.arc(cx, cy, R, 0, Math.PI * 2); x.strokeStyle = "rgba(255,255,255,.35)"; x.lineWidth = 1; x.stroke();
        });
      }

      const centre = (): [number, number] => [-rot[0], -rot[1]];
      const lifted = (ll: [number, number], h: number): [number, number] => {
        const p = proj(ll)!;
        return [cx + (p[0] - cx) * (1 + h), cy + (p[1] - cy) * (1 + h)];
      };
      // Fully visible countries skip horizon clipping; tiny ones touching the
      // horizon are skipped (sub-pixel there, and clipping them can flood the sphere).
      function trace(f: CountryFeature): boolean {
        const k = capOf.get(f)!;
        const mode = traceMode(geoDistance(k.c, centre()), k.r);
        if (mode === "skip") return false;
        if (mode === "fast") { pathFast(f); return true; }
        // Crossing the horizon: draw part by part, so one bad clip (an island,
        // or a mainland seen edge-on) cannot flood the globe.
        let drew = false;
        for (const part of k.parts) {
          const partMode = traceMode(geoDistance(part.c, centre()), part.r);
          if (partMode === "skip") continue;
          if (partMode === "fast") pathFast(part.g);
          else if (clipIsSound(path.area(part.g), part.area, R)) path(part.g);
          else continue;
          drew = true;
        }
        return drew;
      }
      function traceLines(lines: LinePiece[]) {
        const c = centre();
        for (const line of lines) {
          const mode = traceMode(geoDistance(line.c, c), line.r);
          if (mode === "fast") pathFast(line.g);
          else if (mode === "clip") path(line.g);
        }
      }
      function spawnArc() {
        const pins = live.current.pins;
        if (pins.length < 2) return;
        const pick = () => pins[Math.floor(Math.random() * pins.length)]!;
        const a = pick();
        let b = pick(), tries = 0;
        while ((a === b || geoDistance([a.lon, a.lat], [b.lon, b.lat]) < 0.35) && tries++ < 10) b = pick();
        const d = geoDistance([a.lon, a.lat], [b.lon, b.lat]);
        arcs.push({ i: geoInterpolate([a.lon, a.lat], [b.lon, b.lat]), t: 0, sp: 0.36 + Math.random() * 0.3, h: Math.min(0.28, d * 0.12) });
      }
      function step(dt: number) {
        const now = performance.now();
        if (target) {
          const k = 1 - Math.exp(-dt * 4.5);
          const d0 = ((target[0] - rot[0] + 540) % 360) - 180, d1 = target[1] - rot[1];
          rot[0] += d0 * k; rot[1] += d1 * k;
          if (Math.abs(d0) < 0.05 && Math.abs(d1) < 0.05) target = null;
          vel = 0; momentum = [0, 0];
        } else if (!drag) {
          if (Math.abs(momentum[0]) + Math.abs(momentum[1]) > 0.01) {
            rot[0] += momentum[0] * dt;
            rot[1] = Math.max(-65, Math.min(65, rot[1] + momentum[1] * dt));
            const f = Math.exp(-dt * 2.2); momentum = [momentum[0] * f, momentum[1] * f];
          }
          const want = hover || now < idleUntil ? 0 : spin;
          vel += (want - vel) * (1 - Math.exp(-dt * (want ? 1.2 : 4)));
          rot[0] += vel * dt;
        }
        rot[0] = ((((rot[0] + 180) % 360) + 360) % 360) - 180;
        proj.scale(R).translate([cx, cy]).rotate(rot);
        projFast.scale(R).translate([cx, cy]).rotate(rot);
      }
      function draw() {
        if (!ctx) return;
        const dark = document.documentElement.dataset.theme !== "light";
        buildLayers(dark);
        ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, node.width, node.height);
        if (back) ctx.drawImage(back, 0, 0);
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.beginPath(); path(grat); ctx.strokeStyle = "rgba(255,255,255,.3)"; ctx.lineWidth = 0.6; ctx.stroke();
        // One fill per map colour: countries never overlap, so this draws the
        // same picture with 6 fills instead of 233.
        for (const [colour, group] of byColour) {
          ctx.beginPath();
          let any = false;
          for (const k of group) any = trace(k.f) || any;
          if (any) { ctx.fillStyle = colour; ctx.fill(); }
        }
        const selected = live.current.selected ?? [];
        if (selected.length) {
          ctx.fillStyle = `rgba(226,72,56,${0.78 + 0.12 * Math.sin(t * 3.2)})`;
          for (const code of selected) { const f = byCode.get(code); if (f) { ctx.beginPath(); if (trace(f)) ctx.fill(); } }
        }
        if (hover) { ctx.beginPath(); if (trace(hover)) { ctx.fillStyle = "rgba(255,255,255,.38)"; ctx.fill(); } }
        ctx.beginPath(); traceLines(borders); ctx.strokeStyle = "rgba(120,88,52,.55)"; ctx.lineWidth = 0.5; ctx.stroke();
        ctx.beginPath(); traceLines(coast); ctx.strokeStyle = "rgba(28,72,128,.6)"; ctx.lineWidth = 0.7; ctx.stroke();
        if (hover) { ctx.beginPath(); if (trace(hover)) { ctx.strokeStyle = "rgba(40,30,20,.85)"; ctx.lineWidth = 1.3; ctx.stroke(); } }
        ctx.beginPath(); path(equator); ctx.setLineDash([3, 3]); ctx.strokeStyle = "rgba(20,50,95,.5)"; ctx.lineWidth = 0.8; ctx.stroke(); ctx.setLineDash([]);
        if (showArcs) {
          ctx.lineCap = "round";
          for (const a of arcs) {
            const head = Math.min(a.t, 1), tail = Math.max(0, a.t - 0.45);
            const fade = a.t > 1 ? 1 - (a.t - 1) / 0.45 : Math.min(1, a.t * 6);
            let prev: { p: [number, number]; e: number } | null = null;
            for (let s = 0; s <= 28; s++) {
              const tt = tail + ((head - tail) * s) / 28, ll = a.i(tt);
              const edge = Math.max(0, Math.min(1, (H - geoDistance(ll, centre())) / 0.12));
              const p = lifted(ll, a.h * Math.sin(Math.PI * tt));
              if (prev && edge > 0 && prev.e > 0) {
                ctx.beginPath(); ctx.moveTo(prev.p[0], prev.p[1]); ctx.lineTo(p[0], p[1]);
                ctx.strokeStyle = `rgba(214,40,57,${0.85 * fade * Math.min(edge, prev.e) * (0.35 + (0.65 * s) / 28)})`;
                ctx.lineWidth = 1.6; ctx.stroke();
              }
              prev = { p, e: edge };
            }
          }
        }
        for (const pin of live.current.pins) {
          const ll: [number, number] = [pin.lon, pin.lat];
          const dist = geoDistance(ll, centre());
          if (dist > H - 0.02) continue;
          const p = proj(ll)!;
          const rad = Math.max(2, Math.min(4.2, 1.6 + Math.log2(1 + pin.count) * 0.45)) * (W < 260 ? 0.8 : 1);
          const ph = ((((t * 0.75 + pin.lon * 0.033) % 1) + 1) % 1);
          ctx.globalAlpha = Math.min(1, (H - 0.02 - dist) / 0.15);
          if (!reduced) { ctx.beginPath(); ctx.arc(p[0], p[1], rad + ph * 9, 0, Math.PI * 2); ctx.strokeStyle = `rgba(214,40,57,${0.55 * (1 - ph)})`; ctx.lineWidth = 1.2; ctx.stroke(); }
          ctx.beginPath(); ctx.arc(p[0], p[1], rad, 0, Math.PI * 2); ctx.fillStyle = "#d62839"; ctx.fill(); ctx.strokeStyle = "#fff"; ctx.stroke();
        }
        ctx.globalAlpha = 1;
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        if (front) ctx.drawImage(front, 0, 0);
      }
      function pick(ev: { clientX: number; clientY: number }): CountryFeature | null {
        const r = node.getBoundingClientRect(), x = ev.clientX - r.left, y = ev.clientY - r.top;
        if (Math.hypot(x - cx, y - cy) > R) return null;
        const ll = proj.invert?.([x, y]);
        if (!ll) return null;
        for (const k of caps) {
          if (geoDistance(k.c, ll) > k.r + 0.01) continue;
          if (geoContains(k.f, ll)) return k.f;
        }
        return null;
      }
      function showTip(ev: { clientX: number; clientY: number }, f: CountryFeature | null) {
        if (!f) { setTip(null); return; }
        const code = live.current.codes[f.properties.n];
        setTip({ x: ev.clientX, y: ev.clientY, name: f.properties.n, count: code ? (live.current.counts[code] ?? 0) : 0 });
      }
      function frame(now: number) {
        frameId = requestAnimationFrame(frame);
        const dt = Math.min(0.05, last ? (now - last) / 1000 : 0.016);
        last = now;
        if (!onScreen || !node.offsetParent || document.hidden) return;
        if (needSize && !size()) return;
        t += dt;
        if (showArcs) {
          arcs.forEach((a) => { a.t += a.sp * dt; });
          arcs = arcs.filter((a) => a.t < 1.45);
          spawnClock += dt;
          if (spawnClock > 0.6 && arcs.length < 9) { spawnClock = 0; spawnArc(); }
        }
        step(dt);
        if (pendingPick) { const e = pendingPick; pendingPick = null; hover = pick(e); node.classList.toggle("pointing", !!hover); showTip(e, hover); }
        const began = performance.now();
        try { draw(); } catch (error) { console.error(error); }
        // Median draw time over the last 60 frames, for the frame-budget test.
        drawTimes.push(performance.now() - began);
        if (drawTimes.length === 60) {
          node.dataset.drawMs = [...drawTimes].sort((a, b) => a - b)[30]!.toFixed(2);
          drawTimes.length = 0;
        }
      }

      const down = (e: PointerEvent) => {
        drag = { x: e.clientX, y: e.clientY, r: [...rot] as [number, number, number], moved: false, lx: e.clientX, ly: e.clientY, lt: performance.now(), vx: 0, vy: 0 };
        target = null; momentum = [0, 0]; vel = 0;
        node.setPointerCapture(e.pointerId); node.classList.add("dragging");
      };
      const move = (e: PointerEvent) => {
        if (drag) {
          const dx = e.clientX - drag.x, dy = e.clientY - drag.y, k = 180 / (Math.PI * R);
          if (Math.abs(dx) + Math.abs(dy) > 4) drag.moved = true;
          rot[0] = drag.r[0] + dx * k;
          rot[1] = Math.max(-65, Math.min(65, drag.r[1] - dy * k));
          const now = performance.now(), ddt = Math.max(1, now - drag.lt) / 1000;
          drag.vx = drag.vx * 0.6 + 0.4 * (((e.clientX - drag.lx) * k) / ddt);
          drag.vy = drag.vy * 0.6 + 0.4 * ((-(e.clientY - drag.ly) * k) / ddt);
          drag.lx = e.clientX; drag.ly = e.clientY; drag.lt = now;
          if (drag.moved) { hover = null; setTip(null); }
          return;
        }
        if (e.pointerType === "mouse") pendingPick = { clientX: e.clientX, clientY: e.clientY };
      };
      const up = (e: PointerEvent) => {
        node.classList.remove("dragging");
        if (drag) {
          if (!drag.moved) {
            const f = pick(e);
            const code = f ? live.current.codes[f.properties.n] : undefined;
            if (code) { setTip(null); live.current.onPick(code); }
          } else if (performance.now() - drag.lt < 80) {
            const c = (v: number) => Math.max(-400, Math.min(400, v));
            momentum = [c(drag.vx), c(drag.vy)];
          }
        }
        drag = null; idleUntil = performance.now() + 1800;
      };
      const cancel = () => { drag = null; node.classList.remove("dragging"); idleUntil = performance.now() + 1800; };
      const leave = () => { if (!drag) { pendingPick = null; hover = null; setTip(null); node.classList.remove("pointing"); } };
      node.addEventListener("pointerdown", down);
      node.addEventListener("pointermove", move);
      node.addEventListener("pointerup", up);
      node.addEventListener("pointercancel", cancel);
      node.addEventListener("pointerleave", leave);

      if (showArcs) for (let i = 0; i < 4; i++) { spawnArc(); const a = arcs[i]; if (a) a.t = Math.random() * 0.9; }
      api.current = {
        flyTo(code: string) {
          const f = byCode.get(code);
          if (!f) return;
          const [lon, lat] = f.properties.ll;
          target = [-lon, Math.max(-55, Math.min(55, -lat))];
          momentum = [0, 0]; idleUntil = performance.now() + 4000;
        },
      };
      if (live.current.focus) api.current.flyTo(live.current.focus);
      frameId = requestAnimationFrame(frame);
      node.dataset.ready = "true";
      node.dataset.motion = reduced ? "reduced" : "full";

      return () => {
        cancelAnimationFrame(frameId);
        resize.disconnect(); seen.disconnect();
        node.removeEventListener("pointerdown", down); node.removeEventListener("pointermove", move);
        node.removeEventListener("pointerup", up); node.removeEventListener("pointercancel", cancel);
        node.removeEventListener("pointerleave", leave);
      };
    }
  }, []);

  useEffect(() => {
    if (props.focus) api.current?.flyTo(props.focus);
  }, [props.focus]);

  return (
    <>
      <canvas ref={canvas} className="globe-canvas" role="img" aria-label={props.label} />
      {tip && (
        <div id="gtip" className="on" style={{ left: tip.x, top: tip.y }} role="tooltip">
          <b>{tip.name}</b>
          <span>
            {tip.count ? `${tip.count} job${tip.count === 1 ? "" : "s"}` : "Remote roles only"} · {props.worldwide} worldwide-remote
          </span>
          <em>{props.hint}</em>
        </div>
      )}
    </>
  );
}
