"use client";

import { FormEvent, useEffect, useState } from "react";
import Link from "next/link";
import { Shell, useMe } from "@/components/shell";
import { Badge, Empty, Flash, Spinner } from "@/components/ui";
import { apiGet, apiPost, CampaignRow } from "@/lib/api";

function statusTone(s: string): "good" | "warn" | "bad" | "muted" {
  return s === "active" ? "good" : s === "paused" ? "warn" : "muted";
}

function CampaignsInner() {
  const me = useMe();
  const [rows, setRows] = useState<CampaignRow[] | null>(null);
  const [flash, setFlash] = useState({ msg: "", err: false });
  const [busy, setBusy] = useState(false);

  function load() {
    apiGet<{ campaigns: CampaignRow[] }>("/api/v1/campaigns")
      .then((d) => setRows(d.campaigns))
      .catch(() => {});
  }
  useEffect(load, []);

  async function create(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    const form = e.currentTarget;
    const fd = new FormData(form);
    const res = await apiPost(
      "/campaigns",
      { name: String(fd.get("name") ?? "") },
      me.csrf_token,
    );
    setFlash({ msg: res.msg || (res.ok ? "Campaign created" : "Failed"), err: !res.ok });
    if (res.ok) form.reset();
    setBusy(false);
    load();
  }

  async function setStatus(id: string, status: string) {
    const res = await apiPost(`/campaigns/${id}/status`, { status }, me.csrf_token);
    setFlash({ msg: res.msg, err: !res.ok });
    load();
  }

  if (!rows) return <Spinner />;

  return (
    <>
      <Flash {...flash} />
      <div className="panel">
        <h2>New campaign</h2>
        <form onSubmit={create} className="row">
          <input
            name="name"
            placeholder="Campaign name (e.g. Series A CTOs — Q3)"
            required
            style={{ maxWidth: 420 }}
          />
          <button disabled={busy}>Create</button>
        </form>
      </div>

      <div className="panel">
        <h2>Campaigns</h2>
        {rows.length ? (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Status</th>
                  <th>Prospects</th>
                  <th>Daily cap</th>
                  <th>LLM cost</th>
                  <th>Angle</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((c) => (
                  <tr key={c.id}>
                    <td>
                      <Link href={`/campaigns/detail/?id=${c.id}`}>
                        <strong>{c.name}</strong>
                      </Link>
                    </td>
                    <td>
                      <Badge tone={statusTone(c.status)}>{c.status}</Badge>
                    </td>
                    <td>{c.prospect_count ?? 0}</td>
                    <td>{c.daily_cap}/day</td>
                    <td>${(c.llm_cost_usd ?? 0).toFixed(2)}</td>
                    <td className="muted">{c.angle || "—"}</td>
                    <td>
                      <span className="row" style={{ gap: 6 }}>
                        {c.status === "active" ? (
                          <button
                            className="secondary sm"
                            onClick={() => setStatus(c.id, "paused")}
                          >
                            Pause
                          </button>
                        ) : (
                          <button
                            className="secondary sm"
                            onClick={() => setStatus(c.id, "active")}
                          >
                            Activate
                          </button>
                        )}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty icon="◈" title="No campaigns yet">
            Create one above, then import a prospect CSV from its page.
          </Empty>
        )}
      </div>
    </>
  );
}

export default function CampaignsPage() {
  return (
    <Shell title="Campaigns">
      <CampaignsInner />
    </Shell>
  );
}
