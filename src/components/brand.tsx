import Image from "next/image";
import { site } from "@/lib/site";

/** The mark (a pulse beacon on a light tile) with the name on two lines: "Stellar" over "Agents". */
export function Brand({ tone = "light", size = "md" }: { tone?: "light" | "dark"; size?: "md" | "lg" }) {
  const [first, ...rest] = site.name.split(" ");
  const markSize = size === "lg" ? 52 : 44;
  return (
    <span className="inline-flex items-center gap-3" aria-label={site.name}>
      <Image src={site.logo} alt="" width={markSize} height={markSize} priority />
      <span aria-hidden="true" className={`flex flex-col font-display leading-[1.05] tracking-[-0.02em] ${size === "lg" ? "text-2xl" : "text-xl"}`}>
        <span className={`font-bold ${tone === "dark" ? "text-white" : "text-ink"}`}>{first}</span>
        <span className={`font-semibold ${tone === "dark" ? "text-mint" : "text-signal"}`}>{rest.join(" ")}</span>
      </span>
    </span>
  );
}
