import { api, type DomainProfile } from "@/lib/api";

export const dynamic = "force-dynamic";

const ENGINE_STYLES: Record<string, string> = {
  static: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
  impersonate: "bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  browser: "bg-indigo-50 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300",
  solver: "bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300",
};

export default async function DomainsPage() {
  let domains: DomainProfile[] = [];
  let unavailable = false;
  try {
    domains = await api.domains(500);
  } catch {
    unavailable = true;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[22px] font-semibold tracking-tight text-neutral-900 dark:text-neutral-100">
          Domains
        </h1>
        <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
          The fetch strategy the crawler learned per domain — which engine tier works
          and where bot protection was hit.
        </p>
      </div>

      <div className="overflow-hidden rounded-xl border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-neutral-100 text-left text-xs font-medium text-neutral-500 dark:border-neutral-800">
              <th className="px-5 py-3 font-medium">Host</th>
              <th className="px-5 py-3 font-medium">Engine</th>
              <th className="px-5 py-3 font-medium">OK</th>
              <th className="px-5 py-3 font-medium">Blocks</th>
              <th className="px-5 py-3 font-medium">Last block</th>
            </tr>
          </thead>
          <tbody>
            {domains.map((d) => (
              <tr key={d.host} className="border-b border-neutral-100 last:border-0 dark:border-neutral-800">
                <td className="px-5 py-3 font-medium text-neutral-900 dark:text-neutral-100">{d.host}</td>
                <td className="px-5 py-3">
                  <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${ENGINE_STYLES[d.engine] ?? ENGINE_STYLES.static}`}>
                    {d.engine}
                  </span>
                </td>
                <td className="px-5 py-3 text-neutral-600 dark:text-neutral-400">{d.successes}</td>
                <td className="px-5 py-3 text-neutral-600 dark:text-neutral-400">
                  {d.blocks}
                  {d.last_vendor && (
                    <span className="ml-2 text-xs text-red-500">{d.last_vendor}</span>
                  )}
                </td>
                <td suppressHydrationWarning className="px-5 py-3 text-xs text-neutral-500 dark:text-neutral-400">
                  {d.last_block_at ? new Date(d.last_block_at * 1000).toLocaleString() : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {domains.length === 0 && (
          <div className="px-5 py-12 text-center text-sm text-neutral-500 dark:text-neutral-400">
            {unavailable
              ? "Domain profiles are unavailable (backend unreachable)."
              : "No domains crawled yet — profiles appear after the first crawl."}
          </div>
        )}
      </div>
    </div>
  );
}
