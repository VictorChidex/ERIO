"use client";

import { useRouter } from "next/navigation";

import type { Country } from "@/lib/api";
import { type Filters, toQuery } from "@/lib/filters";

/** The header dropdown picks one country (spec section 8); the sidebar allows several. */
export function HeaderCountrySelect({ countries, filters }: { countries: Country[]; filters: Filters }) {
  const router = useRouter();
  const value = filters.countries.length === 1 ? filters.countries[0] : filters.countries.length ? "__multi" : "";
  const sorted = [...countries].sort((a, b) => a.name.localeCompare(b.name));
  return (
    <select
      className="cselect"
      aria-label="Country"
      value={value}
      onChange={(event) => {
        const code = event.target.value;
        router.push(`/search${toQuery(filters, { countries: code ? [code] : [] })}`, { scroll: false });
      }}
    >
      <option value="">Any country</option>
      <option value="__multi" hidden>
        Multiple countries
      </option>
      {sorted.map((c) => (
        <option key={c.code} value={c.code}>
          {c.name}
          {c.job_count ? ` · ${c.job_count}` : ""}
        </option>
      ))}
    </select>
  );
}
