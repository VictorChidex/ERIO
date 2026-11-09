// Plain SVG and CSS charts for the pulse and company pages: no chart library.
// Every figure is printed next to its bar, so nothing depends on colour alone.

import Link from "next/link";

import type { Bucket, Flow, PayQuartiles } from "@/lib/api";
import { formatCount } from "@/lib/format";

import styles from "./insights.module.css";

export function Stat({ value, label, href }: { value: string; label: string; href?: string }) {
  const body = (
    <>
      <div className={styles.statNum}>{value}</div>
      <div className={styles.statLbl}>{label}</div>
    </>
  );
  return href ? (
    <Link href={href} className={styles.stat}>
      {body}
    </Link>
  ) : (
    <div className={styles.stat}>{body}</div>
  );
}

export function percent(value: number | null): string {
  return value === null ? "—" : `${value}%`;
}

/** Horizontal bars; a row with an href links to the roles behind its number. */
export function BarList({ rows, href }: { rows: Bucket[]; href?: (row: Bucket) => string | null }) {
  const max = Math.max(1, ...rows.map((r) => r.count));
  if (!rows.length) return <p className={styles.empty}>Nothing to show yet.</p>;
  return (
    <ul className={styles.bars}>
      {rows.map((row) => {
        const target = href?.(row) ?? null;
        return (
          <li className={styles.bar} key={row.key}>
            <span className={styles.barName} title={row.label}>
              {target ? <Link href={target}>{row.label}</Link> : row.label}
            </span>
            <span className={styles.track} aria-hidden="true">
              <span className={styles.fill} style={{ width: `${(row.count / max) * 100}%` }} />
            </span>
            <span className={styles.barNum}>{formatCount(row.count)}</span>
          </li>
        );
      })}
    </ul>
  );
}

const W = 720;
const H = 200;
const MID = 100;

/** Roles added (up) and removed (down) per day. */
export function FlowChart({ flow }: { flow: Flow }) {
  const days = flow.days;
  const peak = Math.max(1, ...days.flatMap((d) => [d.added, d.removed]));
  const step = W / days.length;
  const barW = Math.max(2, step - 3);
  const scale = (MID - 14) / peak;
  const label = `Roles added and removed per day over the last ${days.length} days: ${flow.added} added, ${flow.removed} removed.`;
  const short = (iso: string) => new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
  return (
    <div>
      <div className={styles.legend}>
        <span className={styles.key}>
          <span className={`${styles.swatch} ${styles.added}`} />
          Added: {formatCount(flow.added)}
        </span>
        <span className={styles.key}>
          <span className={`${styles.swatch} ${styles.removed}`} />
          Removed: {formatCount(flow.removed)}
        </span>
      </div>
      <svg className={styles.chart} viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label}>
        <line className={styles.axis} x1="0" x2={W} y1={MID} y2={MID} />
        {days.map((d, i) => {
          const x = i * step + (step - barW) / 2;
          return (
            <g key={d.date}>
              <title>{`${short(d.date)}: ${d.added} added, ${d.removed} removed`}</title>
              {d.added > 0 && <rect x={x} y={MID - d.added * scale} width={barW} height={d.added * scale} rx="1.5" fill="var(--grn)" />}
              {d.removed > 0 && <rect x={x} y={MID + 1} width={barW} height={d.removed * scale} rx="1.5" fill="var(--amb)" />}
            </g>
          );
        })}
        <text className={styles.tick} x="0" y={H - 2}>
          {short(days[0]?.date ?? "")}
        </text>
        <text className={styles.tick} x={W} y={H - 2} textAnchor="end">
          {short(days[days.length - 1]?.date ?? "")}
        </text>
        <text className={styles.tick} x="0" y="10">
          {`up to ${peak}`}
        </text>
      </svg>
      {flow.removals_tracked_since && (
        <p className={styles.small}>
          Removals are counted only since ERIO began following these roles (
          {new Date(flow.removals_tracked_since).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", timeZone: "UTC" })}
          ). A role is added on the date its employer gave, or the day it was first seen.
        </p>
      )}
    </div>
  );
}

const SYMBOL_CODES = new Set(["USD", "EUR", "GBP", "NGN", "INR", "JPY", "CAD", "AUD", "BRL", "ZAR", "KES"]);

function money(amount: number, currency: string): string {
  const options: Intl.NumberFormatOptions = SYMBOL_CODES.has(currency)
    ? { style: "currency", currency, notation: "compact", maximumFractionDigits: 1 }
    : { notation: "compact", maximumFractionDigits: 1 };
  const text = new Intl.NumberFormat("en-US", options).format(amount);
  return SYMBOL_CODES.has(currency) ? text : `${currency} ${text}`;
}

const PERIOD: Record<string, string> = { year: "a year", month: "a month", hour: "an hour" };

/** Lower quartile, median and upper quartile per currency. Never converted. */
export function PayRanges({ rows }: { rows: PayQuartiles[] }) {
  if (!rows.length) return <p className={styles.empty}>No role states pay in a way that can be summarised yet.</p>;
  return (
    <div className={styles.pay}>
      {rows.map((row) => {
        const span = Math.max(1e-9, row.upper - row.lower);
        const mid = row.upper === row.lower ? 50 : ((row.median - row.lower) / span) * 100;
        return (
          <div key={`${row.currency}-${row.period}`}>
            <div className={styles.payHead}>
              <span className={styles.payCur}>
                {row.currency} <span className={styles.payMeta}>{PERIOD[row.period]}</span>
              </span>
              <span className={styles.payMeta}>{formatCount(row.roles)} roles</span>
            </div>
            <div className={styles.range} role="img" aria-label={`${row.currency} ${PERIOD[row.period]}: lower quartile ${money(row.lower, row.currency)}, median ${money(row.median, row.currency)}, upper quartile ${money(row.upper, row.currency)}`}>
              <div className={styles.rangeLine} />
              <div className={styles.rangeBox} style={{ left: 0, right: 0 }} />
              <div className={styles.rangeMid} style={{ left: `${mid}%` }} />
            </div>
            <div className={styles.payNums}>
              <span>{money(row.lower, row.currency)}</span>
              <span>median {money(row.median, row.currency)}</span>
              <span>{money(row.upper, row.currency)}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
