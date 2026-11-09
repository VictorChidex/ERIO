import Link from "next/link";

import { popularSearches, type PopularLink } from "@/lib/seo-data";

function Group({ title, links }: { title: string; links: PopularLink[] }) {
  if (!links.length) return null;
  return (
    <div>
      <h3 className="sect-eye">{title}</h3>
      <div className="qf-row">
        {links.map((link) => (
          <Link key={link.href} href={link.href} className="qf">
            {link.label}
          </Link>
        ))}
      </div>
    </div>
  );
}

/** Links from the home page into the landing pages that have enough jobs to be worth a visit. */
export async function PopularSearches() {
  const popular = await popularSearches().catch(() => null);
  if (!popular || !(popular.countries.length || popular.titles.length || popular.roles.length)) return null;
  return (
    <section id="popular">
      <div className="wrap">
        <div className="sect-eye">◉ Popular searches</div>
        <h2 className="sect-h">Where the open roles are.</h2>
        <Group title="By country" links={popular.countries} />
        <Group title="By job title" links={popular.titles} />
        <Group title="Top roles in the biggest markets" links={popular.roles} />
      </div>
    </section>
  );
}
