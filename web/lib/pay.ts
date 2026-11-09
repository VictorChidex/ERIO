/** The jobs a pay figure rests on: that role and country with pay stated, highest first. */
export function jobsBehind(cell: { role: string | null; country: string | null }): string {
  const params = new URLSearchParams();
  if (cell.role) params.set("role", cell.role);
  if (cell.country) {
    params.set("country", cell.country);
    params.set("ww", "0");
  }
  params.set("salary", "1");
  params.set("sort", "salary");
  return `/search?${params.toString()}`;
}
