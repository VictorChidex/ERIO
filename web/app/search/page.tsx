import type { Metadata } from "next";

import { SearchView } from "@/components/SearchView";
import { parseFilters, type RawParams } from "@/lib/filters";

export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Search jobs",
  description: "Search open jobs from employers' applicant tracking systems, filtered by any country.",
};

export default async function SearchPage({ searchParams }: { searchParams: Promise<RawParams> }) {
  return <SearchView filters={parseFilters(await searchParams)} />;
}
