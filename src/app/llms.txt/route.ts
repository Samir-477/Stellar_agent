import { absoluteUrl, pages, site } from "@/lib/site";

// Serves /llms.txt (https://llmstxt.org) from the same page list as the sitemap.
export const dynamic = "force-static";

export function GET() {
  const links = pages
    .map((page) => `- [${page.title}](${absoluteUrl(page.path)}): ${page.description}`)
    .join("\n");

  const body = `# ${site.name}

> ${site.description}

## Pages

${links}
`;

  return new Response(body, {
    headers: { "Content-Type": "text/plain; charset=utf-8" },
  });
}
