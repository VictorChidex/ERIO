"use client";

import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import type { GlobeProps, Pin } from "@/components/Globe";
import { type Filters, toQuery } from "@/lib/filters";

// The globe's code and map data load only after the page is interactive, so
// it never delays the first paint (spec section 8).
const Globe = dynamic(() => import("@/components/Globe"), { ssr: false });

export type GlobeData = {
  codes: Record<string, string>;
  counts: Record<string, number>;
  worldwide: number;
  pins: Pin[];
};

function useIdle(): boolean {
  const [idle, setIdle] = useState(false);
  useEffect(() => {
    const win = window as Window & { requestIdleCallback?: (cb: () => void, o?: { timeout: number }) => number };
    if (win.requestIdleCallback) {
      win.requestIdleCallback(() => setIdle(true), { timeout: 1500 });
    } else {
      const timer = setTimeout(() => setIdle(true), 300);
      return () => clearTimeout(timer);
    }
  }, []);
  return idle;
}

type Shared = Omit<GlobeProps, "onPick" | "hint" | "label" | keyof GlobeData>;

function LazyGlobe(props: GlobeData & Shared & Pick<GlobeProps, "onPick" | "hint" | "label">) {
  const idle = useIdle();
  return idle ? <Globe {...props} /> : <div className="globe-canvas globe-placeholder" aria-hidden="true" />;
}

/** Home: clicking a country opens Search filtered to it. */
export function HomeGlobe({ data }: { data: GlobeData }) {
  const router = useRouter();
  return (
    <LazyGlobe
      {...data}
      hint="Click to see jobs here"
      label="Interactive globe. Drag to spin; click a country to see its jobs. The country list in the search box does the same."
      onPick={(code) => router.push(`/search?country=${code}`)}
    />
  );
}

/** Search: clicking a country adds or removes it; the globe turns to the latest. */
export function SearchGlobe({ data, filters }: { data: GlobeData; filters: Filters }) {
  const router = useRouter();
  const selected = filters.countries;
  return (
    <LazyGlobe
      {...data}
      selected={selected}
      spin={3.5}
      arcs={false}
      start={[-10, -22]}
      focus={selected[selected.length - 1] ?? null}
      hint="Click to add or remove"
      label="Globe showing selected countries. Click a country to add or remove it; the country list in the filters does the same."
      onPick={(code) => {
        const next = selected.includes(code) ? selected.filter((c) => c !== code) : [...selected, code];
        router.push(`/search${toQuery(filters, { countries: next })}`, { scroll: false });
      }}
    />
  );
}
