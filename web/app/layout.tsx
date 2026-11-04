import type { Metadata } from "next";
import { DM_Sans, JetBrains_Mono, Syne } from "next/font/google";
import Link from "next/link";
import type { ReactNode } from "react";

import { ThemeToggle } from "@/components/ThemeToggle";
import { THEME_STORAGE_KEY } from "@/lib/theme";

import "./globals.css";

const display = Syne({ subsets: ["latin"], weight: ["700", "800"], variable: "--font-display" });
const text = DM_Sans({ subsets: ["latin"], variable: "--font-text" });
const mono = JetBrains_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-mono" });

export const metadata: Metadata = {
  title: "ERIO — real-time job index",
  description: "Search open jobs from applicant tracking systems in every country.",
};

// Applies the saved theme before first paint so light-mode users never see a dark flash.
const themeScript = `try{if(localStorage.getItem("${THEME_STORAGE_KEY}")==="light")document.documentElement.dataset.theme="light"}catch(e){}`;

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html
      lang="en"
      className={`${display.variable} ${text.variable} ${mono.variable}`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body>
        <nav className="nav" aria-label="Main">
          <div className="nav-in">
            <Link href="/" className="logo">
              ERIO<span>.</span>
            </Link>
            <div className="nav-r">
              <ThemeToggle />
            </div>
          </div>
        </nav>
        <main>{children}</main>
      </body>
    </html>
  );
}
