"use client";

import { FormEvent, useEffect, useState } from "react";

export default function LoginPage() {
  const [csrf, setCsrf] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [showPw, setShowPw] = useState(false);

  useEffect(() => {
    fetch("/api/v1/prelogin", { credentials: "same-origin" })
      .then((r) => r.json())
      .then((d) => setCsrf(d.csrf_token))
      .catch(() => setError("Could not reach the server"));
  }, []);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    setError("");
    const fd = new FormData(e.currentTarget);
    fd.set("csrf_token", csrf);
    const r = await fetch("/login", {
      method: "POST",
      body: fd,
      credentials: "same-origin",
      redirect: "follow",
    });
    try {
      const u = new URL(r.url);
      const err = u.searchParams.get("error");
      if (err || u.pathname.startsWith("/login")) {
        setError(err || "Invalid credentials");
        // A fresh pre-login token: the old cookie was consumed.
        const d = await fetch("/api/v1/prelogin", {
          credentials: "same-origin",
        }).then((x) => x.json());
        setCsrf(d.csrf_token);
        setBusy(false);
        return;
      }
    } catch {
      /* fall through to success */
    }
    window.location.href = "/app/";
  }

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <span className="logo">
          <span className="mark">CE</span> Conversion Engine
        </span>
        <h2>Sign in</h2>
        <p className="muted" style={{ margin: "0 0 8px" }}>
          Operator dashboard
        </p>
        {error && <div className="banner bad">{error}</div>}
        <form onSubmit={submit}>
          <label>Email</label>
          <input name="email" type="email" required autoFocus />
          <label>Password</label>
          <div style={{ position: "relative" }}>
            <input
              name="password"
              type={showPw ? "text" : "password"}
              required
              style={{ paddingRight: 42 }}
            />
            <button
              type="button"
              onClick={() => setShowPw((v) => !v)}
              aria-label={showPw ? "Hide password" : "Show password"}
              title={showPw ? "Hide password" : "Show password"}
              style={{
                position: "absolute",
                right: 6,
                top: "50%",
                transform: "translateY(-50%)",
                background: "transparent",
                border: "none",
                color: "var(--muted)",
                padding: 6,
                margin: 0,
                width: "auto",
                cursor: "pointer",
              }}
            >
              {showPw ? (
                // eye-off
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
                  <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
                  <path d="M14.12 14.12a3 3 0 1 1-4.24-4.24" />
                  <line x1="1" y1="1" x2="23" y2="23" />
                </svg>
              ) : (
                // eye
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                  <circle cx="12" cy="12" r="3" />
                </svg>
              )}
            </button>
          </div>
          <button disabled={busy || !csrf}>{busy ? "Signing in…" : "Sign in"}</button>
        </form>
      </div>
    </div>
  );
}
