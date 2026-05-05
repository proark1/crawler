import Link from "next/link";
import { notFound } from "next/navigation";
import { api } from "@/lib/api";

type Params = Promise<{ id: string }>;

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
          className="inline-flex items-center gap-1 text-xs text-neutral-500 hover:text-neutral-900"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5">
            <path d="m15 18-6-6 6-6" />
          </svg>
          Back to pages
        </Link>
        <h1 className="mt-3 break-words text-[22px] font-semibold tracking-tight text-neutral-900">
          {page.title ?? page.url}
        </h1>
        <a
          href={page.final_url ?? page.url}
          target="_blank"
          rel="noreferrer"
          className="mt-1 inline-block break-all text-sm text-indigo-600 hover:underline"
        >
          {page.final_url ?? page.url}
        </a>
      </div>

      <div className="flex flex-wrap gap-2 text-xs">
        <Pill label="Render" value={page.render_mode} mono />
        {page.status != null && <Pill label="Status" value={String(page.status)} mono />}
        {page.fetched_at && <Pill value={new Date(page.fetched_at).toLocaleString()} />}
        {page.error && (
          <span className="rounded-md bg-red-50 px-2.5 py-1 text-red-700 ring-1 ring-inset ring-red-100">
            {page.error}
          </span>
        )}
      </div>

      {page.text ? (
        <article className="whitespace-pre-wrap rounded-xl border border-neutral-200 bg-white px-5 py-4 text-sm leading-relaxed text-neutral-800">
          {page.text}
        </article>
      ) : (
        <p className="rounded-xl border border-dashed border-neutral-200 bg-white px-5 py-8 text-center text-sm text-neutral-500">
          No extracted text.
        </p>
      )}

      {page.links?.length > 0 && (
        <details className="group rounded-xl border border-neutral-200 bg-white px-5 py-3">
          <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-medium text-neutral-800">
            {page.links.length} link{page.links.length === 1 ? "" : "s"}
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4 text-neutral-400 transition-transform group-open:rotate-180">
              <path d="m6 9 6 6 6-6" />
            </svg>
          </summary>
          <ul className="mt-3 space-y-1 text-xs">
            {page.links.slice(0, 200).map((l) => (
              <li key={l} className="truncate">
                <a href={l} target="_blank" rel="noreferrer" className="text-indigo-600 hover:underline">
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

function Pill({ label, value, mono }: { label?: string; value: string; mono?: boolean }) {
  return (
    <span
      className={`rounded-md bg-neutral-100 px-2.5 py-1 text-neutral-700 ${
        mono ? "font-mono" : ""
      }`}
    >
      {label && <span className="text-neutral-500">{label}: </span>}
      {value}
    </span>
  );
}
