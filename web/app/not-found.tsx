import Link from "next/link";

export default function NotFound() {
  return (
    <div className="rounded-xl border border-neutral-200 bg-white px-6 py-12 text-center dark:border-neutral-800 dark:bg-neutral-900">
      <h2 className="text-base font-semibold text-neutral-900 dark:text-neutral-100">Not found</h2>
      <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
        That page isn&apos;t in the index.
      </p>
      <Link
        href="/pages"
        className="mt-4 inline-block rounded-lg bg-[#0B1739] px-4 py-2 text-sm font-medium text-white hover:opacity-90 dark:bg-indigo-600"
      >
        Browse pages
      </Link>
    </div>
  );
}
