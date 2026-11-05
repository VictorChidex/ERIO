import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { SearchView } from "@/components/SearchView";
import { getCountries } from "@/lib/api";
import { parseFilters, type RawParams } from "@/lib/filters";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ code: string }>; searchParams: Promise<RawParams> };

async function country(code: string) {
  const countries = await getCountries();
  const found = countries.data.find((c) => c.code === code.toUpperCase());
  if (!found) notFound();
  return found;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const found = await country((await params).code);
  return {
    title: `Jobs in ${found.name}`,
    description: `Open jobs in ${found.name} and remote roles open to applicants there, from employers' own applicant tracking systems.`,
  };
}

/** Country landing page: the same results as /search?country=XX, server-rendered for search engines. */
export default async function CountryPage({ params, searchParams }: Props) {
  const found = await country((await params).code);
  const filters = parseFilters({ ...(await searchParams), country: found.code });
  return (
    <SearchView
      filters={filters}
      eyebrow={`⌕ Jobs in ${found.name}`}
      title={`Jobs in ${found.name}`}
      intro={`Roles based in ${found.name}, plus remote roles open to applicants there.`}
    />
  );
}
