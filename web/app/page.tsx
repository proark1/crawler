import CrawlForm from "./crawl-form";

export default function Home() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">New crawl</h1>
        <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
          Paste a URL. Static fetch first; Playwright kicks in if the page needs JS.
        </p>
      </div>
      <CrawlForm />
    </div>
  );
}
