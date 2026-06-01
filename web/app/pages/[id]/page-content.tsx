"use client";

import { useState } from "react";

export default function PageContent({
  text,
  markdown,
}: {
  text: string | null;
  markdown: string | null;
}) {
  const hasMarkdown = !!markdown;
  const [view, setView] = useState<"text" | "markdown">("text");
  const [copied, setCopied] = useState(false);

  const body = view === "markdown" && markdown ? markdown : text;
  if (!body) return <p className="text-sm text-neutral-500">No extracted text.</p>;

  async function copy() {
    try {
      await navigator.clipboard.writeText(body ?? "");
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable */
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs">
        {hasMarkdown && (
          <div className="inline-flex rounded-md border border-neutral-300 dark:border-neutral-700 overflow-hidden">
            {(["text", "markdown"] as const).map((mode) => (
              <button
                key={mode}
                onClick={() => setView(mode)}
                className={`px-2 py-1 ${
                  view === mode
                    ? "bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-900"
                    : "text-neutral-600 dark:text-neutral-400"
                }`}
              >
                {mode}
              </button>
            ))}
          </div>
        )}
        <button
          onClick={copy}
          className="rounded-md border border-neutral-300 dark:border-neutral-700 px-2 py-1 text-neutral-600 dark:text-neutral-400"
        >
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <article className="whitespace-pre-wrap rounded-md border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 px-4 py-3 text-sm leading-relaxed">
        {body}
      </article>
    </div>
  );
}
