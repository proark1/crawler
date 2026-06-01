export default function Loading() {
  return (
    <div className="space-y-6">
      <div className="h-8 w-40 animate-pulse rounded bg-neutral-200 dark:bg-neutral-800" />
      <div className="h-10 w-full animate-pulse rounded-lg bg-neutral-100 dark:bg-neutral-800" />
      <div className="overflow-hidden rounded-xl border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="flex items-center gap-3 border-b border-neutral-100 px-5 py-4 last:border-0 dark:border-neutral-800">
            <div className="h-8 w-8 animate-pulse rounded-md bg-neutral-100 dark:bg-neutral-800" />
            <div className="flex-1 space-y-2">
              <div className="h-3 w-1/3 animate-pulse rounded bg-neutral-200 dark:bg-neutral-700" />
              <div className="h-2.5 w-1/2 animate-pulse rounded bg-neutral-100 dark:bg-neutral-800" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
