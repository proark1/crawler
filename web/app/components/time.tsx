"use client";

import { useEffect, useState } from "react";

/**
 * Renders a timestamp in the *viewer's* locale/timezone. Server-rendered output
 * uses the ISO string (deterministic, no hydration mismatch); the effect swaps
 * in the localized form after mount.
 */
export default function Time({ iso }: { iso: string }) {
  const [text, setText] = useState(iso);
  useEffect(() => {
    setText(new Date(iso).toLocaleString());
  }, [iso]);
  return (
    <time dateTime={iso} suppressHydrationWarning>
      {text}
    </time>
  );
}
