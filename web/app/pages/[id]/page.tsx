import Link from "next/link";
import { notFound } from "next/navigation";
import { api } from "@/lib/api";
import DeletePageButton from "./delete-button";

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

  const meta = (page.metadata ?? {}) as Record<string, unknown>;
  const block = meta.block as { vendor?: string } | undefined;
  const product = meta.product as
    | { name?: string; brand?: string; price?: string; currency?: string; availability?: string }
    | undefined;

  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/pages"
          className="inline-flex items-center gap-1 text-xs text-neutral-500 hover:text-neutral-900 dark:text-neutral-400 dark:hover:text-neutral-100"
        >
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-3.5 w-3.5">
            <path d="m15 18-6-6 6-6" />
          </svg>
          Back to pages
        </Link>
        <div className="mt-3 flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="break-words text-[22px] font-semibold tracking-tight text-neutral-900 dark:text-neutral-100">
              {page.title ?? page.url}
            </h1>
            <a
              href={page.final_url ?? page.url}
              target="_blank"
              rel="noreferrer"
              className="mt-1 inline-block break-all text-sm text-indigo-600 hover:underline dark:text-indigo-400"
            >
              {page.final_url ?? page.url}
            </a>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {page.id != null && (
              <a
                href={`/api/pages/${page.id}/html`}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1.5 rounded-lg border border-neutral-200 bg-white px-3 py-1.5 text-sm font-medium text-neutral-700 hover:bg-neutral-50 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-300 dark:hover:bg-neutral-800"
              >
                Raw HTML
              </a>
            )}
            {page.id != null && <DeletePageButton id={page.id} />}
          </div>
        </div>
      </div>

      <div className="flex flex-wrap gap-2 text-xs">
        <Pill label="Render" value={page.render_mode} mono />
        {page.status != null && <Pill label="Status" value={String(page.status)} mono />}
        {typeof meta.language === "string" && <Pill label="Lang" value={meta.language} />}
        {typeof meta.author === "string" && <Pill label="Author" value={meta.author} />}
        {typeof meta.schema_type === "string" && <Pill label="Type" value={meta.schema_type} />}
        {block?.vendor && (
          <span className="rounded-md bg-amber-50 px-2.5 py-1 text-amber-700 ring-1 ring-inset ring-amber-100 dark:bg-amber-950 dark:text-amber-300 dark:ring-amber-900">
            bot-protection: {block.vendor}
          </span>
        )}
        {page.fetched_at && <Pill value={new Date(page.fetched_at).toLocaleString()} />}
        {page.error && (
          <span className="rounded-md bg-red-50 px-2.5 py-1 text-red-700 ring-1 ring-inset ring-red-100 dark:bg-red-950 dark:text-red-300 dark:ring-red-900">
            {page.error}
          </span>
        )}
      </div>

      {product && (product.price || product.name) && (
        <div className="rounded-xl border border-neutral-200 bg-white px-5 py-4 text-sm dark:border-neutral-800 dark:bg-neutral-900">
          <div className="mb-1 text-xs font-medium uppercase tracking-wider text-neutral-400">Product</div>
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 text-neutral-800 dark:text-neutral-200">
            {product.name && <span className="font-medium">{product.name}</span>}
            {product.brand && <span className="text-neutral-500 dark:text-neutral-400">{product.brand}</span>}
            {product.price && (
              <span className="font-mono">
                {product.price} {product.currency ?? ""}
              </span>
            )}
            {product.availability && (
              <span className="rounded bg-neutral-100 px-1.5 py-0.5 text-xs dark:bg-neutral-800">
                {product.availability}
              </span>
            )}
          </div>
        </div>
      )}

      {page.text ? (
        <article className="whitespace-pre-wrap rounded-xl border border-neutral-200 bg-white px-5 py-4 text-sm leading-relaxed text-neutral-800 dark:border-neutral-800 dark:bg-neutral-900 dark:text-neutral-200">
          {page.text}
        </article>
      ) : (
        <p className="rounded-xl border border-dashed border-neutral-200 bg-white px-5 py-8 text-center text-sm text-neutral-500 dark:border-neutral-800 dark:bg-neutral-900 dark:text-neutral-400">
          No extracted text.
        </p>
      )}

      {page.links?.length > 0 && (
        <details className="group rounded-xl border border-neutral-200 bg-white px-5 py-3 dark:border-neutral-800 dark:bg-neutral-900">
          <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-medium text-neutral-800 dark:text-neutral-200">
            {page.links.length} link{page.links.length === 1 ? "" : "s"}
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4 text-neutral-400 transition-transform group-open:rotate-180">
              <path d="m6 9 6 6 6-6" />
            </svg>
          </summary>
          <ul className="mt-3 space-y-1 text-xs">
            {page.links.slice(0, 200).map((l) => (
              <li key={l} className="truncate">
                <a href={l} target="_blank" rel="noreferrer" className="text-indigo-600 hover:underline dark:text-indigo-400">
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
      className={`rounded-md bg-neutral-100 px-2.5 py-1 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300 ${
        mono ? "font-mono" : ""
      }`}
    >
      {label && <span className="text-neutral-500 dark:text-neutral-400">{label}: </span>}
      {value}
    </span>
  );
}
