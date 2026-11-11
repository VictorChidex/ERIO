"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { Logo } from "@/components/Logo";
import { ThemeToggle } from "@/components/ThemeToggle";

// What a visitor uses most sits in the bar; the rest is one tap away under "More". On a phone
// everything is in one menu, so the bar never overflows and no link is lost.
const MAIN = [
  { href: "/search", label: "Search" },
  { href: "/salary", label: "Pay" },
  { href: "/paths", label: "Roles" },
  { href: "/companies", label: "Companies" },
  { href: "/workspace", label: "Workspace" },
];
const MORE = [
  { href: "/pulse", label: "Pulse" },
  { href: "/coverage", label: "Coverage" },
  { href: "/api", label: "API" },
];

export function Nav() {
  const path = usePathname() ?? "";
  const [menu, setMenu] = useState<"more" | "mobile" | null>(null);
  const bar = useRef<HTMLDivElement>(null);
  const isActive = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));

  // A page change, Escape, or a click outside closes whatever is open.
  useEffect(() => setMenu(null), [path]);
  useEffect(() => {
    if (!menu) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setMenu(null);
    const onClick = (event: MouseEvent) => {
      if (bar.current && !bar.current.contains(event.target as Node)) setMenu(null);
    };
    document.addEventListener("keydown", onKey);
    document.addEventListener("click", onClick);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("click", onClick);
    };
  }, [menu]);

  const link = (item: { href: string; label: string }) => (
    <Link
      key={item.href}
      href={item.href}
      className={isActive(item.href) ? "active" : undefined}
      aria-current={isActive(item.href) ? "page" : undefined}
    >
      {item.label}
    </Link>
  );

  return (
    <nav id="nav" aria-label="Main" ref={bar}>
      <div className="nav-in">
        <Link href="/" className="nav-logo" aria-label="ERIO home">
          <Logo />
        </Link>
        <div className="nav-links">
          {MAIN.map(link)}
          <div className="nav-more">
            <button
              type="button"
              className={`nav-more-btn${MORE.some((item) => isActive(item.href)) ? " active" : ""}`}
              aria-expanded={menu === "more"}
              aria-haspopup="true"
              onClick={() => setMenu(menu === "more" ? null : "more")}
            >
              More <span aria-hidden="true">▾</span>
            </button>
            {menu === "more" && <div className="nav-pop">{MORE.map(link)}</div>}
          </div>
        </div>
        <div className="nav-r">
          <ThemeToggle />
          <Link href="/api#access" className="btn-acc nav-cta">
            API key
          </Link>
          <button
            type="button"
            className="nav-burger"
            aria-label={menu === "mobile" ? "Close menu" : "Open menu"}
            aria-expanded={menu === "mobile"}
            onClick={() => setMenu(menu === "mobile" ? null : "mobile")}
          >
            <span aria-hidden="true">{menu === "mobile" ? "✕" : "☰"}</span>
          </button>
        </div>
      </div>
      {menu === "mobile" && (
        <div className="nav-sheet">
          {link({ href: "/", label: "Home" })}
          {MAIN.map(link)}
          {MORE.map(link)}
        </div>
      )}
    </nav>
  );
}
