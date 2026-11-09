import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { LandingPage } from "@/components/LandingPage";
import { landingMetadata, resolveLanding } from "@/lib/seo-data";

type Props = { params: Promise<{ country: string; segment: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const resolved = await resolveLanding(await params);
  if (!resolved) notFound();
  return landingMetadata(resolved);
}

/** /jobs/in/{country}/{role category | job title | city}. */
export default async function CountrySegmentJobsPage({ params }: Props) {
  const resolved = await resolveLanding(await params);
  if (!resolved) notFound();
  return <LandingPage resolved={resolved} />;
}
