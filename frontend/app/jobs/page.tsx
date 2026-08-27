"use client";

import { useCallback, useEffect, useState } from "react";
import { Shell, useMe } from "@/components/shell";
import { Badge, Flash, Pager, Spinner, Stat } from "@/components/ui";
import { apiGet, apiPost, JobRow, Pager as PagerData, fmtDate } from "@/lib/api";

interface JobsData {
  status_counts: Record<string, number>;
  problem_jobs: JobRow[];
  pager: PagerData;
}

const STATUSES = ["pending", "running", "done", "failed", "dead"];

function JobsInner() {
  const me = useMe();
  const [data, setData] = useState<JobsData | null>(null);
  const [page, setPage] = useState(1);
  const [flash, setFlash] = useState({ msg: "", err: false });

  const load = useCallback(() => {
    apiGet<JobsData>(`/api/v1/jobs?page=${page}`).then(setData).catch(() => {});
  }, [page]);
  useEffect(load, [load]);

  // Queue state changes constantly — poll while the tab is open.
  useEffect(() => {
    const t = setInterval(load, 10_000);
    return () => clearInterval(t);
  }, [load]);

  async function retry(id: string) {
    const res = await apiPost(`/jobs/${id}/retry`, {}, me.csrf_token);
    setFlash({ msg: res.msg, err: !res.ok });
    load();
  }

  if (!data) return <Spinner />;

  return (
    <>
      <Flash {...flash} />
      <div className="grid cols-4" style={{ marginBottom: 16 }}>
        {STATUSES.map((s) => (
          <Stat
            key={s}
            label={s}
            value={data.status_counts[s] ?? 0}
            accent={s === "dead" && (data.status_counts[s] ?? 0) > 0}
          />
        ))}
      </div>

      <div className="panel">
        <h2>Failing &amp; dead jobs</h2>
        {data.problem_jobs.length === 0 ? (
          <p className="muted">Nothing failing — the queue is healthy.</p>
        ) : (
          <>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Status</th>
                    <th>Attempts</th>
                    <th>Last error</th>
                    <th>Updated</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody>
                  {data.problem_jobs.map((j) => (
                    <tr key={j.id}>
                      <td>
                        <code>{j.type}</code>
                      </td>
                      <td>
                        <Badge tone={j.status === "dead" ? "bad" : "warn"}>{j.status}</Badge>
                      </td>
                      <td>
                        {j.attempts}/{j.max_attempts}
                      </td>
                      <td
                        className="muted"
                        style={{
                          maxWidth: 420,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                        title={j.last_error}
                      >
                        {j.last_error.slice(0, 160)}
                      </td>
                      <td className="muted">{fmtDate(j.updated_at)}</td>
                      <td>
                        {me.user.role === "admin" && (
                          <button className="secondary sm" onClick={() => retry(j.id)}>
                            Retry
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager pager={data.pager} onPage={setPage} />
          </>
        )}
      </div>
    </>
  );
}

export default function JobsPage() {
  return (
    <Shell title="Jobs">
      <JobsInner />
    </Shell>
  );
}
