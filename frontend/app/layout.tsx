import type { Metadata } from "next";
import { Fraunces, Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { ThemeScript } from "@/components/theme/theme-script";
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
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} ${fraunces.variable} h-full antialiased`}
    >
      <head>
        <ThemeScript />
      </head>
      <body className="min-h-full">
        <a
          href="#main-content"
          className="sr-only rounded-md bg-accent px-3 py-2 text-sm font-medium text-on-accent focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-[60]"
        >
          Skip to content
        </a>
        <AuthProvider>
          <AppShell>{children}</AppShell>
        </AuthProvider>
      </body>
    </html>
  );
}
