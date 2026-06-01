import Link from "next/link";

export const metadata = { title: "Settings · Crawler" };

export default function SettingsPage() {
  const apiConfigured = Boolean(process.env.CRAWLER_API_URL);
  const keyConfigured = Boolean(process.env.CRAWLER_API_KEY);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[22px] font-semibold tracking-tight text-neutral-900 dark:text-neutral-100">Settings</h1>
        <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
          Connection details for the crawler backend. These are configured via environment
          variables on the deployment.
        </p>
      </div>

      <div className="space-y-4 rounded-xl border border-neutral-200 bg-white p-6 dark:border-neutral-800 dark:bg-neutral-900">
        <Row
          label="Backend API"
          value={apiConfigured ? "Configured" : "Using default (localhost:8000)"}
          ok={apiConfigured}
          hint="CRAWLER_API_URL"
        />
        <Row
          label="API key"
          value={keyConfigured ? "Set" : "Not set (auth disabled)"}
          ok={keyConfigured}
          hint="CRAWLER_API_KEY"
        />
      </div>

      <div className="rounded-xl border border-neutral-200 bg-white p-6 text-sm text-neutral-600 dark:border-neutral-800 dark:bg-neutral-900 dark:text-neutral-400">
        <h2 className="mb-2 text-sm font-medium text-neutral-900 dark:text-neutral-100">How rendering works</h2>
        <ul className="list-inside list-disc space-y-1">
          <li><span className="font-medium">Auto</span> — fetches static HTML first, falls back to a headless browser only when the page looks empty.</li>
          <li><span className="font-medium">Static</span> — plain HTTP fetch, fastest, no JavaScript.</li>
          <li><span className="font-medium">JS</span> — always renders with Chromium for JavaScript-heavy sites.</li>
        </ul>
        <p className="mt-3">
          Crawls respect <code className="rounded bg-neutral-100 px-1 dark:bg-neutral-800">robots.txt</code> by default,
          block private/internal addresses (SSRF protection), and run as background jobs so large
          crawls don&apos;t time out.
        </p>
      </div>

      <Link
        href="/"
        className="inline-flex items-center gap-1.5 rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-300 dark:hover:bg-neutral-800"
      >
        Back to crawler
      </Link>
    </div>
  );
}

function Row({
  label,
  value,
  ok,
  hint,
}: {
  label: string;
  value: string;
  ok: boolean;
  hint: string;
}) {
  return (
    <div className="flex items-center justify-between gap-4 border-b border-neutral-100 pb-4 last:border-0 last:pb-0 dark:border-neutral-800">
      <div>
        <div className="text-sm font-medium text-neutral-900 dark:text-neutral-100">{label}</div>
        <code className="text-xs text-neutral-400">{hint}</code>
      </div>
      <span
        className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium ${
          ok
            ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300"
            : "bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300"
        }`}
      >
        <span className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-emerald-500" : "bg-neutral-400"}`} />
        {value}
      </span>
    </div>
  );
}
