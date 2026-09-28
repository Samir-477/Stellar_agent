import type { MetadataRoute } from "next";
import { absoluteUrl, pages } from "@/lib/site";

export default function sitemap(): MetadataRoute.Sitemap {
  return pages.map((page) => ({
    url: absoluteUrl(page.path),
    lastModified: new Date(page.lastModified),
  }));
}
