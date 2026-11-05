import type { Metadata } from "next";
import localFont from "next/font/local";
import { headers } from "next/headers";
import type { ReactNode } from "react";

import { Footer } from "@/components/Footer";
import { Nav } from "@/components/Nav";
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
  title: { default: "ERIO — real-time job index", template: "%s · ERIO" },
  description:
    "Search open jobs from employers' applicant tracking systems in every country, refreshed every 15 minutes.",
};

// Applies the saved theme before first paint so light-mode users never see a dark flash.
const themeScript = `try{if(localStorage.getItem("${THEME_STORAGE_KEY}")==="light")document.documentElement.dataset.theme="light"}catch(e){}`;

export default async function RootLayout({ children }: { children: ReactNode }) {
  // Set by middleware.ts; lets this inline script run under the Content Security Policy.
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <html
      lang="en"
      className={`${display.variable} ${text.variable} ${mono.variable}`}
      suppressHydrationWarning
    >
      <head>
        <script nonce={nonce} dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body>
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <Nav />
        <main id="main">{children}</main>
        <Footer />
      </body>
    </html>
  );
}
