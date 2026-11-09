import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { LandingPage } from "@/components/LandingPage";
import { landingMetadata, resolveLanding } from "@/lib/seo-data";

type Props = { params: Promise<{ country: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const resolved = await resolveLanding({ country: (await params).country });
  if (!resolved) notFound();
  return landingMetadata(resolved);
}

/** /jobs/in/{country}: open jobs in one country. */
export default async function CountryJobsPage({ params }: Props) {
  const resolved = await resolveLanding({ country: (await params).country });
  if (!resolved) notFound();
  return <LandingPage resolved={resolved} />;
}
