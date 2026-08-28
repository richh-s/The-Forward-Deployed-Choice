"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Shell, useMe } from "@/components/shell";
import { Badge, Empty, Flash, Pager, Spinner, scoreTone } from "@/components/ui";
import {
  apiGet,
  apiPost,
  DraftRow,
  Pager as PagerData,
  ProspectRow,
  fmtScore,
} from "@/lib/api";

interface ApprovalsData {
  rows: { draft: DraftRow; prospect: ProspectRow }[];
  pager: PagerData;
}

function Card({
  draft,
  prospect,
  onDone,
}: {
  draft: DraftRow;
  prospect: ProspectRow;
  onDone: (msg: string, err: boolean) => void;
}) {
  const me = useMe();
  const [subject, setSubject] = useState(draft.subject);
  const [body, setBody] = useState(draft.body);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const needsSubject = !["sms", "whatsapp", "telegram"].includes(draft.channel);

  async function approve(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    const res = await apiPost(
      `/approvals/${draft.id}/approve`,
      { subject, body },
      me.csrf_token,
    );
    onDone(res.msg, !res.ok);
  }

  async function reject() {
    setBusy(true);
    const res = await apiPost(
      `/approvals/${draft.id}/reject`,
      { reason },
      me.csrf_token,
    );
    onDone(res.msg, !res.ok);
  }

  async function testSend() {
    setBusy(true);
    const res = await apiPost(`/approvals/${draft.id}/test-send`, {}, me.csrf_token);
    onDone(res.msg, !res.ok);
  }

  return (
    <div className="panel">
      <div className="panel-head">
        <div className="who">
          <span className="av">{(prospect.name || prospect.email).slice(0, 2)}</span>
          <div>
            <div className="nm">
              <Link href={`/prospects/detail/?id=${prospect.id}`}>
                {prospect.name || prospect.email}
              </Link>
            </div>
            <div className="muted" style={{ fontSize: 12 }}>
              {prospect.company}
              {draft.kind === "reply" ? (
                <>
                  {" · "}
                  <Badge tone="warn">reply · {draft.channel}</Badge>
                </>
              ) : (
                <>
                  {" · "}touch #{draft.touch_number} · <Badge>{draft.mode}</Badge> ·
                  confidence {fmtScore(draft.avg_confidence)}
                </>
              )}
            </div>
          </div>
        </div>
        {draft.judge_score !== null ? (
          <Badge tone={scoreTone(draft.judge_score)}>
            Judge {fmtScore(draft.judge_score)}
          </Badge>
        ) : (
          <Badge tone="muted">reply — human review</Badge>
        )}
      </div>

      {Object.keys(draft.judge_scores).length > 0 && (
        <div className="row" style={{ gap: 6, flexWrap: "wrap", margin: "0 0 8px" }}>
          {Object.entries(draft.judge_scores).map(([dim, val]) => (
            <Badge key={dim} tone={scoreTone(val)}>
              {dim.replace(/_/g, " ")} {val.toFixed(1)}
            </Badge>
          ))}
        </div>
      )}
      {draft.judge_feedback && (
        <p className="subtle" style={{ margin: "0 0 12px" }}>
          Judge: {draft.judge_feedback}
        </p>
      )}
      {draft.grounding_notes && (
        <details style={{ margin: "0 0 12px" }}>
          <summary className="muted">Evidence — which signals back each claim</summary>
          <pre style={{ whiteSpace: "pre-wrap", fontSize: 12, margin: "6px 0 0" }}>
            {draft.grounding_notes}
          </pre>
          <p className="muted" style={{ fontSize: 12, margin: "6px 0 0" }}>
            Signal brief:
          </p>
          <pre style={{ whiteSpace: "pre-wrap", fontSize: 12, margin: 0 }}>
            {JSON.stringify(prospect.signals, null, 2)}
          </pre>
        </details>
      )}

      <form onSubmit={approve}>
        {needsSubject && (
          <>
            <label>Subject</label>
            <input value={subject} onChange={(e) => setSubject(e.target.value)} required />
          </>
        )}
        <label>
          Body <span className="muted">(editable before send)</span>
        </label>
        <textarea
          style={{ minHeight: 150 }}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          required
        />
        <div className="row" style={{ marginTop: 12, justifyContent: "space-between" }}>
          <span className="row" style={{ gap: 8 }}>
            <button disabled={busy}>Approve &amp; send</button>
            <button
              type="button"
              className="secondary"
              disabled={busy}
              title="Email this draft to yourself — no prospect is contacted"
              onClick={testSend}
            >
              Send test to me
            </button>
          </span>
          <span className="row" style={{ gap: 8 }}>
            <input
              placeholder="Rejection reason (optional)"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              style={{ width: 260 }}
            />
            <button
              type="button"
              className="secondary"
              style={{ color: "var(--bad)", borderColor: "var(--red-ring)" }}
              disabled={busy}
              onClick={reject}
            >
              Reject
            </button>
          </span>
        </div>
      </form>
    </div>
  );
}

function ApprovalsInner() {
  const me = useMe();
  const [data, setData] = useState<ApprovalsData | null>(null);
  const [page, setPage] = useState(1);
  const [minScore, setMinScore] = useState("0.9");
  const [flash, setFlash] = useState({ msg: "", err: false });

  const load = useCallback(() => {
    apiGet<ApprovalsData>(`/api/v1/approvals?page=${page}`)
      .then(setData)
      .catch(() => {});
  }, [page]);
  useEffect(load, [load]);

  // The approval queue moves — refresh it every 20s while the tab is open.
  useEffect(() => {
    const t = setInterval(load, 20_000);
    return () => clearInterval(t);
  }, [load]);

  function done(msg: string, err: boolean) {
    setFlash({ msg, err });
    load();
  }

  async function bulkApprove(e: FormEvent) {
    e.preventDefault();
    if (!confirm("Approve all pending drafts at or above this score?")) return;
    const res = await apiPost(
      "/approvals/bulk-approve",
      { min_score: minScore },
      me.csrf_token,
    );
    done(res.msg, !res.ok);
  }

  if (!data) return <Spinner />;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Approval queue</h1>
          <div className="sub">
            {data.pager.total} draft{data.pager.total !== 1 ? "s" : ""} awaiting review
          </div>
        </div>
        {data.rows.length > 0 && (
          <form className="row" onSubmit={bulkApprove}>
            <span className="muted">Bulk approve ≥</span>
            <input
              type="number"
              step="0.05"
              min={0}
              max={1}
              value={minScore}
              onChange={(e) => setMinScore(e.target.value)}
              style={{ width: 76 }}
            />
            <button className="secondary">Bulk approve</button>
          </form>
        )}
      </div>

      <Flash {...flash} />

      {data.rows.length === 0 && (
        <div className="panel">
          <Empty icon="✓" title="Queue is clear">
            Drafts land here as active campaigns compose outreach. Nothing needs
            your review right now.
          </Empty>
        </div>
      )}

      {data.rows.map(({ draft, prospect }) => (
        <Card key={draft.id} draft={draft} prospect={prospect} onDone={done} />
      ))}
      <Pager pager={data.pager} onPage={setPage} />
    </>
  );
}

export default function ApprovalsPage() {
  return (
    <Shell title="Approvals">
      <ApprovalsInner />
    </Shell>
  );
}
