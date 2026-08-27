"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { Shell, useMe } from "@/components/shell";
import { Badge, Banner, Flash, Spinner } from "@/components/ui";
import { apiGet, apiPost, fmtDate } from "@/lib/api";

interface SettingsData {
  provider_fields: Record<string, string[]>;
  configured: string[];
  webhook_urls: Record<string, string>;
  team: {
    id: string;
    email: string;
    name: string;
    role: string;
    must_change_password: boolean;
    last_login_at: string | null;
  }[];
  llm_defaults: Record<string, string>;
  killswitch_defaults: Record<string, number>;
  local_llm_configured: boolean;
  local_llm_base_url: string;
}

function formFields(e: FormEvent<HTMLFormElement>): Record<string, string> {
  const fd = new FormData(e.currentTarget);
  const out: Record<string, string> = {};
  fd.forEach((v, k) => (out[k] = String(v)));
  return out;
}

function CredentialForm({
  provider,
  fields,
  configured,
  onDone,
}: {
  provider: string;
  fields: string[];
  configured: boolean;
  onDone: (msg: string, err: boolean) => void;
}) {
  const me = useMe();
  const [busy, setBusy] = useState(false);

  async function save(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setBusy(true);
    const values = formFields(e);
    // Only send the fields the admin actually typed — the server merges
    // with what's stored, so partial updates never wipe other fields.
    const payload: Record<string, string> = {};
    for (const f of fields) if (values[f]?.trim()) payload[f] = values[f].trim();
    const res = await apiPost(
      `/settings/credentials/${provider}`,
      { payload_json: JSON.stringify(payload) },
      me.csrf_token,
    );
    onDone(res.msg, !res.ok);
    setBusy(false);
  }

  return (
    <details>
      <summary>
        {provider} {configured ? "✓" : ""}
      </summary>
      <form onSubmit={save}>
        {fields.map((f) => (
          <div key={f}>
            <label>{f}</label>
            <input
              name={f}
              placeholder={configured ? "(unchanged — type to replace)" : ""}
              autoComplete="off"
            />
          </div>
        ))}
        <p className="field-hint">
          Saving merges with what&apos;s stored — you can rotate a single field
          without re-typing the others.
        </p>
        <div style={{ marginTop: 8 }}>
          <button className="secondary" disabled={busy}>
            Save {provider}
          </button>
        </div>
      </form>
    </details>
  );
}

