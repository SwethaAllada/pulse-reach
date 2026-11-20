import type { Metadata } from "next";
import { Fraunces, Geist, Geist_Mono, IBM_Plex_Sans_Arabic } from "next/font/google";
import "./globals.css";
import { ThemeScript } from "@/components/theme/theme-script";
import { LocaleScript } from "@/components/i18n/locale-script";
import { LocaleSync } from "@/components/i18n/language-switcher";
import { SkipLink } from "@/components/shell/skip-link";
import { DocumentTitle } from "@/components/shell/document-title";
import { AppShell } from "@/components/shell/app-shell";
import { AuthProvider } from "@/lib/auth/auth-context";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

/** Arabic UI face (with Latin) — applied under `:lang(ar)` in globals.css; not preloaded for English. */
const plexArabic = IBM_Plex_Sans_Arabic({
  variable: "--font-plex-arabic",
  subsets: ["arabic"],
  weight: ["400", "500", "600", "700"],
  preload: false,
});

/** Editorial display serif — headings and figures. Variable optical size keeps large numbers crisp. */
const fraunces = Fraunces({
  variable: "--font-fraunces",
  subsets: ["latin"],
  axes: ["SOFT", "WONK", "opsz"],
});

export const metadata: Metadata = {
  title: {
    default: "PulseReach — Prevention Atlas",
    template: "%s · PulseReach",
  },
  description:
    "A living view of population health. PulseReach maps preventive-care programmes, documented care gaps and their evidence over a fully synthetic demonstration cohort.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      dir="ltr"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} ${fraunces.variable} ${plexArabic.variable} h-full antialiased`}
    >
      <head>
        <ThemeScript />
        <LocaleScript />
      </head>
      <body className="min-h-full">
        <SkipLink />
        <AuthProvider>
          <LocaleSync />
          <DocumentTitle />
          <AppShell>{children}</AppShell>
        </AuthProvider>
      </body>
    </html>
  );
}
