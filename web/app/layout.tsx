import type { Metadata } from "next";
import "./globals.css";
import Sidebar from "./components/sidebar";
import Topbar from "./components/topbar";

export const metadata: Metadata = {
  title: "Crawler",
  description: "Web crawler dashboard",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="flex min-h-screen">
          <Sidebar />
          <div className="flex flex-1 flex-col">
            <Topbar />
            <main className="flex-1 px-8 py-6">
              <div className="mx-auto max-w-6xl">{children}</div>
            </main>
          </div>
        </div>
      </body>
    </html>
  );
}
