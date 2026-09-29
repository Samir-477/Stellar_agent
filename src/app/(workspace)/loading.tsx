/** Shown the moment a workspace page is opened, while its data loads on the server. */
export default function Loading() {
  return (
    <div role="status" aria-label="Loading" className="mx-auto max-w-[1200px] space-y-6 px-5 pt-12 sm:px-8">
      <div className="h-4 w-40 animate-pulse rounded-[4px] bg-mist" />
      <div className="h-12 w-1/2 animate-pulse rounded-[4px] bg-mist" />
      <div className="h-16 animate-pulse rounded-[8px] bg-mist" />
      <div className="grid gap-3 md:grid-cols-3">
        {[0, 1, 2].map((i) => <div key={i} className="h-40 animate-pulse rounded-[6px] bg-mist" />)}
      </div>
    </div>
  );
}
