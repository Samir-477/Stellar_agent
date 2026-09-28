import type { Metadata } from "next";
import localFont from "next/font/local";
import { JsonLd } from "@/components/json-ld";
import { absoluteUrl, site } from "@/lib/site";
import "./globals.css";

// Space Grotesk for headings, DM Sans for reading and controls, Space Mono only for IDs,
// URLs, timestamps and figures (docs/design/agent-workspace-design-sense.md). Self-hosted
// latin subsets (SIL Open Font License), so builds don't depend on reaching Google Fonts.
const display = localFont({
  src: "./fonts/SpaceGrotesk-Variable.woff2", variable: "--font-space-grotesk", weight: "300 700", display: "swap",
});
const sans = localFont({
  src: "./fonts/DMSans-Variable.woff2", variable: "--font-dm-sans", weight: "100 1000", display: "swap",
});
const mono = localFont({
  src: [
    { path: "./fonts/SpaceMono-Regular.woff2", weight: "400" },
    { path: "./fonts/SpaceMono-Bold.woff2", weight: "700" },
  ],
  variable: "--font-space-mono",
  display: "swap",
});

export const metadata: Metadata = {
  metadataBase: new URL(site.url),
  title: {
    default: site.name,
    template: `%s | ${site.name}`,
  },
  description: site.description,
  alternates: { canonical: "/" },
  openGraph: {
    type: "website",
    siteName: site.name,
    locale: site.locale,
    url: "/",
  },
  robots: { index: true, follow: true },
};

const organizationJsonLd = {
  "@context": "https://schema.org",
  "@type": "Organization",
  "@id": absoluteUrl("/#organization"),
  name: site.name,
  legalName: site.legalName,
  description: site.description,
  url: site.url,
  logo: absoluteUrl(site.logo),
  email: site.email,
  sameAs: site.sameAs,
};

const websiteJsonLd = {
  "@context": "https://schema.org",
  "@type": "WebSite",
  "@id": absoluteUrl("/#website"),
  name: site.name,
  description: site.description,
  url: site.url,
  publisher: { "@id": absoluteUrl("/#organization") },
  inLanguage: "en",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${display.variable} ${sans.variable} ${mono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <JsonLd data={organizationJsonLd} />
        <JsonLd data={websiteJsonLd} />
        {children}
      </body>
    </html>
  );
}
