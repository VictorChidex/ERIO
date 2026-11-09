import Link from "next/link";

import type { JobRecord } from "@/lib/api";
import { companyHref } from "@/lib/seo";
import { ageLabel, freshness, locationLabel, salaryLabel, sourceLabel, TYPE_LABELS } from "@/lib/format";

const TYPE_BADGE: Record<string, string> = { remote: "b-grn", hybrid: "b-amb", onsite: "b-fg" };

export function JobCard({
  job,
  countryNames,
  openToYou = false,
}: {
  job: JobRecord;
  countryNames: Record<string, string>;
  openToYou?: boolean;
}) {
  const salary = salaryLabel(job);
  const verified = job.status === "open";
  const fresh = freshness(job);
  return (
    <article className={`jcard ${job.remote_status}`} role="listitem">
      <div className="jch">
        <div>
          <div className="jco">
            <Link href={companyHref(job.company.name, job.company.slug)} className="jco-link">
              {job.company.name}
            </Link>
          </div>
          <h3 className="jct">
            <Link href={`/jobs/${job.canonical_id}`} className="jct-link">
              {job.title}
            </Link>
          </h3>
        </div>
        <div className="jbadges">
          {fresh.isNew && <span className="b b-grn">New today</span>}
          {openToYou && <span className="b b-acc">Open to you</span>}
          <span className={`b ${TYPE_BADGE[job.remote_status]}`}>{TYPE_LABELS[job.remote_status]}</span>
        </div>
      </div>
      <div className="jcf">
        <span>
          <span aria-hidden="true">📍 </span>
          {locationLabel(job, countryNames)}
        </span>
        {salary && (
          <span>
            <span aria-hidden="true">💰 </span>
            {salary}
          </span>
        )}
        <span className="jcage">
          via {sourceLabel(job.sources)} · {ageLabel(job.posted_at)}
        </span>
      </div>
      <div className="jca">
        <span className="jcstate">
          <span className={verified ? "jcsrc" : "jcsrc jcsrc-unknown"}>
            {verified ? "◉ Verified open" : "◌ Not verified for 72 hours"}
          </span>
          {fresh.checked && <span className="jcchk">{fresh.checked}</span>}
        </span>
        <Link href={`/jobs/${job.canonical_id}`} className="jcbtn" aria-label={`View ${job.title} at ${job.company.name}`}>
          View Job
        </Link>
      </div>
    </article>
  );
}
