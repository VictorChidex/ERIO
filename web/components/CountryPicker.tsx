"use client";

import { useState } from "react";

import type { Country } from "@/lib/api";

/**
 * Searchable list of all 233 countries (spec section 8): selected countries
 * first, then countries with local listings by count, then all the others.
 * Counts are the search's facet counts. Typing only hides rows, so a selected
 * country that is filtered out of view still stays in the search.
 */
export function CountryPicker({
  countries,
  selected,
  counts,
}: {
  countries: Country[];
  selected: string[];
  counts: Record<string, number>;
}) {
  const [term, setTerm] = useState("");
  const needle = term.trim().toLowerCase();
  const visible = (c: Country) =>
    !needle || c.name.toLowerCase().includes(needle) || c.code.toLowerCase() === needle;
  const isSelected = (c: Country) => selected.includes(c.code);
  const count = (c: Country) => counts[c.code] ?? 0;

  const groups = [
    { label: "Selected", items: countries.filter(isSelected) },
    {
      label: "With local listings",
      items: countries
        .filter((c) => !isSelected(c) && count(c) > 0)
        .sort((a, b) => count(b) - count(a) || a.name.localeCompare(b.name)),
    },
    {
      label: "All other countries · remote roles",
      items: countries
        .filter((c) => !isSelected(c) && count(c) === 0)
        .sort((a, b) => a.name.localeCompare(b.name)),
    },
  ];
  const anyVisible = countries.some(visible);

  return (
    <>
      <input
        type="search"
        className="cpick-in"
        placeholder="Find a country…"
        aria-label="Find a country"
        autoComplete="off"
        value={term}
        onChange={(event) => setTerm(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === "Enter") event.preventDefault();
        }}
      />
      <div className="cpick-list fo" role="group" aria-label="Countries">
        {groups.map((group) => (
          <div key={group.label} hidden={!group.items.some(visible)}>
            <div className="cpick-sep">{group.label}</div>
            {group.items.map((c) => (
              <label key={c.code} hidden={!visible(c)}>
                <input type="checkbox" name="country" value={c.code} defaultChecked={isSelected(c)} />{" "}
                <span className="cname">{c.name}</span>{" "}
                <span className={count(c) ? "fc" : "fc zero"}>{count(c)}</span>
              </label>
            ))}
          </div>
        ))}
        {!anyVisible && <p className="cpick-none">No country matches “{term}”.</p>}
      </div>
    </>
  );
}
