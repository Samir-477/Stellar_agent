// Renders schema.org structured data as a server-side <script> tag.
// "<" is escaped so strings in the data can't break out of the script (XSS),
// as recommended in node_modules/next/dist/docs/01-app/02-guides/json-ld.md.

export function JsonLd({ data }: { data: Record<string, unknown> }) {
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{
        __html: JSON.stringify(data).replace(/</g, "\\u003c"),
      }}
    />
  );
}
