/** Same-origin API access.
 *
 * Reads: /api/v1/* JSON endpoints.
 * Writes: the engine's existing (CSRF-protected, audited) form routes —
 * FormData + the csrf_token from /api/v1/me. The 303-redirect target URL
 * carries the outcome (?msg=...&err=1), which we parse instead of the body.
 */

export interface Pager {
  page: number;
  pages: number;
  total: number;
  qs: string;
}

export interface Me {
  user: { id: string; email: string; name: string; role: "admin" | "operator" };
  workspace: {
    id: string;
    name: string;
    slug: string;
    outbound_paused: boolean;
    pause_reason: string | null;
    require_reply_approval: boolean;
    from_email: string | null;
    from_name: string | null;
    sms_sender_id: string | null;
    calcom_event_url: string | null;
    playbook: Record<string, unknown>;
    llm_config: Record<string, string>;
    killswitch: Record<string, number>;
  };
  csrf_token: string;
  stages: string[];
  dead_jobs: number;
  live_mode: boolean;
}

export interface ProspectRow {
  id: string;
  email: string;
  name: string;
  company: string;
  title: string;
  phone: string | null;
  stage: string;
  icp_segment: number | null;
  touch_count: number;
  avg_confidence: number | null;
  campaign_id: string | null;
  signals: Record<string, unknown>;
  next_followup_at: string | null;
  hubspot_contact_id: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface CampaignRow {
  id: string;
  name: string;
  status: string;
  daily_cap: number;
  require_approval: boolean;
  auto_approve_score: number;
  send_window_start_hour: number;
  send_window_end_hour: number;
  timezone: string;
  sequence: { day_offset: number; angle?: string }[];
  angle: string;
  created_at: string | null;
  prospect_count?: number;
  llm_cost_usd?: number;
}

export interface DraftRow {
  id: string;
  prospect_id: string;
  campaign_id: string | null;
  kind: string;
  channel: string;
  subject: string;
  body: string;
  mode: string;
  angle: string;
  avg_confidence: number | null;
  judge_score: number | null;
  judge_scores: Record<string, number>;
  judge_feedback: string;
  grounding_notes: string;
  touch_number: number;
  status: string;
  auto_approved: boolean;
  reject_reason: string | null;
  compose_cost_usd: number;
  created_at: string | null;
}

export interface JobRow {
  id: string;
  type: string;
  status: string;
  attempts: number;
  max_attempts: number;
  last_error: string;
  updated_at: string | null;
}

export interface WriteResult {
  ok: boolean;
  msg: string;
}

export const LOGIN_PATH = "/app/login/";

export async function apiGet<T>(path: string): Promise<T> {
  const r = await fetch(path, { credentials: "same-origin" });
  if (r.status === 401) {
    window.location.href = LOGIN_PATH;
    throw new Error("unauthorized");
  }
  if (!r.ok) throw new Error(`GET ${path} failed: ${r.status}`);
  return r.json() as Promise<T>;
}

export async function apiPost(
  path: string,
  fields: Record<string, string | Blob>,
  csrf: string,
): Promise<WriteResult> {
  const fd = new FormData();
  fd.set("csrf_token", csrf);
  for (const [k, v] of Object.entries(fields)) fd.set(k, v);
  const r = await fetch(path, {
    method: "POST",
    body: fd,
    credentials: "same-origin",
    redirect: "follow",
  });
  if (r.status === 401) {
    window.location.href = LOGIN_PATH;
    return { ok: false, msg: "Signed out" };
  }
  // The engine answers writes with a 303 whose target carries the outcome.
  let msg = "";
  let err = false;
  try {
    const u = new URL(r.url);
    msg = u.searchParams.get("error") ?? u.searchParams.get("msg") ?? "";
    err = u.searchParams.get("err") === "1" || u.searchParams.has("error");
  } catch {
    /* non-redirect response — fall back to status */
  }
  if (!r.ok && !msg) msg = `Request failed (${r.status})`;
  return { ok: r.ok && !err, msg };
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function fmtScore(v: number | null | undefined): string {
  return v === null || v === undefined ? "—" : v.toFixed(2);
}
