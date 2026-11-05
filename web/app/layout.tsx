import type { Metadata } from "next";
import localFont from "next/font/local";
import Link from "next/link";
import type { ReactNode } from "react";

import { ThemeToggle } from "@/components/ThemeToggle";
import { THEME_STORAGE_KEY } from "@/lib/theme";

import "./globals.css";

// Fonts come from the versioned @fontsource packages, so builds never depend
// on reaching Google Fonts.
const display = localFont({
  src: [
    { path: "../node_modules/@fontsource/syne/files/syne-latin-700-normal.woff2", weight: "700" },
    { path: "../node_modules/@fontsource/syne/files/syne-latin-800-normal.woff2", weight: "800" },
  ],
  variable: "--font-display",
});
const text = localFont({
  src: [
    { path: "../node_modules/@fontsource/dm-sans/files/dm-sans-latin-300-normal.woff2", weight: "300" },
    { path: "../node_modules/@fontsource/dm-sans/files/dm-sans-latin-400-normal.woff2", weight: "400" },
    { path: "../node_modules/@fontsource/dm-sans/files/dm-sans-latin-500-normal.woff2", weight: "500" },
    { path: "../node_modules/@fontsource/dm-sans/files/dm-sans-latin-600-normal.woff2", weight: "600" },
  ],
  variable: "--font-text",
});
const mono = localFont({
  src: [
    { path: "../node_modules/@fontsource/jetbrains-mono/files/jetbrains-mono-latin-400-normal.woff2", weight: "400" },
    { path: "../node_modules/@fontsource/jetbrains-mono/files/jetbrains-mono-latin-500-normal.woff2", weight: "500" },
  ],
  variable: "--font-mono",
});

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
