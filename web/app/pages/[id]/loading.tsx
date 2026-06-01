export default function Loading() {
  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <div className="h-3 w-24 animate-pulse rounded bg-neutral-200 dark:bg-neutral-800" />
        <div className="h-7 w-2/3 animate-pulse rounded bg-neutral-200 dark:bg-neutral-700" />
        <div className="h-4 w-1/2 animate-pulse rounded bg-neutral-100 dark:bg-neutral-800" />
      </div>
      <div className="h-48 w-full animate-pulse rounded-xl border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900" />
    </div>
  );
}
