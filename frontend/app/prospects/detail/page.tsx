"use client";

import { FormEvent, Suspense, useCallback, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Shell, useMe } from "@/components/shell";
import { Badge, Banner, Flash, Spinner, scoreTone } from "@/components/ui";
import { apiGet, apiPost, DraftRow, ProspectRow, fmtDate, fmtScore } from "@/lib/api";

interface Detail {
  prospect: ProspectRow;
  stages: string[];
  timeline: {
    id: string;
    channel: string;
    direction: string;
    subject: string;
    body: string;
    status: string;
    intent: string | null;
    created_at: string | null;
  }[];
  drafts: DraftRow[];
  bookings: { id: string; start_time: string | null; status: string }[];
}

function ProspectDetailInner() {
  const me = useMe();
  const id = useSearchParams().get("id") ?? "";
  const [data, setData] = useState<Detail | null>(null);
  const [flash, setFlash] = useState({ msg: "", err: false });

  const load = useCallback(() => {
    if (!id) return;
    apiGet<Detail>(`/api/v1/prospects/${id}`).then(setData).catch(() => {});
  }, [id]);
  useEffect(load, [load]);

  async function act(path: string, fields: Record<string, string> = {}) {
    const res = await apiPost(path, fields, me.csrf_token);
    setFlash({ msg: res.msg, err: !res.ok });
    load();
    return res;
  }

  async function saveSignals(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    await act(`/prospects/${id}/signals`, {
      signals_json: String(fd.get("signals_json") ?? "{}"),
    });
  }

  async function erase() {
    if (
      !confirm(
        "Erase this prospect's personal data (messages, drafts, bookings)? " +
          "Their address stays on the do-not-contact list. This cannot be undone.",
      )
    )
      return;
    const res = await apiPost(`/prospects/${id}/delete`, {}, me.csrf_token);
    if (res.ok) window.location.href = "/app/prospects/";
    else setFlash({ msg: res.msg, err: true });
  }

  if (!id) return <p className="muted">Missing prospect id.</p>;
  if (!data) return <Spinner />;
  const p = data.prospect;
  const enrichFailed = Boolean(p.signals && (p.signals as Record<string, unknown>)["_enrichment_failed"]);

  return (
    <>
      <Flash {...flash} />
      <div className="panel">
        <div className="row" style={{ justifyContent: "space-between" }}>
          <div>
            <h2 style={{ margin: "0 0 4px" }}>
              {p.name || p.email} <Badge>{p.stage}</Badge>
            </h2>
            <div className="muted">
              {p.title}
              {p.title && p.company ? " · " : ""}
              {p.company} · <span className="mono">{p.email}</span>
              {p.phone ? (
                <>
                  {" · "}
                  <span className="mono">{p.phone}</span>
                </>
              ) : null}
            </div>
          </div>
          <span className="row" style={{ gap: 8 }}>
            <button
              className="secondary"
              title="Run the composer + judge now; the draft lands in Approvals"
              onClick={() => act(`/prospects/${id}/compose`)}
            >
              Compose draft now
            </button>
            <form
              className="inline row"
              onSubmit={(e) => {
                e.preventDefault();
                const sel = e.currentTarget.elements.namedItem("stage") as HTMLSelectElement;
                act(`/prospects/${id}/stage`, { stage: sel.value });
              }}
            >
              <select name="stage" defaultValue={p.stage} style={{ width: "auto" }}>
                {data.stages.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
              <button className="secondary">Set stage</button>
            </form>
            {me.user.role === "admin" && (
              <button
                className="secondary"
                style={{ color: "var(--bad)" }}
                title="GDPR/CCPA erasure — removes their data, keeps the opt-out"
                onClick={erase}
              >
                Erase data
              </button>
            )}
          </span>
        </div>
        <div className="muted" style={{ marginTop: 8 }}>
          Touches: {p.touch_count}
          {p.avg_confidence !== null && <> · signal confidence {fmtScore(p.avg_confidence)}</>}
          {p.next_followup_at && <> · next follow-up {fmtDate(p.next_followup_at)}</>}
          {p.hubspot_contact_id && <> · HubSpot #{p.hubspot_contact_id}</>}
        </div>
        {enrichFailed && (
          <div style={{ marginTop: 10 }}>
            <Banner tone="warn">
              Enrichment failed for this prospect after all retries — it proceeded
              without signals (inquiry mode). Fix the enrichment source and use
              “Compose draft now”, or paste signals below.
            </Banner>
          </div>
        )}
      </div>

      <div className="grid cols-2">
        <div className="panel">
          <h2>Conversation timeline</h2>
          {data.timeline.length ? (
            data.timeline.map((m) => (
              <div key={m.id} className={`timeline-item ${m.direction}`}>
                <div className="meta">
                  {fmtDate(m.created_at)} · {m.channel.toUpperCase()}{" "}
                  {m.direction === "out" ? "→ out" : "← in"} ·{" "}
                  <Badge tone="muted">{m.status}</Badge>{" "}
                  {m.intent && (
                    <Badge tone={m.intent === "warm" ? "good" : "muted"}>{m.intent}</Badge>
                  )}
                </div>
                {m.subject && <strong>{m.subject}</strong>}
                <pre>{m.body}</pre>
              </div>
            ))
          ) : (
            <p className="muted">No messages yet.</p>
          )}
        </div>

        <div>
          <div className="panel">
            <h2>Bookings</h2>
            {data.bookings.length ? (
              <table>
                <thead>
                  <tr>
                    <th>When</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {data.bookings.map((b) => (
                    <tr key={b.id}>
                      <td>{fmtDate(b.start_time)}</td>
                      <td>
                        <Badge tone={b.status === "confirmed" ? "good" : "muted"}>
                          {b.status}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="muted">No bookings.</p>
            )}
          </div>

          <div className="panel">
            <h2>Drafts</h2>
            {data.drafts.length ? (
              <table>
                <thead>
                  <tr>
                    <th>Touch</th>
                    <th>Score</th>
                    <th>Status</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {data.drafts.map((d) => (
                    <>
                      <tr key={d.id}>
                        <td>#{d.touch_number}</td>
                        <td>
                          <Badge tone={scoreTone(d.judge_score)}>
                            {fmtScore(d.judge_score)}
                          </Badge>
                        </td>
                        <td>
                          <Badge
                            tone={
                              ["rejected", "failed"].includes(d.status) ? "bad" : "muted"
                            }
                          >
                            {d.status}
                          </Badge>
                        </td>
                        <td className="muted">{fmtDate(d.created_at)}</td>
                      </tr>
                      {(d.reject_reason || d.judge_feedback) && (
                        <tr key={`${d.id}-notes`}>
                          <td colSpan={4} className="muted" style={{ fontSize: 12 }}>
                            {d.reject_reason ? `Reason: ${d.reject_reason}` : ""}
                            {d.reject_reason && d.judge_feedback ? " · " : ""}
                            {d.judge_feedback
                              ? `Judge: ${d.judge_feedback.slice(0, 300)}`
                              : ""}
                          </td>
                        </tr>
                      )}
                    </>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="muted">No drafts.</p>
            )}
          </div>

          <div className="panel">
            <h2>Enrichment signals</h2>
            <form onSubmit={saveSignals}>
              <textarea
                name="signals_json"
                className="mono"
                style={{ minHeight: 160 }}
                defaultValue={JSON.stringify(p.signals ?? {}, null, 2)}
              />
              <div style={{ marginTop: 8 }}>
                <button className="secondary">Save signals</button>
              </div>
            </form>
          </div>
        </div>
      </div>
    </>
  );
}

export default function ProspectDetailPage() {
  return (
    <Shell title="Prospect">
      <Suspense fallback={<Spinner />}>
        <ProspectDetailInner />
      </Suspense>
    </Shell>
  );
}
