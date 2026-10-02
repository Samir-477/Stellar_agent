import { urlPath } from "@/lib/format";
import type { MicrositeIssue } from "@/lib/types";

// The hand-off pack: what is still to do on the diagnosed page, grouped by who does it, with the steps, the
// pages, how to confirm it worked and any prepared code. Built in the browser from the preview's issue list.

const OWNER_ORDER = ["Developer", "Content writer", "Marketing team", "Business owner", "Compliance team"];
const EFFORT: Record<string, string> = { S: "small job", M: "medium job", L: "large job" };

export type HandoffGroup = { owner: string; issues: MicrositeIssue[] };

export function ownerOf(issue: MicrositeIssue): string {
  return issue.plain?.owner || "Your team";
}

/** Still-to-do issues by owner, in a fixed order (developer first), unknown owners last. */
export function handoffGroups(issues: MicrositeIssue[]): HandoffGroup[] {
  const todo = issues.filter((i) => !i.fixed);
  const owners = [...new Set(todo.map(ownerOf))].sort((a, b) => {
    const ia = OWNER_ORDER.indexOf(a), ib = OWNER_ORDER.indexOf(b);
    return (ia < 0 ? 99 : ia) - (ib < 0 ? 99 : ib) || a.localeCompare(b);
  });
  return owners.map((owner) => ({ owner, issues: todo.filter((i) => ownerOf(i) === owner) }));
}

function fence(code: string, language: string): string {
  return "```" + language + "\n" + code.trim() + "\n```";
}

/** The hand-off as Markdown, ready to paste into a ticket, email or document. */
export function handoffMarkdown(issues: MicrositeIssue[], { client, pageUrl, date }: { client: string; pageUrl: string; date: string }): string {
  const groups = handoffGroups(issues);
  const total = groups.reduce((n, g) => n + g.issues.length, 0);
  const lines = [
    `# Hand-off: ${client}`,
    "",
    `Page reviewed: ${pageUrl}  `,
    `Prepared: ${date}. ${total} item${total === 1 ? "" : "s"} still to do, grouped by who does them.`,
    "",
    ...groups.map((g) => `- ${g.owner}: ${g.issues.length}`),
  ];
  let n = 0;
  for (const group of groups) {
    lines.push("", `## ${group.owner} (${group.issues.length})`);
    for (const issue of group.issues) {
      n += 1;
      const plain = issue.plain;
      lines.push("", `### ${n}. ${plain?.problem ?? issue.title}`);
      const meta = [issue.effort && EFFORT[issue.effort], issue.awaiting_approval?.length ? "change prepared, awaiting approval" : ""]
        .filter(Boolean).join("; ");
      if (meta) lines.push(`_${meta.charAt(0).toUpperCase() + meta.slice(1)}_`);
      if (plain?.why || issue.impact) lines.push("", `Why it matters: ${plain?.why || issue.impact}`);
      if (plain?.site_case) lines.push("", `On the site: ${plain.site_case}`);
      lines.push("", `What to do: ${plain?.action || issue.fix}`);
      if (plain?.steps?.length) lines.push("", ...plain.steps.map((step, i) => `${i + 1}. ${step}`));
      if (issue.verification) lines.push("", `Done when: ${issue.verification}`);
      lines.push("", `Technical: ${issue.title}. ${issue.fix}`);
      for (const change of issue.changes) {
        if (change.before) lines.push("", "Now:", fence(change.before, change.language));
        lines.push("", "Change to:", fence(change.after ?? "", change.language));
      }
    }
  }
  return lines.join("\n") + "\n";
}

export function handoffFileName(client: string, pageUrl: string): string {
  const slug = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  return `handoff-${slug(client) || "client"}-${slug(urlPath(pageUrl)) || "page"}.md`;
}
