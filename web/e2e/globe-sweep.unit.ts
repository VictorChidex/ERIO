// Rotation sweep (spec step 11): at every rotation, no country the globe draws
// may cover more than a sensible share of the sphere. A "full-sphere flash"
// happens when clipping a degenerate ring fills the whole disc; this sweep
// checks the exact trace rule and map data the globe uses.

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, test } from "@playwright/test";
import { geoArea, geoCentroid, geoDistance, geoOrthographic, geoPath } from "d3-geo";
import type { Feature, Geometry, Polygon } from "geojson";
import { feature } from "topojson-client";
import type { GeometryCollection, Topology } from "topojson-specification";

import { clipIsSound, traceMode } from "../lib/globe-geometry";

type Props = { n: string; ll: [number, number] };

const world = JSON.parse(readFileSync(join(__dirname, "..", "public", "geo", "world.json"), "utf8")) as Topology;
const countries = (
  feature(world, world.objects.countries as GeometryCollection<Props>) as unknown as { features: Feature<Geometry, Props>[] }
).features;

function radius(centre: [number, number], coords: unknown): number {
  if (Array.isArray(coords) && typeof coords[0] === "number") return geoDistance(centre, coords as [number, number]);
  return Array.isArray(coords) ? Math.max(0, ...coords.map((c) => radius(centre, c))) : 0;
}

function polygons(geometry: Geometry): Polygon[] {
  if (geometry.type === "Polygon") return [geometry];
  if (geometry.type === "MultiPolygon") return geometry.coordinates.map((coordinates) => ({ type: "Polygon", coordinates }));
  return [];
}

const caps = countries.map((f) => ({
  f,
  c: f.properties.ll,
  r: radius(f.properties.ll, (f.geometry as { coordinates?: unknown }).coordinates),
  parts: polygons(f.geometry).map((g) => {
    const c = geoCentroid(g);
    return { g, c, r: radius(c, g.coordinates), area: geoArea(g) };
  }),
}));
const R = 200;
const DISC = Math.PI * R * R;
// Russia, the largest country, covers about a fifth of the visible disc at most.
const LARGEST_SHARE = 0.4;

test("the map has the 233 countries the country list shows", () => {
  expect(countries).toHaveLength(233);
});

test("no rotation makes any country flood the sphere", () => {
  const clip = geoOrthographic().clipAngle(90).precision(0).scale(R).translate([R, R]);
  const fast = geoOrthographic().clipAngle(null).precision(0).scale(R).translate([R, R]);
  const clipPath = geoPath(clip);
  const fastPath = geoPath(fast);
  let checked = 0;
  for (let lon = -180; lon < 180; lon += 10) {
    for (let lat = -60; lat <= 60; lat += 15) {
      const rotate: [number, number, number] = [lon, lat, 0];
      clip.rotate(rotate);
      fast.rotate(rotate);
      const centre: [number, number] = [-lon, -lat];
      for (const cap of caps) {
        // Exactly what the globe draws (components/Globe.tsx, trace).
        const mode = traceMode(geoDistance(cap.c, centre), cap.r);
        if (mode === "skip") continue;
        let area = 0;
        if (mode === "fast") {
          area = fastPath.area(cap.f);
        } else {
          for (const part of cap.parts) {
            const partMode = traceMode(geoDistance(part.c, centre), part.r);
            if (partMode === "fast") area += fastPath.area(part.g);
            else if (partMode === "clip") {
              const projected = clipPath.area(part.g);
              if (clipIsSound(projected, part.area, R)) area += projected;
            }
          }
        }
        checked++;
        expect(area / DISC, `${cap.f.properties.n} at rotation ${lon},${lat} (${mode})`).toBeLessThan(LARGEST_SHARE);
      }
    }
  }
  expect(checked).toBeGreaterThan(10_000);
});

test("the clip guard catches the real flood case (mainland Greece seen edge-on)", () => {
  const greece = caps.find((cap) => cap.f.properties.n === "Greece")!;
  const mainland = [...greece.parts].sort((a, b) => b.area - a.area)[0]!;
  const clip = geoOrthographic().clipAngle(90).precision(0).scale(R).translate([R, R]).rotate([-110, 0, 0]);
  const projected = geoPath(clip).area(mainland.g);
  expect(projected / DISC).toBeGreaterThan(0.9); // the clipper floods here
  expect(clipIsSound(projected, mainland.area, R)).toBe(false); // and the guard rejects it
});
