"use client";

import { useEffect, useState } from "react";

/**
 * Renders a timestamp without a hydration mismatch. The server (and the first
 * client render) emit the raw ISO string; after mount we swap to a localized,
 * timezone-aware string via `useEffect`. The mismatch is confined to the
 * `<time>` element, so we scope `suppressHydrationWarning` there.
 */
export default function Time({
  iso,
  fallback = "—",
}: {
  iso: string | null | undefined;
  fallback?: string;
}) {
  const [text, setText] = useState<string | null>(null);

  useEffect(() => {
    if (!iso) return;
    const d = new Date(iso);
    if (!Number.isNaN(d.getTime())) setText(d.toLocaleString());
  }, [iso]);

  if (!iso) return <>{fallback}</>;

  return (
    <time dateTime={iso} suppressHydrationWarning>
      {text ?? iso}
    </time>
  );
}
