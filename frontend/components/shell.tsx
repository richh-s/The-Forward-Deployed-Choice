"use client";

import {
  createContext,
  ReactNode,
  useContext,
  useEffect,
  useState,
} from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { apiGet, apiPost, Me } from "@/lib/api";
import { Banner, Spinner } from "@/components/ui";

const MeContext = createContext<Me | null>(null);

export function useMe(): Me {
  const me = useContext(MeContext);
  if (!me) throw new Error("useMe outside Shell");
  return me;
}

const NAV: { href: string; icon: string; label: string }[] = [
  { href: "/", icon: "◧", label: "Pipeline" },
  { href: "/campaigns/", icon: "◈", label: "Campaigns" },
  { href: "/prospects/", icon: "◉", label: "Prospects" },
  { href: "/approvals/", icon: "✓", label: "Approvals" },
  { href: "/analytics/", icon: "▤", label: "Analytics" },
  { href: "/jobs/", icon: "⛭", label: "Jobs" },
  { href: "/settings/", icon: "⚙", label: "Settings" },
];

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/" || pathname === "";
  return pathname.startsWith(href.replace(/\/$/, ""));
}

export function Shell({ title, children }: { title: string; children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const pathname = usePathname();

  useEffect(() => {
    apiGet<Me>("/api/v1/me").then(setMe).catch(() => {});
  }, []);

  async function logout() {
    if (!me) return;
    await apiPost("/logout", {}, me.csrf_token);
    window.location.href = "/app/login/";
  }

  if (!me) {
    return (
      <div className="content" style={{ paddingTop: 60 }}>
        <Spinner />
      </div>
    );
  }

  return (
    <MeContext.Provider value={me}>
      <div className="app">
        <aside className="sidebar">
          <div className="brand-row">
            <span className="logo">
              <span className="mark">CE</span>
            </span>
            <div className="ws-name">{me.workspace.name}</div>
            <div className="ws-sub">Conversion Engine</div>
          </div>
          {NAV.map((n) => (
            <Link
              key={n.href}
              href={n.href}
              className={`navlink${isActive(pathname, n.href) ? " active" : ""}`}
            >
              <span className="ico">{n.icon}</span> {n.label}
            </Link>
          ))}
          <div className="spacer" />
          <div className="foot">
            <div className="user-email">{me.user.email}</div>
            <button className="secondary sm" style={{ width: "100%" }} onClick={logout}>
              Log out
            </button>
          </div>
        </aside>

        <div className="main">
          <div className="topbar">
            <span className="page-title">{title}</span>
            <span className="spacer" />
            {!me.live_mode && (
              <span className="badge warn dot" title="All outbound is routed to the sink address">
                Sink mode
              </span>
            )}
            {me.workspace.outbound_paused ? (
              <span className="badge bad dot">Outbound paused</span>
            ) : (
              <span className="badge good dot">Sending live</span>
            )}
          </div>
          <div className="content">
            {me.workspace.outbound_paused && (
              <Banner tone="bad">
                Outbound is paused: {me.workspace.pause_reason} — review in{" "}
                <Link href="/settings/">Settings</Link>.
              </Banner>
            )}
            {me.dead_jobs > 0 && (
              <Banner tone="bad">
                {me.dead_jobs} background job{me.dead_jobs !== 1 ? "s have" : " has"}{" "}
                permanently failed — review and retry on the{" "}
                <Link href="/jobs/">Jobs page</Link>.
              </Banner>
            )}
            {children}
          </div>
        </div>
      </div>
    </MeContext.Provider>
  );
}
