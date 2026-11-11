"use client";

import { type ReactNode, useEffect, useRef } from "react";

/**
 * The filters as a fold. Open by default (so it works without JavaScript and on a wide screen,
 * where the filters sit beside the results); on a narrow screen it starts closed, so the
 * results are the first thing a visitor sees and "Filters" is one tap away.
 */
export function FilterFold({
  children,
  active,
}: {
  children: ReactNode;
  active: number;
}) {
  const fold = useRef<HTMLDetailsElement>(null);

  useEffect(() => {
    if (fold.current && window.matchMedia("(max-width: 900px)").matches)
      fold.current.open = false;
  }, []);

  return (
    <details className="sb-fold" ref={fold} open>
      <summary className="sb-sum">
        <span>Filters</span>
        {active > 0 && <span className="sb-badge">{active}</span>}
        <span className="sb-chev" aria-hidden="true">
          ▾
        </span>
      </summary>
      {children}
    </details>
  );
}
