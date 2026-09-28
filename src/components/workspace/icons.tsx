import {
  BadgeCheck, BookOpen, Bot, Braces, FileText, Gauge, Globe, Heading, Layers, Link2, ListChecks, MapPin, Megaphone,
  MessageCircleQuestionMark, Network, Quote, Route, ScanSearch, Search, ShieldCheck, Sparkles, Tags, Trophy, Waypoints,
  type LucideIcon,
} from "lucide-react";

// One icon per agent, chosen for what it inspects; used beside its name, never alone.
export const AGENT_ICONS: Record<string, LucideIcon> = {
  S1: ScanSearch, S2: Gauge, S3: Tags, S4: FileText, S5: Layers, S6: Trophy, S7: Link2, S8: Braces, S9: MapPin,
  S10: ShieldCheck, A1: MessageCircleQuestionMark, A2: Heading, A3: Route, A4: ListChecks, G1: Bot, G2: Quote,
  G3: Megaphone, G4: BookOpen, G5: BadgeCheck, G6: Waypoints,
};

export const SOURCE_ICONS: Record<string, LucideIcon> = { site: Globe, search: Search, ai: Sparkles, web: Network };

export function AgentIcon({ id, size = 18 }: { id: string; size?: number }) {
  const Icon = AGENT_ICONS[id] ?? FileText;
  return <Icon aria-hidden="true" size={size} strokeWidth={1.8} />;
}
