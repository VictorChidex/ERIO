"use client";

import { useRouter } from "next/navigation";
import { type ReactNode, useRef } from "react";

/**
 * The search form. Without JavaScript it submits as a normal GET form. With
 * it, any change applies at once and the URL is written in its canonical
 * comma-separated form (country=NG,CA) so it can be copied and shared.
 */
export function FilterForm({ children, className }: { children: ReactNode; className?: string }) {
  const router = useRouter();
  const form = useRef<HTMLFormElement>(null);

  function apply() {
    if (!form.current) return;
    const data = new FormData(form.current);
    const params = new URLSearchParams();
    const grouped = new Map<string, string[]>();
    for (const [key, value] of data.entries()) {
      const text = String(value).trim();
      if (!text) continue;
      grouped.set(key, [...(grouped.get(key) ?? []), text]);
    }
    for (const [key, list] of grouped) {
      if (key === "ww") continue;
      params.set(key, list.join(","));
    }
    // The worldwide checkbox is on by default: only "off" goes in the URL.
    if (!grouped.has("ww")) params.set("ww", "0");
    if (!grouped.get("country")?.length) params.delete("ww");
    // All three work types ticked is the same as no work-type filter.
    if (grouped.get("type")?.length === 3) params.delete("type");
    if (params.get("sort") === "recent") params.delete("sort");
    if (params.get("salary") === "0") params.delete("salary");
    const query = params.toString().replaceAll("%2C", ",");
    router.push(`/search${query ? `?${query}` : ""}`, { scroll: false });
  }

  return (
    <form
      ref={form}
      action="/search"
      method="get"
      className={className}
      role="search"
      onChange={(event) => {
        // Typing in a text box waits for Enter; boxes and buttons apply at once.
        const target = event.target;
        if (target instanceof HTMLInputElement && (target.type === "text" || target.type === "search")) return;
        apply();
      }}
      onSubmit={(event) => {
        event.preventDefault();
        apply();
      }}
    >
      {children}
    </form>
  );
}
