"use client";

import { ReactNode } from "react";
import { Pager as PagerData } from "@/lib/api";

export function Badge({
  tone = "muted",
  children,
}: {
  tone?: "good" | "warn" | "bad" | "red" | "muted";
  children: ReactNode;
}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}

export function scoreTone(score: number | null | undefined): "good" | "warn" | "bad" | "muted" {
  if (score === null || score === undefined) return "muted";
  return score >= 0.8 ? "good" : score >= 0.6 ? "warn" : "bad";
}

export function Stat({
  label,
  value,
  accent = false,
  foot,
}: {
  label: string;
  value: ReactNode;
  accent?: boolean;
  foot?: ReactNode;
}) {
  return (
    <div className="stat">
      <div className="label">{label}</div>
      <div className={`value${accent ? " accent" : ""}`}>{value}</div>
      {foot ? <div className="foot">{foot}</div> : null}
    </div>
  );
}

export function Banner({
  tone,
  children,
}: {
  tone: "ok" | "warn" | "bad";
  children: ReactNode;
}) {
  return <div className={`banner ${tone}`}>{children}</div>;
}

/** Post-write feedback banner driven by a WriteResult-shaped state. */
export function Flash({ msg, err }: { msg: string; err: boolean }) {
  if (!msg) return null;
  return <Banner tone={err ? "bad" : "ok"}>{msg}</Banner>;
}

export function Pager({
  pager,
  onPage,
}: {
  pager: PagerData | null;
  onPage: (page: number) => void;
}) {
  if (!pager || pager.pages <= 1) return null;
  return (
    <div className="row" style={{ justifyContent: "space-between", marginTop: 12 }}>
      <span className="muted">
        Page {pager.page} of {pager.pages} · {pager.total} total
      </span>
      <span className="row" style={{ gap: 8 }}>
        {pager.page > 1 && (
          <button className="secondary sm" onClick={() => onPage(pager.page - 1)}>
            ← Newer
          </button>
        )}
        {pager.page < pager.pages && (
          <button className="secondary sm" onClick={() => onPage(pager.page + 1)}>
            Older →
          </button>
        )}
      </span>
    </div>
  );
}

export function Empty({
  icon,
  title,
  children,
}: {
  icon: string;
  title: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="icon">{icon}</div>
      <h3>{title}</h3>
      {children ? <p>{children}</p> : null}
    </div>
  );
}

export function Spinner() {
  return <p className="muted">Loading…</p>;
}
