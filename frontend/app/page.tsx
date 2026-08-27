"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Shell } from "@/components/shell";
import { Badge, Spinner, Stat } from "@/components/ui";
import { apiGet, fmtDate } from "@/lib/api";

interface Summary {
  stages: string[];
  stage_counts: Record<string, number>;
  pending_drafts: number;
  metrics: {
    emails_out: number;
    sms_out: number;
    bounce_rate: number;
    opt_out_rate: number;
    qualified_leads: number;
    llm_cost_usd: number;
    cost_per_qualified_lead: number;
    window_days: number;
  };
  upcoming: { id: string; prospect_id: string | null; start_time: string | null; status: string }[];
  escalations: { created_at: string | null; reason: string; prospect_id: string | null }[];
}

function HomeInner() {
  const [data, setData] = useState<Summary | null>(null);

  useEffect(() => {
    apiGet<Summary>("/api/v1/summary").then(setData).catch(() => {});
  }, []);

  if (!data) return <Spinner />;
  const m = data.metrics;

  return (
    <>
      <div className="grid cols-4" style={{ marginBottom: 18 }}>
        <Stat
          label="Pending review"
          value={<Link href="/approvals/">{data.pending_drafts}</Link>}
          accent={data.pending_drafts > 0}
          foot="drafts awaiting a human"
        />
        <Stat
          label={`Emails sent (${m.window_days}d)`}
          value={m.emails_out}
          foot={`${m.sms_out} SMS`}
        />
        <Stat
          label="Qualified leads"
          value={m.qualified_leads}
          foot={
            m.qualified_leads
              ? `$${m.cost_per_qualified_lead.toFixed(2)} / lead`
              : "—"
          }
        />
        <Stat
          label="LLM spend"
          value={`$${m.llm_cost_usd.toFixed(2)}`}
          foot={`bounce ${(m.bounce_rate * 100).toFixed(1)}% · opt-out ${(m.opt_out_rate * 100).toFixed(1)}%`}
        />
      </div>

      <div className="panel">
        <h2>Pipeline</h2>
        <div className="pipeline">
          {data.stages.map((s) => (
            <Link key={s} className="stage" href={`/prospects/?stage=${s}`}>
              <div className="n">{data.stage_counts[s] ?? 0}</div>
              <div className="s">{s.replace(/_/g, " ")}</div>
            </Link>
          ))}
        </div>
      </div>

      <div className="grid cols-2">
        <div className="panel">
          <h2>Upcoming meetings</h2>
          {data.upcoming.length ? (
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {data.upcoming.map((b) => (
                  <tr key={b.id}>
                    <td>{fmtDate(b.start_time)}</td>
                    <td>
                      <Badge tone={b.status === "confirmed" ? "good" : "muted"}>
                        {b.status}
                      </Badge>
                    </td>
                    <td>
                      {b.prospect_id && (
                        <Link href={`/prospects/detail/?id=${b.prospect_id}`}>
                          view
                        </Link>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted">No bookings on the calendar.</p>
          )}
        </div>

        <div className="panel">
          <h2>
            Needs a human <Badge tone="red">{data.escalations.length}</Badge>
          </h2>
          {data.escalations.length ? (
            <table>
              <thead>
                <tr>
                  <th>When</th>
                  <th>Reason</th>
                </tr>
              </thead>
              <tbody>
                {data.escalations.map((e, i) => (
                  <tr key={i}>
                    <td className="muted">{fmtDate(e.created_at)}</td>
                    <td>
                      {(e.reason || "").slice(0, 120)}
                      {e.prospect_id && (
                        <>
                          {" — "}
                          <Link href={`/prospects/detail/?id=${e.prospect_id}`}>
                            view prospect
                          </Link>
                        </>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="muted">Nothing escalated by the reply agent.</p>
          )}
        </div>
      </div>
    </>
  );
}

export default function HomePage() {
  return (
    <Shell title="Pipeline">
      <HomeInner />
    </Shell>
  );
}
