"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";

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
    href: "/jobs",
    label: "Jobs",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className={stroke}>
        <path d="M4 7h16M4 12h16M4 17h10" />
      </svg>
    ),
  },
  {
    href: "/domains",
    label: "Domains",
    icon: (
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className={stroke}>
        <circle cx="12" cy="12" r="9" />
        <path d="M3 12h18M12 3a15 15 0 0 1 0 18M12 3a15 15 0 0 0 0 18" />
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

function NavLink({
  item,
  active,
  onNavigate,
}: {
  item: Item;
  active: boolean;
  onNavigate?: () => void;
}) {
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      className={[
        "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
        active
          ? "bg-neutral-100 font-medium text-neutral-900 dark:bg-neutral-800 dark:text-neutral-100"
          : "text-neutral-600 hover:bg-neutral-100 hover:text-neutral-900 dark:text-neutral-400 dark:hover:bg-neutral-800 dark:hover:text-neutral-100",
      ].join(" ")}
    >
      <span className={active ? "text-neutral-900 dark:text-neutral-100" : "text-neutral-500 dark:text-neutral-400"}>
        {item.icon}
      </span>
      {item.label}
    </Link>
  );
}

function IndexStatus() {
  const [stats, setStats] = useState<{ total: number; errors: number; blocked: number } | null>(null);
  const [ok, setOk] = useState(true);

  useEffect(() => {
    let alive = true;
    fetch("/api/stats")
      .then((r) => r.json())
      .then((d) => {
        if (!alive) return;
        if (d.total == null) setOk(false);
        else setStats(d);
      })
      .catch(() => alive && setOk(false));
    return () => {
      alive = false;
    };
  }, []);

  return (
    <div className="mt-auto px-3 pb-5 pt-6">
      <p className="pb-2 text-[11px] font-medium uppercase tracking-wider text-neutral-400">
        Index
      </p>
      <div className="flex items-center gap-2 text-xs text-neutral-600 dark:text-neutral-400">
        <span className={`h-2 w-2 rounded-full ${ok ? "bg-emerald-500" : "bg-neutral-300"}`} aria-hidden />
        {ok ? (
          <span>
            {stats ? stats.total.toLocaleString() : "—"} page{stats?.total === 1 ? "" : "s"} stored
          </span>
        ) : (
          <span>Service unreachable</span>
        )}
      </div>
      {ok && stats && (stats.blocked > 0 || stats.errors > 0) && (
        <div className="mt-1 flex gap-3 text-[11px] text-neutral-500 dark:text-neutral-500">
          {stats.errors > 0 && <span>{stats.errors.toLocaleString()} errored</span>}
          {stats.blocked > 0 && <span>{stats.blocked.toLocaleString()} blocked</span>}
        </div>
      )}
    </div>
  );
}

export function NavContent({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname() ?? "/";
  const isActive = (href: string) => {
    if (href === "/") return pathname === "/";
    return pathname === href || pathname.startsWith(`${href}/`);
  };

  return (
    <>
      <div className="flex items-center gap-2 px-5 pb-6 pt-5">
        <span className="flex h-7 w-7 items-center justify-center rounded-md bg-neutral-100 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-200">
          {SpiderIcon}
        </span>
        <span className="text-[15px] font-semibold tracking-tight">Crawler</span>
      </div>

      <div className="px-3">
        <Link
          href="/"
          onClick={onNavigate}
          className="flex items-center justify-center gap-2 rounded-lg bg-[#0B1739] px-3 py-2.5 text-sm font-medium text-white shadow-sm transition-opacity hover:opacity-90 dark:bg-indigo-600"
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
            <NavLink key={it.href} item={it} active={isActive(it.href)} onNavigate={onNavigate} />
          ))}
        </div>

        <p className="mt-6 px-3 pb-2 text-[11px] font-medium uppercase tracking-wider text-neutral-400">
          Account
        </p>
        <div className="flex flex-col gap-0.5">
          {accountItems.map((it) => (
            <NavLink key={it.href} item={it} active={isActive(it.href)} onNavigate={onNavigate} />
          ))}
        </div>

        <IndexStatus />
      </nav>
    </>
  );
}

export default function Sidebar() {
  return (
    <aside className="hidden w-60 shrink-0 border-r border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900 md:flex md:flex-col">
      <NavContent />
    </aside>
  );
}
