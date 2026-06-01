import type { Metadata } from "next";
import "./globals.css";
import { CommandPaletteProvider } from "./components/command-palette";
import Sidebar from "./components/sidebar";
import { ThemeProvider, ThemeScript } from "./components/theme";
import { ToastProvider } from "./components/toast";
import Topbar from "./components/topbar";

export const metadata: Metadata = {
  title: "Crawler",
  description: "Web crawler dashboard",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <ThemeScript />
      </head>
      <body>
        <ThemeProvider>
          <ToastProvider>
            <CommandPaletteProvider>
              <div className="flex min-h-screen">
                <Sidebar />
                <div className="flex flex-1 flex-col">
                  <Topbar />
                  <main className="flex-1 px-4 py-6 sm:px-8">
                    <div className="mx-auto max-w-6xl">{children}</div>
                  </main>
                </div>
              </div>
            </CommandPaletteProvider>
          </ToastProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
