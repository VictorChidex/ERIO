import { describeEvent, type HistoryEvent } from "@/lib/history";
import type { JobRecord } from "@/lib/api";

import styles from "./JobHistory.module.css";

const day = (iso: string): string => iso.slice(0, 10);

/** What changed on a job since ERIO first saw it, newest first. Renders nothing without events. */
export function JobHistory({ events, job }: { events: HistoryEvent[]; job: JobRecord }) {
  if (events.length === 0) return null;
  return (
    <>
      <h2 className={styles.h2}>History</h2>
      <ol className={styles.timeline} aria-label="Changes to this job">
        {events.map((event, index) => (
          <li key={`${event.at}-${event.kind}-${index}`} className={styles[event.kind]}>
            <time dateTime={event.at}>{day(event.at)}</time>
            <span>
              {describeEvent(event, job).map((line) => (
                <span key={line} className={styles.line}>
                  {line}
                </span>
              ))}
            </span>
          </li>
        ))}
      </ol>
    </>
  );
}
