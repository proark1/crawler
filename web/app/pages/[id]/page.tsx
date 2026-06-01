import Link from "next/link";
import { notFound } from "next/navigation";
import { api } from "@/lib/api";
import Time from "../../components/time";
import PageContent from "./page-content";

type Params = Promise<{ id: string }>;

const LINK_LIMIT = 200;

export default async function PageDetail({ params }: { params: Params }) {
  const { id } = await params;
  const numericId = Number(id);
  if (!Number.isFinite(numericId)) notFound();

  let page;
  try {
    page = await api.get(numericId);
  } catch {
    notFound();
  }

  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/pages"
          className="text-xs text-neutral-500 hover:text-neutral-900 dark:hover:text-neutral-100"
        >
          ← Back to pages
        </Link>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight break-words">
          {page.title ?? page.url}
        </h1>
        <a
          href={page.final_url ?? page.url}
          target="_blank"
          rel="noreferrer"
          className="mt-1 inline-block text-sm text-blue-600 dark:text-blue-400 hover:underline break-all"
        >
          {page.final_url ?? page.url}
        </a>
      </div>

      <div className="flex flex-wrap gap-2 text-xs">
        <span className="rounded bg-neutral-100 dark:bg-neutral-800 px-2 py-1 font-mono">
          render: {page.render_mode}
        </span>
        {page.status != null && (
          <span className="rounded bg-neutral-100 dark:bg-neutral-800 px-2 py-1 font-mono">
            status: {page.status}
          </span>
        )}
        {page.fetched_at && (
          <span className="rounded bg-neutral-100 dark:bg-neutral-800 px-2 py-1">
            <Time iso={page.fetched_at} />
          </span>
        )}
        {page.error && (
          <span className="rounded bg-red-100 dark:bg-red-950/40 text-red-800 dark:text-red-200 px-2 py-1">
            {page.error}
          </span>
        )}
      </div>

      <PageContent text={page.text} markdown={page.markdown} />

      {page.links?.length > 0 && (
        <details className="rounded-md border border-neutral-200 dark:border-neutral-800 px-4 py-3">
          <summary className="cursor-pointer text-sm font-medium">
            {page.links.length} link{page.links.length === 1 ? "" : "s"}
            {page.links.length > LINK_LIMIT ? ` (showing first ${LINK_LIMIT})` : ""}
          </summary>
          <ul className="mt-3 space-y-1 text-xs">
            {page.links.slice(0, LINK_LIMIT).map((l) => (
              <li key={l} className="truncate">
                <a
                  href={l}
                  target="_blank"
                  rel="noreferrer"
                  className="text-blue-600 dark:text-blue-400 hover:underline"
                >
                  {l}
                </a>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}
