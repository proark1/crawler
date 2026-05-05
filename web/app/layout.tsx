import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Crawler",
  description: "Web crawler dashboard",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="min-h-screen">
          <header className="border-b border-neutral-200 dark:border-neutral-800">
            <div className="mx-auto max-w-5xl px-6 py-4 flex items-center gap-6">
              <Link href="/" className="font-semibold tracking-tight">
                Crawler
              </Link>
              <nav className="flex gap-4 text-sm text-neutral-600 dark:text-neutral-400">
                <Link href="/" className="hover:text-neutral-900 dark:hover:text-neutral-100">
                  New crawl
                </Link>
                <Link
                  href="/pages"
                  className="hover:text-neutral-900 dark:hover:text-neutral-100"
                >
                  Pages
                </Link>
              </nav>
            </div>
          </header>
          <main className="mx-auto max-w-5xl px-6 py-8">{children}</main>
        </div>
      </body>
    </html>
  );
}
