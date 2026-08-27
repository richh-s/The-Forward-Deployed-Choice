"use client";

import { FormEvent, useEffect, useState } from "react";

export default function LoginPage() {
  const [csrf, setCsrf] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

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
          <input name="password" type="password" required />
          <button disabled={busy || !csrf}>{busy ? "Signing in…" : "Sign in"}</button>
        </form>
      </div>
    </div>
  );
}
