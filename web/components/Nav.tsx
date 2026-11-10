"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { Logo } from "@/components/Logo";
import { ThemeToggle } from "@/components/ThemeToggle";

const LINKS = [
  { href: "/", label: "Home" },
  { href: "/search", label: "Search" },
  { href: "/pulse", label: "Pulse" },
  { href: "/salary", label: "Pay" },
  { href: "/paths", label: "Roles" },
  { href: "/companies", label: "Companies" },
  { href: "/workspace", label: "Workspace" },
  { href: "/coverage", label: "Coverage" },
  { href: "/api", label: "API" },
];

export function Nav() {
  const path = usePathname() ?? "";
  const isActive = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));

  return (
    <nav id="nav" aria-label="Main">
      <div className="nav-in">
        <Link href="/" className="nav-logo" aria-label="ERIO home">
          <Logo />
        </Link>
        <div className="nav-links">
          {LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={isActive(link.href) ? "active" : undefined}
              aria-current={isActive(link.href) ? "page" : undefined}
            >
              {link.label}
            </Link>
          ))}
        </div>
        <div className="nav-r">
          <ThemeToggle />
          <Link href="/api#access" className="btn-acc nav-cta">
            Get API Key
          </Link>
        </div>
      </div>
    </nav>
  );
}
