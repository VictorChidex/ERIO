import type { Country } from "@/lib/api";

/** Header dropdown for one country (spec section 8); the search sidebar takes several. */
export function CountrySelect({
  name,
  countries,
  value = "",
  id,
}: {
  name: string;
  countries: Country[];
  value?: string;
  id?: string;
}) {
  const sorted = [...countries].sort((a, b) => a.name.localeCompare(b.name));
  return (
    <select className="cselect" name={name} id={id} defaultValue={value} aria-label="Country">
      <option value="">Any country</option>
      {sorted.map((c) => (
        <option key={c.code} value={c.code}>
          {c.name}
          {c.job_count ? ` · ${c.job_count}` : ""}
        </option>
      ))}
    </select>
  );
}
