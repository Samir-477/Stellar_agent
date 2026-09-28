import Image from "next/image";
import { site } from "@/lib/site";

/** Three evidence paths converge into one finding, then move toward action. */
export function Brand({ tone = "light", size = "md" }: { tone?: "light" | "dark"; size?: "md" | "lg" }) {
  const [first, ...rest] = site.name.split(" ");
  const markSize = size === "lg" ? 52 : 44;
  return (
    <span className="inline-flex items-center gap-3" aria-label={site.name}>
      <Image src={site.logo} alt="" width={markSize} height={markSize} priority className={tone === "dark" ? "rounded-[10px] ring-1 ring-white/20" : ""} />
      <span aria-hidden="true" className={`flex flex-col font-display leading-[1.02] font-bold tracking-[0.035em] uppercase ${size === "lg" ? "text-lg" : "text-base"}`}>
        <span className={tone === "dark" ? "text-white" : "text-ink"}>{first}</span>
        <span className={tone === "dark" ? "text-mint" : "text-signal"}>{rest.join(" ")}</span>
      </span>
    </span>
  );
}
