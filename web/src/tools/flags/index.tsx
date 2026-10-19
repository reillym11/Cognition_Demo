import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { http } from "../../api/client";
import { can, useMe } from "../../shell/me";
import {
  ApprovalPanel, Badge, Card, DataTable, ErrorBox, Field, Page, ReasonAction, dt, type Approval, Input, Checkbox, SearchBox, Button, Choice, humanize, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow,
} from "../../ui/kit";
import type { ToolRoute } from "../registry";

type Rule = { attribute: string; op: string; values: string[] };
type EnvCfg = { enabled: boolean; rollout_pct: number; rules: Rule[]; default_value: boolean; version: number; updated_by: string; updated_at: string; stale: boolean };
type Flag = { id: number; key: string; description: string; owner: string; envs: Record<string, EnvCfg>; stale: boolean };
type Change = { id: number; env: string; actor: string; approved_by: string | null; reason: string; before: Record<string, unknown>; after: Record<string, unknown>; at: string };
const ENVS = ["dev", "staging", "prod"];
const ENV_LABEL: Record<string, string> = { dev: "Development", staging: "Staging", prod: "Production" };
const envLabel = (e: string) => ENV_LABEL[e] ?? humanize(e);
const ATTRS: [string, string][] = [["region", "Region"], ["plan", "Plan"], ["email_domain", "Email domain"], ["user_id", "User ID"]];
const attrLabel = (a: string) => ATTRS.find(([k]) => k === a)?.[1] ?? humanize(a);
const ACRONYM = new Set(["api", "ui", "ux", "sso", "kyc", "ap", "pdf", "csv", "sms", "ml"]);

/** "alerts.v2-api" -> "Alerts: v2 API". The key stays the identifier for URLs and the API. */
export function flagName(key: string): string {
  const word = (w: string) => (ACRONYM.has(w) ? w.toUpperCase() : /^v\d+$/.test(w) ? w : w[0].toUpperCase() + w.slice(1));
  const part = (p: string) => p.split(/[-_]+/).filter(Boolean).map(word).join(" ");
  const [area, ...rest] = key.split(".");
  return rest.length ? `${part(area)}: ${part(rest.join(" "))}` : part(area);
}

const ruleText = (r: Rule) => `${attrLabel(r.attribute)} ${r.op === "in" ? "is" : "is not"} ${r.values.join(", ")}`;

function describeCfg(c: Partial<EnvCfg>): string {
  if (!c.enabled) return `Off (serves ${c.default_value ? "on" : "off"})`;
  return [`On for ${c.rollout_pct}%`, ...(c.rules ?? []).map(ruleText)].join(" · ");
}

function fmtVal(k: string, v: unknown): string {
  if (v === null || v === undefined) return "---";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (k === "rollout_pct") return `${v}%`;
  if (Array.isArray(v)) return v.length ? (v as Rule[]).map(ruleText).join("; ") : "None";
  return String(v);
}
const DIFF_LABEL: Record<string, string> = { enabled: "Enabled", rollout_pct: "Rollout", rules: "Targeting rules", default_value: "Value when off" };

const envBadge = (e?: EnvCfg) =>
  !e ? "---" : <Badge tone={!e.enabled ? "slate" : e.rollout_pct === 100 ? "green" : "blue"}>{e.enabled ? `${e.rollout_pct}%${e.rules.length ? " + rules" : ""}` : "Off"}</Badge>;

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
              <Field label="Key" hint="Used in code, e.g. checkout.new-flow"><Input  aria-label="Key" placeholder="area.feature-name" value={nf.key} onChange={(e) => setNf({ ...nf, key: e.target.value })} /></Field>
              <Field label="Description"><Input  aria-label="Description" value={nf.description} onChange={(e) => setNf({ ...nf, description: e.target.value })} /></Field>
            </div>
          }
          onSubmit={async (reason) => { await http("POST", "/api/flags", { ...nf, reason }); qc.invalidateQueries(); nav(`/flags/${nf.key}`); }}
        />
      )}
    >
      <div className="flex flex-wrap items-end gap-3">
        <SearchBox label="Search flags" placeholder="Flag key" value={q} onChange={(v) => setQ(v)} />
        <Checkbox checked={!!stale} onChange={(e) => setStale(e.target.checked ? "1" : "")} label={<>Stale only (100% in prod &gt; 14 days)</>} />
      </div>
      <DataTable<Flag>
        url="/api/flags"
        params={{ q, stale }}
        rowTestId="flag-row"
        onRowClick={(r) => nav(`/flags/${r.key}`)}
        columns={[
          { key: "key", label: "Flag", render: (r) => <span className="inline-flex flex-col"><span className="font-semibold">{flagName(r.key)} {r.stale && <Badge tone="amber">Stale</Badge>}</span><span className="text-xs text-slate-500">{r.key}</span></span> },
          { key: "owner", label: "Owner" },
          ...ENVS.map((e) => ({ key: e, label: envLabel(e), render: (r: Flag) => envBadge(r.envs[e]) })),
        ]}
      />
    </Page>
  );
}

