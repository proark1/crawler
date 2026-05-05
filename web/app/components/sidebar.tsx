"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

type Item = { href: string; label: string; icon: React.ReactNode };

const stroke = "h-[18px] w-[18px] shrink-0";

const SpiderIcon = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-5 w-5">
    <circle cx="12" cy="12" r="3.5" />
    <path d="M12 8.5V4M8.5 12H4M15.5 12H20M12 15.5V20M9.5 9.5L6.5 6.5M14.5 9.5L17.5 6.5M9.5 14.5L6.5 17.5M14.5 14.5L17.5 17.5" />
  </svg>
);

const items: Item[] = [
  {
    href: "/",
    label: "New crawl",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className={stroke}>
        <path d="M12 5v14M5 12h14" />
      </svg>
    ),
  },
  {
    href: "/pages",
    label: "Pages",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className={stroke}>
        <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
        <path d="M14 3v6h6" />
      </svg>
    ),
  },
  {
    href: "/pages?recent=1",
    label: "Recent",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className={stroke}>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </svg>
    ),
  },
  {
    href: "/pages?search=1",
    label: "Search",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className={stroke}>
        <circle cx="11" cy="11" r="7" />
        <path d="m20 20-3.5-3.5" />
      </svg>
    ),
  },
];

const accountItems: Item[] = [
  {
    href: "/settings",
    label: "Settings",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className={stroke}>
        <circle cx="12" cy="12" r="3" />
        <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1A2 2 0 1 1 4.3 17l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1A2 2 0 1 1 7 4.3l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" />
      </svg>
    ),
  },
];

function NavLink({ item, active }: { item: Item; active: boolean }) {
  return (
    <Link
      href={item.href}
      className={[
        "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
        active
          ? "bg-neutral-100 text-neutral-900 font-medium"
          : "text-neutral-600 hover:bg-neutral-100 hover:text-neutral-900",
      ].join(" ")}
    >
      <span className={active ? "text-neutral-900" : "text-neutral-500"}>{item.icon}</span>
      {item.label}
    </Link>
  );
}

export default function Sidebar() {
  const pathname = usePathname() ?? "/";
  const isActive = (href: string) => {
    const base = href.split("?")[0];
    if (base === "/") return pathname === "/";
    return pathname === base || pathname.startsWith(`${base}/`);
  };

  return (
    <aside className="hidden w-60 shrink-0 border-r border-neutral-200 bg-white md:flex md:flex-col">
      <div className="flex items-center gap-2 px-5 pt-5 pb-6">
        <span className="flex h-7 w-7 items-center justify-center rounded-md bg-neutral-100 text-neutral-700">
          {SpiderIcon}
        </span>
        <span className="text-[15px] font-semibold tracking-tight">crawler.io</span>
      </div>

      <div className="px-3">
        <Link
          href="/"
          className="flex items-center justify-center gap-2 rounded-lg bg-[#0B1739] px-3 py-2.5 text-sm font-medium text-white shadow-sm transition-opacity hover:opacity-90"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
            <path d="M12 5v14M5 12h14" />
          </svg>
          New crawl
        </Link>
      </div>

      <nav className="mt-6 flex flex-1 flex-col px-3">
        <p className="px-3 pb-2 text-[11px] font-medium uppercase tracking-wider text-neutral-400">
          Workspace
        </p>
        <div className="flex flex-col gap-0.5">
          {items.map((it) => (
            <NavLink key={it.href} item={it} active={isActive(it.href)} />
          ))}
        </div>

        <p className="mt-6 px-3 pb-2 text-[11px] font-medium uppercase tracking-wider text-neutral-400">
          Account
        </p>
        <div className="flex flex-col gap-0.5">
          {accountItems.map((it) => (
            <NavLink key={it.href} item={it} active={isActive(it.href)} />
          ))}
        </div>

        <div className="mt-auto px-3 pb-5 pt-6">
          <p className="pb-2 text-[11px] font-medium uppercase tracking-wider text-neutral-400">
            Storage
          </p>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-neutral-100">
            <div className="h-full w-[14%] rounded-full bg-neutral-900" />
          </div>
          <p className="mt-2 text-xs text-neutral-500">Local index · synced</p>
        </div>
      </nav>
    </aside>
  );
}
