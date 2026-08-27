"use client";

import { FormEvent, Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Shell } from "@/components/shell";
import { Badge, Empty, Pager, Spinner } from "@/components/ui";
import { apiGet, Pager as PagerData, ProspectRow, fmtScore } from "@/lib/api";

interface ListData {
  prospects: ProspectRow[];
  pager: PagerData;
  stages: string[];
}

function ProspectsInner() {
  const initialStage = useSearchParams().get("stage") ?? "";
  const [stage, setStage] = useState(initialStage);
  const [q, setQ] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<ListData | null>(null);

  const load = useCallback(() => {
    const params = new URLSearchParams();
    if (stage) params.set("stage", stage);
    if (search) params.set("q", search);
    params.set("page", String(page));
    apiGet<ListData>(`/api/v1/prospects?${params}`).then(setData).catch(() => {});
  }, [stage, search, page]);
  useEffect(load, [load]);

  function submitSearch(e: FormEvent) {
    e.preventDefault();
    setPage(1);
    setSearch(q.trim());
  }

  if (!data) return <Spinner />;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Prospects</h1>
          <div className="sub">
            {data.pager.total} total
            {stage ? (
              <>
                {" "}
                · filtered by <strong>{stage.replace(/_/g, " ")}</strong>
              </>
            ) : null}
            {search ? (
              <>
                {" "}
                · matching <strong>{search}</strong>
              </>
            ) : null}
          </div>
        </div>
        <span className="row" style={{ gap: 8 }}>
          <form onSubmit={submitSearch} className="row" style={{ gap: 8 }}>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Search name, email, company"
              style={{ width: 220 }}
            />
            <button className="secondary">Search</button>
          </form>
          <a className="btn secondary" href="/prospects.csv">
            Export CSV
          </a>
          <Link className="btn" href="/campaigns/">
            Import prospects
          </Link>
        </span>
      </div>

      <div className="segmented" style={{ marginBottom: 16 }}>
        <a
          className={!stage ? "active" : ""}
          onClick={() => {
            setStage("");
            setPage(1);
          }}
          style={{ cursor: "pointer" }}
        >
          all
        </a>
        {data.stages.map((s) => (
          <a
            key={s}
            className={stage === s ? "active" : ""}
            onClick={() => {
              setStage(s);
              setPage(1);
            }}
            style={{ cursor: "pointer" }}
          >
            {s.replace(/_/g, " ")}
          </a>
        ))}
      </div>

      {data.prospects.length ? (
        <div className="panel">
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
                      <span className="who">
                        <span className="av">{(p.name || p.email).slice(0, 2)}</span>
                        <Link className="nm" href={`/prospects/detail/?id=${p.id}`}>
                          {p.name || "—"}
                        </Link>
                      </span>
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
        </div>
      ) : (
        <div className="panel">
          <Empty icon="◉" title={stage || search ? "No matches" : "No prospects yet"}>
            {stage || search
              ? "Nothing matches the current filter."
              : "Create a campaign and import a prospect list (CSV) to start building your pipeline."}
          </Empty>
        </div>
      )}
    </>
  );
}

export default function ProspectsPage() {
  return (
    <Shell title="Prospects">
      <Suspense fallback={<Spinner />}>
        <ProspectsInner />
      </Suspense>
    </Shell>
  );
}
