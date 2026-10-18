import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { http } from "../../api/client";
import { can, useMe } from "../../shell/me";
import { ApprovalPanel, Badge, Card, DataTable, ErrorBox, Field, Page, ReasonAction, dt, inputCls, type Approval } from "../../ui/kit";
import type { ToolRoute } from "../registry";

type Rule = { attribute: string; op: string; values: string[] };
type EnvCfg = { enabled: boolean; rollout_pct: number; rules: Rule[]; default_value: boolean; version: number; updated_by: string; updated_at: string; stale: boolean };
type Flag = { id: number; key: string; description: string; owner: string; envs: Record<string, EnvCfg>; stale: boolean };
type Change = { id: number; env: string; actor: string; approved_by: string | null; reason: string; before: Record<string, unknown>; after: Record<string, unknown>; at: string };
const ENVS = ["dev", "staging", "prod"];

const envBadge = (e?: EnvCfg) =>
  !e ? "—" : <Badge tone={!e.enabled ? "slate" : e.rollout_pct === 100 ? "green" : "blue"}>{e.enabled ? `${e.rollout_pct}%${e.rules.length ? " + rules" : ""}` : "off"}</Badge>;

function FlagList() {
  const me = useMe();
  const nav = useNavigate();
  const qc = useQueryClient();
  const [sp] = useSearchParams();
  const [q, setQ] = useState("");
  const [stale, setStale] = useState(sp.get("stale") ? "1" : "");
  const [nf, setNf] = useState({ key: "", description: "" });
  return (
    <Page
      title="Feature flags"
      actions={can(me.data, "flags.create") && (
        <ReasonAction
          label="New flag"
          variant="primary"
          extra={
            <div className="flex gap-2">
              <Field label="Key"><input className={inputCls} aria-label="Key" placeholder="area.feature-name" value={nf.key} onChange={(e) => setNf({ ...nf, key: e.target.value })} /></Field>
              <Field label="Description"><input className={inputCls} aria-label="Description" value={nf.description} onChange={(e) => setNf({ ...nf, description: e.target.value })} /></Field>
            </div>
          }
          onSubmit={async (reason) => { await http("POST", "/api/flags", { ...nf, reason }); qc.invalidateQueries(); nav(`/flags/${nf.key}`); }}
        />
      )}
    >
      <div className="flex gap-2">
        <input aria-label="Search flags" placeholder="search key" className="rounded border px-2 py-1 text-sm" value={q} onChange={(e) => setQ(e.target.value)} />
        <label className="flex items-center gap-1 text-sm"><input type="checkbox" checked={!!stale} onChange={(e) => setStale(e.target.checked ? "1" : "")} /> Stale only (100% in prod &gt; 14 days)</label>
      </div>
      <DataTable<Flag>
        url="/api/flags"
        params={{ q, stale }}
        rowTestId="flag-row"
        onRowClick={(r) => nav(`/flags/${r.key}`)}
        columns={[
          { key: "key", label: "Key", render: (r) => <span className="font-mono">{r.key} {r.stale && <Badge tone="amber">stale</Badge>}</span> },
          { key: "owner", label: "Owner" },
          ...ENVS.map((e) => ({ key: e, label: e, render: (r: Flag) => envBadge(r.envs[e]) })),
        ]}
      />
    </Page>
  );
}

