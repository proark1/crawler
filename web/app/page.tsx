import CrawlForm from "./crawl-form";

export default function Home() {
  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight text-neutral-900 dark:text-neutral-100">New crawl</h1>
          <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
            Paste a URL. Static fetch first; Playwright kicks in if the page needs JS.
          </p>
        </div>
      </div>

      <CrawlForm />
    </div>
  );
}