function RulesEditor({ env, rules, disabled, onChange }: { env: string; rules: Rule[]; disabled: boolean; onChange: (r: Rule[]) => void }) {
  const set = (i: number, patch: Partial<Rule>) => onChange(rules.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <div className="space-y-2" aria-label={`${env} rules`}>
      <p className="text-sm font-semibold">Targeting rules</p>
      {rules.length === 0 && <p className="text-xs text-slate-500">No rules: the rollout applies to everyone.</p>}
      {rules.map((r, i) => (
        <div key={i} className="flex flex-wrap items-center gap-1">
          <Choice aria-label="Attribute" value={r.attribute} disabled={disabled} onChange={(e) => set(i, { attribute: e.target.value })}>
            {ATTRS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </Choice>
          <Choice aria-label="Condition" value={r.op} disabled={disabled} onChange={(e) => set(i, { op: e.target.value })}>
            <option value="in">is one of</option>
            <option value="not_in">is not one of</option>
          </Choice>
          <Input aria-label="Values" placeholder="US, EU" disabled={disabled} value={r.values.join(", ")} onChange={(e) => set(i, { values: e.target.value.split(",").map((v) => v.trim()).filter(Boolean) })} />
          {!disabled && <Button variant="subtle" onClick={() => onChange(rules.filter((_, j) => j !== i))}>Remove</Button>}
        </div>
      ))}
      {!disabled && <Button size="small" onClick={() => onChange([...rules, { attribute: "region", op: "in", values: [] }])}>Add rule</Button>}
    </div>
  );
}

function EnvEditor({ flagKey, env, cfg, canEdit, onDone }: { flagKey: string; env: string; cfg: EnvCfg; canEdit: boolean; onDone: (msg: string) => void }) {
  const [s, setS] = useState({ enabled: cfg.enabled, rollout_pct: cfg.rollout_pct, default_value: cfg.default_value, rules: cfg.rules });
  const seeded = cfg.updated_by === "seed";
  return (
    <Card title={`${envLabel(env)}${cfg.stale ? " · Stale" : ""}`}>
      <div className="space-y-2 text-sm">
        <Checkbox aria-label={`${env} enabled`} checked={s.enabled} disabled={!canEdit} onChange={(e) => setS({ ...s, enabled: e.target.checked })} label={<>Enabled</>} />
        <Field label="Rollout (%)"><Input  aria-label={`${env} rollout`} type="number" min={0} max={100} disabled={!canEdit} value={String(s.rollout_pct)} onChange={(e) => setS({ ...s, rollout_pct: Number(e.target.value) })} /></Field>
        <RulesEditor env={env} rules={s.rules} disabled={!canEdit} onChange={(rules) => setS({ ...s, rules })} />
        <Checkbox aria-label={`${env} default`} checked={s.default_value} disabled={!canEdit} onChange={(e) => setS({ ...s, default_value: e.target.checked })} label={<>Value when off / outside rollout</>} />
        {!seeded && <p className="text-xs text-slate-500">Last changed by {cfg.updated_by} · {dt(cfg.updated_at)}</p>}
        {canEdit && (
          <ReasonAction
            label={env === "prod" ? "Request production change" : "Save"}
            variant="primary"
            testId={`save-${env}`}
            onSubmit={async (reason) => {
              const r = await http<{ status: string }>("PUT", `/api/flags/${flagKey}/envs/${env}`, { enabled: s.enabled, rollout_pct: s.rollout_pct, default_value: s.default_value, rules: s.rules, reason });
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
    <Page subtitle="Feature flag" title={flagName(f.key)} status={f.stale ? <Badge tone="amber">Stale: clean up the code path</Badge> : undefined}>
      <p className="text-sm text-slate-600">Key <span className="font-mono">{f.key}</span> · Owner {f.owner}</p>
      {msg && <p role="status" className="text-sm text-green-800">{msg}</p>}
      <div className="grid gap-4 lg:grid-cols-3">
        {ENVS.map((e) => (
          <EnvEditor key={`${e}-${f.envs[e].version}`} flagKey={f.key} env={e} cfg={f.envs[e]} canEdit={e === "prod" ? q.data!.can.prod : q.data!.can.edit} onDone={done} />
        ))}
      </div>
      {q.data.pending_prod && (
        <Card title="Pending production change">
          {q.data.pending_payload?.after && <p className="mb-2 text-sm">Proposed: <strong>{describeCfg(q.data.pending_payload.after)}</strong></p>}
          <ApprovalPanel approval={q.data.pending_prod} invalidate={[qk]} />
        </Card>
      )}
      <Card title="Change history">
        <Table size="small" className="min-w-full text-sm">
          <TableHeader className="text-left text-xs uppercase text-slate-500"><TableRow><TableHeaderCell>When</TableHeaderCell><TableHeaderCell>Environment</TableHeaderCell><TableHeaderCell>By</TableHeaderCell><TableHeaderCell>Approved by</TableHeaderCell><TableHeaderCell>Reason</TableHeaderCell><TableHeaderCell>Change</TableHeaderCell></TableRow></TableHeader>
          <TableBody>
            {q.data.history.length === 0 && <TableRow><TableCell colSpan={6} className="py-2 text-slate-500">No changes yet.</TableCell></TableRow>}
            {q.data.history.map((c) => (
              <TableRow key={c.id} className="border-t align-top">
                <TableCell className="py-1 pr-2">{dt(c.at)}</TableCell><TableCell>{envLabel(c.env)}</TableCell><TableCell>{c.actor}</TableCell><TableCell>{c.approved_by ?? "---"}</TableCell><TableCell>{c.reason}</TableCell>
                <TableCell className="text-xs">
                  {Object.keys(c.after).filter((k) => k in DIFF_LABEL && JSON.stringify(c.before[k]) !== JSON.stringify(c.after[k])).map((k) => (
                    <div key={k}>{DIFF_LABEL[k]}: {fmtVal(k, c.before[k])} → {fmtVal(k, c.after[k])}</div>
                  ))}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
    </Page>
  );
}

export const routes: ToolRoute[] = [
  { path: "/flags", element: <FlagList /> },
  { path: "/flags/:key", element: <FlagDetail /> },
];
