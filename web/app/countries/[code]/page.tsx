import { notFound, permanentRedirect } from "next/navigation";

import { getCountries } from "@/lib/api";
import { countrySlugs } from "@/lib/seo";

export const dynamic = "force-dynamic";

type Props = { params: Promise<{ code: string }> };

/**
 * /countries/NG was the first country page; /jobs/in/nigeria replaced it.
 * Old links keep working through a permanent redirect (308).
 */
export default async function CountryRedirect({ params }: Props) {
  const code = (await params).code.toUpperCase();
  const countries = (await getCountries()).data;
  const slug = countrySlugs(countries).get(code);
  if (!slug) notFound();
  permanentRedirect(`/jobs/in/${slug}`);
}