function SettingsInner() {
  const me = useMe();
  const isAdmin = me.user.role === "admin";
  const ws = me.workspace;
  const pb = ws.playbook as Record<string, string | string[]>;
  const [data, setData] = useState<SettingsData | null>(null);
  const [flash, setFlash] = useState({ msg: "", err: false });

  const load = useCallback(() => {
    apiGet<SettingsData>("/api/v1/settings").then(setData).catch(() => {});
  }, []);
  useEffect(load, [load]);

  function done(msg: string, err: boolean) {
    setFlash({ msg, err });
    load();
  }

  async function simple(path: string, fields: Record<string, string> = {}) {
    const res = await apiPost(path, fields, me.csrf_token);
    done(res.msg, !res.ok);
  }

  async function changePassword(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const res = await apiPost("/settings/password", formFields(e), me.csrf_token);
    if (res.ok || res.msg.includes("log in again")) {
      window.location.href = "/app/login/";
      return;
    }
    done(res.msg, true);
  }

  if (!data) return <Spinner />;
  const str = (k: string) => (typeof pb[k] === "string" ? (pb[k] as string) : "");

  return (
    <>
      <Flash {...flash} />
      {!isAdmin && (
        <Banner tone="warn">
          You have the operator role — provider credentials, playbook, models,
          team, and outbound controls are admin-only and hidden. Ask an admin
          for changes to them.
        </Banner>
      )}

      {isAdmin && (
        <div className="panel">
          <h2>Workspace &amp; sending identity</h2>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              const res = await apiPost("/settings/workspace", formFields(e), me.csrf_token);
              done(res.msg, !res.ok);
            }}
          >
            <div className="grid cols-2">
              <div>
                <label>Workspace name</label>
                <input name="name" defaultValue={ws.name} required />
              </div>
              <div>
                <label>From email (verified domain in Resend)</label>
                <input
                  name="from_email"
                  defaultValue={ws.from_email ?? ""}
                  placeholder="outreach@yourdomain.com"
                />
              </div>
              <div>
                <label>From name</label>
                <input name="from_name" defaultValue={ws.from_name ?? ""} />
              </div>
              <div>
                <label>SMS sender ID / shortcode</label>
                <input name="sms_sender_id" defaultValue={ws.sms_sender_id ?? ""} />
              </div>
            </div>
            <label>Cal.com event URL (e.g. https://cal.com/yourteam/intro-30min)</label>
            <input name="calcom_event_url" defaultValue={ws.calcom_event_url ?? ""} />
            <div style={{ marginTop: 10 }}>
              <button>Save</button>
            </div>
          </form>
        </div>
      )}

      <div className="panel">
        <h2>Outbound control</h2>
        <p>
          Status:{" "}
          {ws.outbound_paused ? (
            <>
              <Badge tone="bad">paused</Badge> — {ws.pause_reason}
            </>
          ) : (
            <Badge tone="good">sending allowed</Badge>
          )}
          {!me.live_mode && (
            <>
              {" · "}
              <Badge tone="warn">SINK MODE</Badge> — all messages route to the
              configured sink address.
            </>
          )}
        </p>
        {isAdmin ? (
          <>
            <div className="row">
              {ws.outbound_paused ? (
                <button
                  onClick={() => {
                    if (confirm("Resume outbound sending for this workspace?"))
                      simple("/settings/resume-outbound");
                  }}
                >
                  Resume outbound
                </button>
              ) : (
                <button className="danger" onClick={() => simple("/settings/pause-outbound")}>
                  Pause all outbound
                </button>
              )}
            </div>
            <hr />
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                const on = (
                  e.currentTarget.elements.namedItem(
                    "require_reply_approval",
                  ) as HTMLInputElement
                ).checked;
                const res = await apiPost(
                  "/settings/reply-approval",
                  on ? { require_reply_approval: "true" } : {},
                  me.csrf_token,
                );
                done(res.msg, !res.ok);
              }}
            >
              <label className="check">
                <input
                  type="checkbox"
                  name="require_reply_approval"
                  defaultChecked={ws.require_reply_approval}
                />
                Hold reply-agent responses for human review before sending
              </label>
              <p className="muted" style={{ margin: "6px 0 10px" }}>
                When unchecked, replies send automatically. Escalated replies
                (pricing, legal, anger, out-of-playbook questions) are always
                held regardless.
              </p>
              <button className="secondary">Save reply policy</button>
            </form>
            <hr />
            <form
              onSubmit={async (e) => {
                e.preventDefault();
                const res = await apiPost("/settings/killswitch", formFields(e), me.csrf_token);
                done(res.msg, !res.ok);
              }}
            >
              <h3 style={{ marginTop: 0 }}>Kill-switch thresholds</h3>
              <p className="muted" style={{ margin: "0 0 10px" }}>
                Breaching any of these pauses all outbound automatically. Blank =
                platform default. Rates are fractions (0.05 = 5%). Resuming
                restarts the measurement window.
              </p>
              <div className="grid cols-4">
                {(
                  [
                    ["opt_out_rate", "Opt-out rate"],
                    ["bounce_rate", "Bounce rate"],
                    ["cost_per_qualified_lead", "Cost / qualified lead ($)"],
                    ["max_llm_cost_usd", "LLM spend ceiling ($)"],
                  ] as const
                ).map(([k, label]) => (
                  <div key={k}>
                    <label>{label}</label>
                    <input
                      name={k}
                      defaultValue={ws.killswitch[k] ?? ""}
                      placeholder={String(data.killswitch_defaults[k] ?? "")}
                    />
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 10 }}>
                <button className="secondary">Save thresholds</button>
              </div>
            </form>
          </>
        ) : (
          <p className="muted">
            Pausing/resuming outbound and threshold changes are admin-only.
          </p>
        )}
      </div>

      {isAdmin && (
        <div className="panel">
          <h2>Playbook</h2>
          <p className="muted">
            The composer and reply agent may only make claims that appear here.
            Everything else is escalated to a human.
          </p>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              const res = await apiPost("/settings/playbook", formFields(e), me.csrf_token);
              done(res.msg, !res.ok);
            }}
          >
            <div className="grid cols-2">
              <div>
                <label>Company name</label>
                <input name="company_name" defaultValue={str("company_name")} />
              </div>
              <div>
                <label>Sign-off (exact signature)</label>
                <input name="sign_off" defaultValue={str("sign_off")} />
              </div>
            </div>
            <label>Company description</label>
            <textarea name="company_description" defaultValue={str("company_description")} />
            <label>Value proposition</label>
            <textarea name="value_proposition" defaultValue={str("value_proposition")} />
            <label>Ideal customer profile (ICP) definition</label>
            <textarea name="icp_definition" defaultValue={str("icp_definition")} />
            <label>Style guide</label>
            <textarea name="style_guide" defaultValue={str("style_guide")} />
            <label>Capacity / offering facts (the only capacity claims allowed)</label>
            <textarea name="capacity_notes" defaultValue={str("capacity_notes")} />
            <label>Public pricing notes</label>
            <textarea name="pricing_notes" defaultValue={str("pricing_notes")} />
            <label>Case studies (quotable outcomes)</label>
            <textarea name="case_studies" defaultValue={str("case_studies")} />
            <label>Example outreach (tone references)</label>
            <textarea name="examples" defaultValue={str("examples")} />
            <div className="grid cols-2">
              <div>
                <label>Support contact (shown in SMS HELP replies)</label>
                <input name="support_contact" defaultValue={str("support_contact")} />
              </div>
            </div>
            <label>Honesty constraints (one per line; defaults apply when empty)</label>
            <textarea
              name="honesty_constraints"
              defaultValue={
                Array.isArray(pb.honesty_constraints)
                  ? (pb.honesty_constraints as string[]).join("\n")
                  : ""
              }
            />
            <div style={{ marginTop: 10 }}>
              <button>Save playbook</button>
            </div>
          </form>
        </div>
      )}

      {isAdmin && (
        <div className="panel">
          <h2>Models</h2>
          <p className="muted">
            Choose the model for each role. Leave blank for the platform default
            (shown as the placeholder). Prefix with <span className="mono">local:</span>{" "}
            to route a role to your self-hosted models.
          </p>
          <p>
            Self-hosted endpoint:{" "}
            {data.local_llm_configured ? (
              <>
                {/* "configured", not "connected": only the env var is
                    checked — reachability isn't verified until a call. */}
                <Badge tone="good">configured</Badge>{" "}
                <span className="mono">{data.local_llm_base_url}</span>
              </>
            ) : (
              <>
                <Badge tone="muted">not configured</Badge> — set{" "}
                <span className="mono">LOCAL_LLM_BASE_URL</span> to enable.
              </>
            )}
          </p>
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              const res = await apiPost("/settings/models", formFields(e), me.csrf_token);
              done(res.msg, !res.ok);
            }}
          >
            <div className="grid cols-3">
              {(["compose", "reply", "judge"] as const).map((role) => (
                <div key={role}>
                  <label>{role} model</label>
                  <input
                    name={`${role}_model`}
                    defaultValue={ws.llm_config[role] ?? ""}
                    placeholder={data.llm_defaults[role]}
                  />
                </div>
              ))}
            </div>
            <div style={{ marginTop: 10 }}>
              <button>Save models</button>
            </div>
          </form>
        </div>
      )}

      {isAdmin && (
        <div className="panel">
          <h2>Provider credentials</h2>
          <p className="muted">
            Stored encrypted. Configured:{" "}
            {data.configured.length ? (
              data.configured.map((p) => (
                <Badge key={p} tone="good">
                  {p}
                </Badge>
              ))
            ) : (
              <span className="muted">none yet</span>
            )}
          </p>
          {Object.entries(data.provider_fields).map(([provider, fields]) => (
            <CredentialForm
              key={provider}
              provider={provider}
              fields={fields}
              configured={data.configured.includes(provider)}
              onDone={done}
            />
          ))}
        </div>
      )}

      {isAdmin && (
        <div className="panel">
          <h2>Webhook URLs to register</h2>
          <div className="table-wrap">
            <table>
              <tbody>
                {Object.entries(data.webhook_urls).map(([name, url]) => (
                  <tr key={name}>
                    <td style={{ width: 180 }}>{name}</td>
                    <td className="mono">{url}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted">
            Register each URL in the provider&apos;s dashboard and set the matching
            webhook signing secret in the credentials above. Webhooks without a
            configured secret are rejected.
          </p>
        </div>
      )}

      <div className="panel">
        <h2>Team</h2>
        {data.team.length > 0 && (
          <div className="table-wrap" style={{ marginBottom: 14 }}>
            <table>
              <thead>
                <tr>
                  <th>Email</th>
                  <th>Role</th>
                  <th>Last login</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {data.team.map((member) => (
                  <tr key={member.id}>
                    <td>
                      {member.email}
                      {member.id === me.user.id ? " (you)" : ""}
                    </td>
                    <td>
                      <Badge tone="muted">{member.role}</Badge>{" "}
                      {member.must_change_password && (
                        <Badge tone="warn">password change pending</Badge>
                      )}
                    </td>
                    <td className="muted">
                      {member.last_login_at ? fmtDate(member.last_login_at) : "never"}
                    </td>
                    <td>
                      {isAdmin && member.id !== me.user.id && (
                        // Real form POST in a new tab: the response page shows
                        // the one-time temporary password.
                        <form
                          method="post"
                          action={`/settings/users/${member.id}/reset-password`}
                          target="_blank"
                          className="inline"
                          onSubmit={(e) => {
                            if (
                              !confirm(
                                `Issue a temporary password for ${member.email}? All their sessions will be signed out.`,
                              )
                            )
                              e.preventDefault();
                          }}
                        >
                          <input type="hidden" name="csrf_token" value={me.csrf_token} />
                          <button className="secondary sm">Reset password</button>
                        </form>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {isAdmin ? (
          <form
            onSubmit={async (e) => {
              e.preventDefault();
              const form = e.currentTarget;
              const res = await apiPost("/settings/users", formFields(e), me.csrf_token);
              done(res.msg, !res.ok);
              if (res.ok) form.reset();
            }}
          >
            <div className="grid cols-3">
              <div>
                <label>Email</label>
                <input type="email" name="email" required />
              </div>
              <div>
                <label>Name</label>
                <input name="name" />
              </div>
              <div>
                <label>Role</label>
                <select name="role" defaultValue="operator">
                  <option value="operator">operator</option>
                  <option value="admin">admin</option>
                </select>
              </div>
            </div>
            <label>Temporary password (min 10 chars — replaced at first login)</label>
            <input type="password" name="password" minLength={10} required />
            <div style={{ marginTop: 10 }}>
              <button className="secondary">Add user</button>
            </div>
          </form>
        ) : (
          <p className="muted">Adding teammates is admin-only.</p>
        )}
      </div>

      {isAdmin && (
        <div className="panel">
          <h2>Judge fine-tuning data</h2>
          <p className="muted">
            Every human review (approve, reject, edit) is a labeled example.
            Export them as JSONL to fine-tune a workspace-specific judge.
          </p>
          <a className="btn secondary" href="/settings/export-judge-data">
            Download judge_training_data.jsonl
          </a>
        </div>
      )}

      <div className="panel">
        <h2>Your account</h2>
        <form onSubmit={changePassword}>
          <div className="grid cols-2">
            <div>
              <label>Current password</label>
              <input type="password" name="current_password" required />
            </div>
            <div>
              <label>New password (min 10 chars)</label>
              <input type="password" name="new_password" minLength={10} required />
            </div>
          </div>
          <p className="muted">
            Changing your password signs you out of every session, including this
            one.
          </p>
          <div style={{ marginTop: 10 }}>
            <button className="secondary">Change password</button>
          </div>
        </form>
      </div>
    </>
  );
}

export default function SettingsPage() {
  return (
    <Shell title="Settings">
      <SettingsInner />
    </Shell>
  );
}
