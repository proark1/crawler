"use client";

export default function Error({ reset }: { error: Error; reset: () => void }) {
  return (
    <div className="rounded-xl border border-red-200 bg-red-50 px-6 py-8 text-center">
      <h2 className="text-base font-semibold text-red-800">Something went wrong</h2>
      <p className="mt-1 text-sm text-red-600">
        The crawler backend could not be reached or returned an error.
      </p>
      <button
        type="button"
        onClick={reset}
        className="mt-4 rounded-lg bg-[#0B1739] px-4 py-2 text-sm font-medium text-white hover:opacity-90"
      >
        Try again
      </button>
    </div>
  );
}
