// Role explorer content: where each role page sits, how it relates to others,
// and a short "how to get started" note per field. Pure data, so the unit
// tests can check it. The figures on the pages come from the API.

import { ROLE_LABELS } from "./format";
import { JOB_TITLES, type JobTitle } from "./seo";

/** The role category each curated title belongs to. */
export const TITLE_CATEGORY: Record<string, string> = {
  nurse: "healthcare",
  driver: "logistics",
  teacher: "education",
  electrician: "trades",
  warehouse: "logistics",
  cashier: "retail",
  accountant: "operations",
  "software-engineer": "engineering",
  "data-analyst": "data",
  "data-scientist": "data",
  "product-manager": "product",
  designer: "design",
  "project-manager": "operations",
  "customer-support": "operations",
  "sales-representative": "sales",
  "marketing-manager": "marketing",
  recruiter: "operations",
  mechanic: "trades",
  chef: "hospitality",
  "security-guard": "security",
  pharmacist: "healthcare",
  receptionist: "operations",
};

/** Fields that people often move between; shown as "related roles". */
const NEIGHBOURS: Record<string, string[]> = {
  engineering: ["data", "product", "design"],
  product: ["engineering", "design", "marketing"],
  design: ["product", "engineering", "marketing"],
  data: ["engineering", "product", "operations"],
  operations: ["sales", "data", "logistics"],
  sales: ["marketing", "operations", "retail"],
  marketing: ["sales", "design", "product"],
  healthcare: ["education", "security", "operations"],
  education: ["healthcare", "operations", "hospitality"],
  hospitality: ["retail", "logistics", "operations"],
  retail: ["hospitality", "sales", "logistics"],
  logistics: ["trades", "retail", "operations"],
  trades: ["logistics", "security", "engineering"],
  security: ["trades", "logistics", "healthcare"],
  other: ["operations", "sales", "retail"],
};

export type PathPage =
  | { kind: "category"; slug: string; label: string; category: string }
  | { kind: "title"; slug: string; label: string; category: string; title: JobTitle };

/** What /paths/{slug} shows: a role category, or one of the curated titles. */
export function resolvePath(slug: string): PathPage | null {
  if (slug in ROLE_LABELS) return { kind: "category", slug, label: ROLE_LABELS[slug] ?? slug, category: slug };
  const title = JOB_TITLES.find((t) => t.slug === slug);
  if (title) return { kind: "title", slug, label: title.label, category: TITLE_CATEGORY[slug] ?? "other", title };
  return null;
}

export type Related = { slug: string; label: string };

/** Other pages to read next: for a category its neighbours and titles; for a title its category and siblings. */
export function relatedPaths(page: PathPage): Related[] {
  if (page.kind === "category") {
    const neighbours = (NEIGHBOURS[page.category] ?? []).map((slug) => ({ slug, label: ROLE_LABELS[slug] ?? slug }));
    const titles = JOB_TITLES.filter((t) => TITLE_CATEGORY[t.slug] === page.category).map((t) => ({ slug: t.slug, label: t.label }));
    return [...titles, ...neighbours];
  }
  const category = { slug: page.category, label: ROLE_LABELS[page.category] ?? page.category };
  const siblings = JOB_TITLES.filter((t) => t.slug !== page.slug && TITLE_CATEGORY[t.slug] === page.category).map((t) => ({
    slug: t.slug,
    label: t.label,
  }));
  return [category, ...siblings];
}

/** Every path page, for the index and the sitemap. */
export const allPathSlugs = (): string[] => [...Object.keys(ROLE_LABELS), ...JOB_TITLES.map((t) => t.slug)];

/** Short, factual starting points. Written for ERIO; nothing here is a promise about any employer. */
export const STARTER_NOTES: Record<string, string> = {
  engineering:
    "Most listings name the languages and tools they use, so read three or four postings in the area you want and note what repeats. A small project you can show, such as a repository or a deployed app, is easier to judge than a list of skills. The remote share above shows how many openings are remote right now; a remote posting usually states which countries it can hire in, so check that line before applying.",
  product:
    "Postings usually ask for experience owning a feature or a metric. If you have not held the title, look at how your current work touches users, priorities and trade-offs, and describe that. Where pay figures are shown above, compare them before you negotiate.",
  design:
    "Employers in this field look at a portfolio first. Pick two or three projects, and for each say the problem, your part and what changed. Titles vary (product, visual, UX research, brand), so search more than one word and read what the daily work is, not only the title.",
  data:
    "Titles overlap heavily: analyst, scientist, engineer and ML roles may share half their requirements. Read the tools named in postings (SQL, Python, a BI tool) and start with the ones that appear in most of them. Where enough roles state pay, the quartiles above give a figure to check an offer against.",
  operations:
    "This group covers office and business functions such as accounting, administration, support, project management and recruiting. Requirements are often practical: a certificate, a tool you have used or a language you speak. Read the posting for the tools and the shift pattern, and use the country and city lists above to see where openings concentrate.",
  sales:
    "Postings often split pay into a base and a variable part, and only the stated figure is counted here, so a range may understate what a role can earn. Ask what the quota and ramp-up period are before accepting. Experience selling to the same kind of customer counts for more than the product you sold.",
  marketing:
    "Look at whether a posting is about content, performance, brand or lifecycle work, because the skills differ. Samples of results you can explain, with numbers where you have them, help. The remote share above shows how many of these openings are remote right now.",
  healthcare:
    "Most clinical roles require a licence or registration in the country where you will work, and recognition of a licence earned elsewhere varies by country and profession; check the regulator before you apply. Postings usually state shifts and the setting (hospital, clinic, home care). Non-clinical roles in the same employers, such as coordinators and technicians, have different requirements.",
  education:
    "Teaching posts commonly require a qualification and sometimes registration with a national or regional body. Check the term dates and contract type, since fixed-term and part-time posts are common. International schools and online tutoring list openings in many countries; the country list above shows where employers are hiring now.",
  hospitality:
    "Hiring in kitchens, hotels and restaurants is often local and seasonal, so the city list matters more than the country. Postings usually state the shift pattern; many also say whether training or a food-safety certificate is needed. Start with the employers listed above and read what they ask for.",
  retail:
    "Store roles are posted by the employer for a specific location, so search by your city. Many are part-time or have flexible hours, and postings often list the hours. A first role usually needs availability and reliability more than experience; say plainly which hours you can work.",
  logistics:
    "Driving roles name the licence class and sometimes the vehicle type and region; check these first, since they decide whether you can apply. Warehouse and delivery postings usually list shifts and physical requirements. Employers that hire many people post the same role in several places, so look at the city list above.",
  trades:
    "Electrical, mechanical, building and production roles typically ask for a trade qualification or documented experience, and some require a local licence. Postings usually say which. Apprenticeships and trainee posts exist at larger employers; search for them by name alongside the trade.",
  security:
    "Guard and security-officer roles commonly require a licence or registration that is issued locally, so check what your country or state asks for before applying. Postings name the site type and shift pattern. Employers often hire in batches, so a role you miss may be posted again soon.",
  other:
    "This group holds roles that fit none of the other fields, and it is a mixed set. Use the search to narrow by title, then read the postings themselves; the figures on this page describe the whole group and may not fit the kind of work you want.",
};
