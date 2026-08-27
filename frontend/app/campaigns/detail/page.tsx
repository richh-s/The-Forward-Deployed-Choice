"use client";

import { FormEvent, Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Shell, useMe } from "@/components/shell";
import { Badge, Flash, Pager, Spinner } from "@/components/ui";
import {
  apiGet,
  apiPost,
  CampaignRow,
  Pager as PagerData,
  ProspectRow,
  fmtScore,
} from "@/lib/api";

interface Detail {
  campaign: CampaignRow;
  stages: string[];
  stage_counts: Record<string, number>;
  prospects: ProspectRow[];
  pager: PagerData;
}

function CampaignDetailInner() {
  const me = useMe();
  const id = useSearchParams().get("id") ?? "";
  const [data, setData] = useState<Detail | null>(null);
  const [page, setPage] = useState(1);
  const [flash, setFlash] = useState({ msg: "", err: false });
  const [uploading, setUploading] = useState(false);

  const load = useCallback(() => {
    if (!id) return;
    apiGet<Detail>(`/api/v1/campaigns/${id}?page=${page}`)
      .then(setData)
      .catch(() => {});
  }, [id, page]);
  useEffect(load, [load]);

  async function saveSettings(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const fd = new FormData(e.currentTarget);
    const fields: Record<string, string> = {};
    fd.forEach((v, k) => (fields[k] = String(v)));
    const res = await apiPost(`/campaigns/${id}/settings`, fields, me.csrf_token);
    setFlash({ msg: res.msg, err: !res.ok });
    load();
  }

  async function upload(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const input = e.currentTarget.elements.namedItem("file") as HTMLInputElement;
    const file = input.files?.[0];
    if (!file) return;
    setUploading(true);
    const res = await apiPost(`/campaigns/${id}/upload`, { file }, me.csrf_token);
    setFlash({ msg: res.msg, err: !res.ok });
    setUploading(false);
    input.value = "";
    load();
  }

  async function setStatus(status: string) {
    const res = await apiPost(`/campaigns/${id}/status`, { status }, me.csrf_token);
    setFlash({ msg: res.msg, err: !res.ok });
    load();
  }

  if (!id) return <p className="muted">Missing campaign id.</p>;
  if (!data) return <Spinner />;
  const c = data.campaign;

  return (
    <>
      <Flash {...flash} />
      <div className="panel">
        <div className="panel-head">
          <h2>
            {c.name} <Badge tone={c.status === "active" ? "good" : "muted"}>{c.status}</Badge>
          </h2>
          <span className="row" style={{ gap: 8 }}>
            {c.status !== "active" && (
              <button className="secondary sm" onClick={() => setStatus("active")}>
                Activate
              </button>
            )}
            {c.status === "active" && (
              <button className="secondary sm" onClick={() => setStatus("paused")}>
                Pause
              </button>
            )}
            {c.status !== "completed" && (
              <button className="secondary sm" onClick={() => setStatus("completed")}>
                Mark completed
              </button>
            )}
          </span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                {data.stages.map((s) => (
                  <th key={s}>{s.replace(/_/g, " ")}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              <tr>
                {data.stages.map((s) => (
                  <td key={s}>{data.stage_counts[s] ?? 0}</td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div className="grid cols-2">
        <div className="panel">
          <h2>Import prospects (CSV)</h2>
          <p className="muted">
            Columns: email (required), name, company, title, phone, signals
            (JSON object). Deduped per workspace by email.
          </p>
          <form onSubmit={upload} className="row">
            <input type="file" name="file" accept=".csv,text/csv" required />
            <button disabled={uploading}>{uploading ? "Importing…" : "Import"}</button>
          </form>
        </div>

        <div className="panel">
          <h2>Settings</h2>
          <form onSubmit={saveSettings}>
            <div className="grid cols-2">
              <div>
                <label>Daily cap</label>
                <input type="number" name="daily_cap" min={1} max={500} defaultValue={c.daily_cap} />
              </div>
              <div>
                <label>Auto-approve at judge score ≥</label>
                <input
                  type="number"
                  step="0.05"
                  min={0}
                  max={1}
                  name="auto_approve_score"
                  defaultValue={c.auto_approve_score}
                />
              </div>
              <div>
                <label>Send window start hour</label>
                <input
                  type="number"
                  min={0}
                  max={23}
                  name="send_window_start_hour"
                  defaultValue={c.send_window_start_hour}
                />
              </div>
              <div>
                <label>Send window end hour</label>
                <input
                  type="number"
                  min={1}
                  max={24}
                  name="send_window_end_hour"
                  defaultValue={c.send_window_end_hour}
                />
              </div>
            </div>
            <label>Timezone (IANA, e.g. Europe/Berlin — start &gt; end = overnight window)</label>
            <input name="timezone" defaultValue={c.timezone} />
            <label>Campaign angle (guides the composer)</label>
            <input name="angle" defaultValue={c.angle} />
            <label>Follow-up sequence (JSON: {"[{\"day_offset\": 3, \"angle\": \"…\"}]"})</label>
            <textarea
              name="sequence_json"
              className="mono"
              defaultValue={JSON.stringify(c.sequence)}
            />
            <label className="check">
              <input
                type="checkbox"
                name="require_approval"
                value="true"
                defaultChecked={c.require_approval}
              />
              Require human approval for every draft
            </label>
            <div style={{ marginTop: 10 }}>
              <button>Save settings</button>
            </div>
          </form>
        </div>
      </div>

      <div className="panel">
        <h2>Prospects</h2>
        {data.prospects.length ? (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Name</th>
                    <th>Company</th>
                    <th>Email</th>
                    <th>Stage</th>
                    <th>Conf.</th>
                    <th>Touches</th>
                  </tr>
                </thead>
                <tbody>
                  {data.prospects.map((p) => (
                    <tr key={p.id}>
                      <td>
                        <Link href={`/prospects/detail/?id=${p.id}`}>{p.name || "—"}</Link>
                      </td>
                      <td>{p.company || "—"}</td>
                      <td className="mono">{p.email}</td>
                      <td>
                        <Badge
                          tone={
                            ["warm", "booked"].includes(p.stage)
                              ? "good"
                              : ["lost", "opted_out"].includes(p.stage)
                                ? "bad"
                                : "muted"
                          }
                        >
                          {p.stage.replace(/_/g, " ")}
                        </Badge>
                      </td>
                      <td>{fmtScore(p.avg_confidence)}</td>
                      <td>{p.touch_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager pager={data.pager} onPage={setPage} />
          </>
        ) : (
          <p className="muted">No prospects yet — import a CSV above.</p>
        )}
      </div>
    </>
  );
}

export default function CampaignDetailPage() {
  return (
    <Shell title="Campaign">
      <Suspense fallback={<Spinner />}>
        <CampaignDetailInner />
      </Suspense>
    </Shell>
  );
}
