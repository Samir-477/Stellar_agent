import type { Metadata } from "next";
import { redirect } from "next/navigation";
import { Brand } from "@/components/brand";
import { currentUser } from "@/lib/session";
import { site } from "@/lib/site";
import LoginForm from "./login-form";
import styles from "./login.module.css";

export const metadata: Metadata = {
  title: { absolute: `Sign in | ${site.name}` },
  description: `Sign in to the ${site.name} workspace.`,
  robots: { index: false, follow: false },
};

/** Only same-site paths, so a crafted link can't send someone elsewhere after sign-in. */
function safeNext(value: string | string[] | undefined): string {
  const next = typeof value === "string" ? value : "";
  return next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/login") ? next : "/home";
}

const stages = [
  { number: "01", title: "Collect", detail: "Capture the site as evidence." },
  { number: "02", title: "Diagnose", detail: "Let specialist agents investigate." },
  { number: "03", title: "Decide", detail: "Review what deserves attention." },
  { number: "04", title: "Preview", detail: "See proposed changes in context." },
];

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const next = safeNext((await searchParams).next);
  if (await currentUser()) redirect(next);
  return (
    <main className={styles.page}>
      <section className={styles.story} aria-labelledby="story-title">
        <div className={styles.storyInner}>
          <Brand size="lg" />

          <div className={styles.storyContent}>
            <p className={styles.eyebrow}>A clearer route from evidence to action</p>
            <h1 id="story-title">Understand what your site is really saying.</h1>
            <p className={styles.storyIntro}>
              One workspace to investigate search visibility, answer coverage, and AI discovery—then review the evidence behind every recommendation.
            </p>

            <div className={styles.route} aria-label="Diagnosis workflow">
              <div className={styles.routeLine} aria-hidden="true" />
              {stages.map((stage) => (
                <div className={styles.routeStage} key={stage.number}>
                  <span className={styles.routeNode} aria-hidden="true" />
                  <span className={styles.routeNumber}>{stage.number}</span>
                  <div>
                    <strong>{stage.title}</strong>
                    <p>{stage.detail}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <p className={styles.storyFoot}>SEO · AEO · GEO, connected by evidence.</p>
        </div>
      </section>

      <section className={styles.formSide} aria-labelledby="login-title">
        <div className={styles.formTop}>
          <span className={styles.workspaceLabel}>Private workspace</span>
          <span className={styles.topRule} aria-hidden="true" />
          <span className={styles.topIndex}>01 / Access</span>
        </div>
        <div className={styles.formWrap}>
          <div className={styles.formHeading}>
            <span className={styles.greenDot} aria-hidden="true" />
            <p>Welcome back</p>
          </div>
          <h2 id="login-title">Sign in to your workspace.</h2>
          <p className={styles.formIntro}>Pick up where your last diagnosis left off.</p>
          <LoginForm next={next} />
        </div>
        <footer className={styles.formFoot}>
          <span>{site.name}</span>
          <span>Evidence first. Decisions second.</span>
        </footer>
      </section>
    </main>
  );
}
