import type { Metadata } from "next";
import { notFound } from "next/navigation";

import { LandingPage } from "@/components/LandingPage";
import { landingMetadata, resolveLanding } from "@/lib/seo-data";

type Props = { params: Promise<{ title: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const resolved = await resolveLanding(await params);
  if (!resolved) notFound();
  return landingMetadata(resolved);
}

/** /jobs/role/{title}: one job title across every country. */
export default async function RoleJobsPage({ params }: Props) {
  const resolved = await resolveLanding(await params);
  if (!resolved) notFound();
  return <LandingPage resolved={resolved} />;
}