function EnvEditor({ flagKey, env, cfg, canEdit, onDone }: { flagKey: string; env: string; cfg: EnvCfg; canEdit: boolean; onDone: (msg: string) => void }) {
  const [s, setS] = useState({ enabled: cfg.enabled, rollout_pct: cfg.rollout_pct, default_value: cfg.default_value, rules: JSON.stringify(cfg.rules) });
  return (
    <Card title={`${env}${cfg.stale ? " · stale" : ""}`}>
      <div className="space-y-2 text-sm">
        <label className="flex items-center gap-2"><input type="checkbox" aria-label={`${env} enabled`} checked={s.enabled} disabled={!canEdit} onChange={(e) => setS({ ...s, enabled: e.target.checked })} /> Enabled</label>
        <Field label="Rollout %"><input className={inputCls} aria-label={`${env} rollout`} type="number" min={0} max={100} disabled={!canEdit} value={s.rollout_pct} onChange={(e) => setS({ ...s, rollout_pct: Number(e.target.value) })} /></Field>
        <Field label='Rules (JSON, e.g. [{"attribute":"region","op":"in","values":["US"]}])'><textarea className={inputCls} aria-label={`${env} rules`} rows={2} disabled={!canEdit} value={s.rules} onChange={(e) => setS({ ...s, rules: e.target.value })} /></Field>
        <label className="flex items-center gap-2"><input type="checkbox" aria-label={`${env} default`} checked={s.default_value} disabled={!canEdit} onChange={(e) => setS({ ...s, default_value: e.target.checked })} /> Value when off / outside rollout</label>
        <p className="text-xs text-slate-500">v{cfg.version} · {cfg.updated_by} · {dt(cfg.updated_at)}</p>
        {canEdit && (
          <ReasonAction
            label={env === "prod" ? "Request prod change" : "Save"}
            variant="primary"
            testId={`save-${env}`}
            onSubmit={async (reason) => {
              const r = await http<{ status: string }>("PUT", `/api/flags/${flagKey}/envs/${env}`, { enabled: s.enabled, rollout_pct: s.rollout_pct, default_value: s.default_value, rules: JSON.parse(s.rules || "[]"), reason });
              onDone(r.status === "pending_approval" ? "Sent for approval" : "Applied");
            }}
          />
        )}
      </div>
    </Card>
  );
}

function FlagDetail() {
  const { key } = useParams();
  const qc = useQueryClient();
  const qk = ["flag", key!];
  const q = useQuery({ queryKey: qk, queryFn: () => http<{ flag: Flag; pending_prod: Approval | null; pending_payload: { after: EnvCfg } | null; history: Change[]; can: { edit: boolean; prod: boolean } }>("GET", `/api/flags/${key}`) });
  const [msg, setMsg] = useState("");
  if (!q.data) return <ErrorBox error={q.error} />;
  const f = q.data.flag;
  const done = (m: string) => { setMsg(m); qc.invalidateQueries({ queryKey: qk }); };
  return (
    <Page title={f.key} actions={f.stale ? <Badge tone="amber">stale: clean up the code path</Badge> : undefined}>
      <p className="text-sm text-slate-600">{f.description} · owner {f.owner}</p>
      {msg && <p role="status" className="text-sm text-green-800">{msg}</p>}
      <div className="grid gap-4 lg:grid-cols-3">
        {ENVS.map((e) => (
          <EnvEditor key={`${e}-${f.envs[e].version}`} flagKey={f.key} env={e} cfg={f.envs[e]} canEdit={e === "prod" ? q.data!.can.prod : q.data!.can.edit} onDone={done} />
        ))}
      </div>
      {q.data.pending_prod && (
        <Card title="Pending production change">
          <pre className="mb-2 overflow-x-auto rounded bg-slate-50 p-2 text-xs">{JSON.stringify(q.data.pending_payload?.after, null, 2)}</pre>
          <ApprovalPanel approval={q.data.pending_prod} invalidate={[qk]} />
        </Card>
      )}
      <Card title="Change history">
        <table className="min-w-full text-sm">
          <thead className="text-left text-xs uppercase text-slate-500"><tr><th>When</th><th>Env</th><th>By</th><th>Approved by</th><th>Reason</th><th>Diff</th></tr></thead>
          <tbody>
            {q.data.history.map((c) => (
              <tr key={c.id} className="border-t align-top">
                <td className="py-1 pr-2">{dt(c.at)}</td><td>{c.env}</td><td>{c.actor}</td><td>{c.approved_by ?? "—"}</td><td>{c.reason}</td>
                <td className="font-mono text-xs">
                  {Object.keys(c.after).filter((k) => JSON.stringify(c.before[k]) !== JSON.stringify(c.after[k])).map((k) => (
                    <div key={k}>{k}: {JSON.stringify(c.before[k])} → {JSON.stringify(c.after[k])}</div>
                  ))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>
    </Page>
  );
}

export const routes: ToolRoute[] = [
  { path: "/flags", element: <FlagList /> },
  { path: "/flags/:key", element: <FlagDetail /> },
];
