"use client";

import { useEffect, useState } from "react";
import { Shell } from "@/components/shell";
import { Spinner, Stat } from "@/components/ui";
import { apiGet } from "@/lib/api";

interface Analytics {
  metrics: {
    window_days: number;
    emails_out: number;
    sms_out: number;
    bounce_rate: number;
    opt_out_rate: number;
    qualified_leads: number;
    llm_cost_usd: number;
    cost_per_qualified_lead: number;
  };
  funnel: { label: string; value: number }[];
  angles: {
    angle: string;
    sends: number;
    replies: number;
    reply_rate: number;
    bookings: number;
  }[];
  calibration: {
    bands: {
      band: string;
      reviewed: number;
      approved: number;
      approval_rate: number | null;
      avg_edit_ratio: number | null;
    }[];
    recommended_auto_approve_score: number | null;
    reviewed_total: number;
  };
  edits: {
    reviewed: number;
    avg_edit_ratio: number | null;
    sent_verbatim: number;
    heavily_edited: number;
  };
  delivery: {
    warmup_enabled: boolean;
    warmup_day: number;
    cap_today: number;
    full_cap: number;
    warmed_up: boolean;
    bounced_7d: number;
    complained_7d: number;
  };
}

const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${(v * 100).toFixed(1)}%`;

function AnalyticsInner() {
  const [data, setData] = useState<Analytics | null>(null);

  useEffect(() => {
    apiGet<Analytics>("/api/v1/analytics").then(setData).catch(() => {});
  }, []);

  if (!data) return <Spinner />;
  const maxFunnel = Math.max(...data.funnel.map((f) => f.value), 1);
  const m = data.metrics;
  const d = data.delivery;

  return (
    <>
      <div className="panel">
        <h2>Funnel (all time)</h2>
        <table>
          <tbody>
            {data.funnel.map((f) => (
              <tr key={f.label}>
                <td style={{ width: 180 }}>{f.label}</td>
                <td style={{ width: 80 }}>
                  <strong>{f.value}</strong>
                </td>
                <td>
                  <div
                    className={`funnel-bar${f.value === 0 ? " dim" : ""}`}
                    style={{ width: `${Math.max((f.value / maxFunnel) * 100, 1)}%` }}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="panel">
        <h2>Health metrics — rolling {m.window_days} days</h2>
        <div className="grid cols-3">
          <Stat label="Emails sent" value={m.emails_out} />
          <Stat label="SMS sent" value={m.sms_out} />
          <Stat label="Qualified leads" value={m.qualified_leads} />
          <Stat label="Bounce rate" value={pct(m.bounce_rate)} />
          <Stat label="Opt-out rate" value={pct(m.opt_out_rate)} />
          <Stat
            label="Cost / qualified lead"
            value={`$${m.cost_per_qualified_lead.toFixed(2)}`}
          />
        </div>
        <p className="muted">
          These metrics drive the kill-switch: breaching a threshold pauses all
          outbound for this workspace until an admin reviews and resumes it in
          Settings.
        </p>
      </div>

      <div className="panel">
        <h2>Deliverability — domain warm-up</h2>
        <div className="grid cols-3">
          <Stat
            label="Today's email cap"
            value={d.cap_today}
            foot={d.warmed_up ? "fully warmed" : `warming up, day ${d.warmup_day}`}
          />
          <Stat label="Bounces (7d)" value={d.bounced_7d} accent={d.bounced_7d > 0} />
          <Stat
            label="Complaints (7d)"
            value={d.complained_7d}
            accent={d.complained_7d > 0}
          />
        </div>
        <p className="muted">
          {d.warmed_up
            ? `Domain fully warmed up — the full cap of ${d.full_cap}/day applies.`
            : `New sending domains ramp automatically toward the ${d.full_cap}/day cap so early volume can't burn the domain.`}
        </p>
      </div>

      <div className="panel">
        <h2>Learning — angle performance (90 days)</h2>
        {data.angles.length ? (
          <>
            <table>
              <thead>
                <tr>
                  <th>Angle</th>
                  <th>Sends</th>
                  <th>Replies</th>
                  <th>Reply rate</th>
                  <th>Bookings</th>
                </tr>
              </thead>
              <tbody>
                {data.angles.map((a) => (
                  <tr key={a.angle}>
                    <td>{a.angle}</td>
                    <td>{a.sends}</td>
                    <td>{a.replies}</td>
                    <td>
                      <strong>{pct(a.reply_rate)}</strong>
                    </td>
                    <td>{a.bookings}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="muted">
              Replies and bookings are attributed to the last touch that preceded
              them. Promote the winning angles in your campaign sequences.
            </p>
          </>
        ) : (
          <p className="muted">
            No sent drafts in the window yet — angle performance appears once
            campaigns start sending.
          </p>
        )}
      </div>

      <div className="panel">
        <h2>Learning — judge calibration (90 days)</h2>
        {data.calibration.reviewed_total ? (
          <>
            <table>
              <thead>
                <tr>
                  <th>Judge score band</th>
                  <th>Reviewed</th>
                  <th>Approved</th>
                  <th>Approval rate</th>
                  <th>Avg human edit</th>
                </tr>
              </thead>
              <tbody>
                {data.calibration.bands.map((b) => (
                  <tr key={b.band}>
                    <td>{b.band}</td>
                    <td>{b.reviewed}</td>
                    <td>{b.approved}</td>
                    <td>{pct(b.approval_rate)}</td>
                    <td>{pct(b.avg_edit_ratio)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {data.calibration.recommended_auto_approve_score !== null && (
              <p className="muted">
                Humans approve near-unanimously down to a judge score of{" "}
                <strong>{data.calibration.recommended_auto_approve_score}</strong> —
                you can consider lowering the campaign auto-approve threshold to
                that value.
              </p>
            )}
          </>
        ) : (
          <p className="muted">
            Calibration appears once drafts have been human-reviewed.
          </p>
        )}
        <div className="grid cols-3" style={{ marginTop: 12 }}>
          <Stat label="Drafts human-reviewed" value={data.edits.reviewed} />
          <Stat label="Avg human edit" value={pct(data.edits.avg_edit_ratio)} />
          <Stat label="Sent verbatim" value={data.edits.sent_verbatim} />
        </div>
      </div>
    </>
  );
}

export default function AnalyticsPage() {
  return (
    <Shell title="Analytics">
      <AnalyticsInner />
    </Shell>
  );
}
