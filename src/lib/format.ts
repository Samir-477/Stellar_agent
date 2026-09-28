// Display helpers. Dates are shown in India time, where the team and the captured results are.
const TZ = "Asia/Kolkata";

export function formatDate(iso: string | null | undefined, withTime = true): string {
  if (!iso) return "Not started";
  const date = new Date(iso);
  return new Intl.DateTimeFormat("en-IN", {
    day: "numeric", month: "short", year: "numeric", timeZone: TZ,
    ...(withTime ? { hour: "numeric", minute: "2-digit" } : {}),
  }).format(date);
}

export function formatClock(iso: string): string {
  return new Intl.DateTimeFormat("en-IN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false, timeZone: TZ })
    .format(new Date(iso));
}

export function formatDuration(from: string | null | undefined, to: string | null | undefined): string {
  if (!from) return "Not started";
  const seconds = Math.max(0, Math.round(((to ? new Date(to) : new Date()).getTime() - new Date(from).getTime()) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${String(seconds % 60).padStart(2, "0")}s`;
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}m`;
}

/** The part of a URL a person scans for: host-less path, or the host for a home page. */
export function urlPath(url: string): string {
  try {
    const parsed = new URL(url);
    const path = parsed.pathname + parsed.search;
    return path === "/" ? parsed.host : path;
  } catch {
    return url;
  }
}

export function plural(count: number, one: string, many = `${one}s`): string {
  return `${count} ${count === 1 ? one : many}`;
}

export function agentOfKey(key: string): string {
  return key.split(":")[0];
}
