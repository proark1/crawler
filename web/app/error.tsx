"use client";

function friendlyMessage(error: Error): string {
  const raw = error.message ?? "";
  const m = raw.match(/^API (\d{3}):\s*([\s\S]*)$/);
  if (m) {
    const status = Number(m[1]);
    if (status === 401 || status === 403) {
      return "Not authorized to reach the crawler service. Check the API key.";
    }
    if (status >= 400 && status < 500) {
      return "The request was rejected. Check the inputs and try again.";
    }
    return "The crawler service returned an error. Please try again.";
  }
  if (/fetch failed|ECONNREFUSED|network|Failed to fetch/i.test(raw)) {
    return "Couldn't reach the crawler service. Is it running?";
  }
  return "The crawler backend could not be reached or returned an error.";
}

export default function Error({ error, reset }: { error: Error; reset: () => void }) {
  return (
    <div className="rounded-xl border border-red-200 bg-red-50 px-6 py-8 text-center dark:border-red-900 dark:bg-red-950">
      <h2 className="text-base font-semibold text-red-800 dark:text-red-300">Something went wrong</h2>
      <p className="mt-1 text-sm text-red-600 dark:text-red-400">
        {friendlyMessage(error)}
      </p>
      <button
        type="button"
        onClick={reset}
        className="mt-4 rounded-lg bg-[#0B1739] px-4 py-2 text-sm font-medium text-white hover:opacity-90 dark:bg-indigo-600"
      >
        Try again
      </button>
    </div>
  );
}
