import Link from "next/link";
import { api, type JobSummary } from "@/lib/api";
import Time from "../components/time";

export const dynamic = "force-dynamic";

const STATUS_STYLES: Record<string, string> = {
  done: "bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300",
  error: "bg-red-50 text-red-700 dark:bg-red-950 dark:text-red-300",
  running: "bg-amber-50 text-amber-700 dark:bg-amber-950 dark:text-amber-300",
  pending: "bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300",
  cancelled: "bg-neutral-100 text-neutral-500 dark:bg-neutral-800 dark:text-neutral-400",
};

export default async function JobsPage() {
  let jobs: JobSummary[] = [];
  let unavailable = false;
  try {
    jobs = await api.listJobs(100);
  } catch {
    unavailable = true;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-[22px] font-semibold tracking-tight text-neutral-900 dark:text-neutral-100">
          Jobs
        </h1>
        <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
          Background crawl jobs, most recent first.
        </p>
      </div>

      <div className="overflow-hidden rounded-xl border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-neutral-100 text-left text-xs font-medium text-neutral-500 dark:border-neutral-800">
              <th className="px-5 py-3 font-medium">Job</th>
              <th className="px-5 py-3 font-medium">Status</th>
              <th className="px-5 py-3 font-medium">Progress</th>
              <th className="hidden px-5 py-3 font-medium md:table-cell">Updated</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((j) => (
              <tr key={j.id} className="border-b border-neutral-100 last:border-0 dark:border-neutral-800">
                <td className="px-5 py-3 font-mono text-xs text-neutral-700 dark:text-neutral-300">
                  {j.id.slice(0, 12)}
                </td>
                <td className="px-5 py-3">
                  <span className={`rounded-md px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[j.status] ?? STATUS_STYLES.pending}`}>
                    {j.status}
                  </span>
                  {j.error && <span className="ml-2 text-xs text-red-500">{j.error}</span>}
                </td>
                <td className="px-5 py-3 text-neutral-600 dark:text-neutral-400">
                  {j.progress}
                  {j.total ? ` / ${j.total}` : ""}
                </td>
                <td className="hidden px-5 py-3 text-xs text-neutral-500 md:table-cell dark:text-neutral-400">
                  <Time iso={j.updated_at} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {jobs.length === 0 && (
          <div className="flex flex-col items-center gap-4 px-5 py-12 text-center text-sm text-neutral-500 dark:text-neutral-400">
            <span>
              {unavailable
                ? "Jobs are unavailable (backend unreachable)."
                : "No background jobs yet."}
            </span>
            {!unavailable && (
              <Link
                href="/"
                className="inline-flex items-center gap-1.5 rounded-lg bg-[#0B1739] px-4 py-2 text-sm font-medium text-white shadow-sm hover:opacity-90 dark:bg-indigo-600"
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
                  <path d="M12 5v14M5 12h14" />
                </svg>
                New crawl
              </Link>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
