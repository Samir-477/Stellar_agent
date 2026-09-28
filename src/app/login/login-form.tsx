"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import styles from "./login.module.css";

export default function LoginForm({ next }: { next: string }) {
  const router = useRouter();
  const [showPassword, setShowPassword] = useState(false);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setMessage("");
    setBusy(true);
    const fields = new FormData(event.currentTarget);
    try {
      const response = await fetch("/api/demo-auth", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: fields.get("email"), password: fields.get("password") }),
      });
      const result = await response.json();
      if (!response.ok) {
        setMessage(result.error || "Sign-in failed. Try again.");
        setBusy(false);
        return;
      }
      router.replace(next);
      router.refresh();
    } catch {
      setMessage("Could not reach the sign-in service. Try again.");
      setBusy(false);
    }
  }

  return (
    <form className={styles.form} onSubmit={handleSubmit}>
      <div className={styles.field}>
        <label htmlFor="login-email">Work email</label>
        <input
          id="login-email"
          name="email"
          type="email"
          inputMode="email"
          autoComplete="username"
          placeholder="you@company.com"
          required
          onChange={() => setMessage("")}
        />
      </div>

      <div className={styles.field}>
        <label htmlFor="login-password">Password</label>
        <div className={styles.passwordField}>
          <input
            id="login-password"
            name="password"
            type={showPassword ? "text" : "password"}
            autoComplete="current-password"
            placeholder="Enter your password"
            required
            onChange={() => setMessage("")}
          />
          <button
            className={styles.visibilityButton}
            type="button"
            aria-label={showPassword ? "Hide password" : "Show password"}
            aria-pressed={showPassword}
            onClick={() => setShowPassword((current) => !current)}
          >
            {showPassword ? "Hide" : "Show"}
          </button>
        </div>
      </div>

      <button className={styles.submit} type="submit" disabled={busy}>
        <span>{busy ? "Signing in…" : "Sign in"}</span>
        <svg aria-hidden="true" viewBox="0 0 20 20" fill="none">
          <path d="M3.5 10h12m-5-5 5 5-5 5" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {message && <p className={styles.formMessage} role="alert">{message}</p>}

      <div className={styles.formNote}>
        <span className={styles.noteIcon} aria-hidden="true">i</span>
        <p>Demo access only. Your workspace data stays separate from this preview.</p>
      </div>
    </form>
  );
}
