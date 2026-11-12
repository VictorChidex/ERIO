"use client";

import { type ReactNode, useId, useState } from "react";

/**
 * The filters as a fold on a narrow screen, always open beside the results on a wide one.
 * The closed look on a phone comes from CSS (not a script that runs after the page loads), so
 * the results never jump when the page becomes interactive.
 */
export function FilterFold({ children, active }: { children: ReactNode; active: number }) {
  const [open, setOpen] = useState(false);
  const body = useId();

  return (
    <div className="sb-fold" data-open={open ? "true" : "false"}>
      <button
        type="button"
        className="sb-sum"
        aria-expanded={open}
        aria-controls={body}
        onClick={() => setOpen(!open)}
      >
        <span>Filters</span>
        {active > 0 && <span className="sb-badge">{active}</span>}
        <span className="sb-chev" aria-hidden="true">
          ▾
        </span>
      </button>
      <div className="sb-body" id={body}>
        {children}
      </div>
    </div>
  );
}
