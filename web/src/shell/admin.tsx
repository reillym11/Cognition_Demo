import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { http } from "../api/client";
import {
  ApprovalPanel, Badge, Button, Card, Checkbox, DataTable, ErrorBox, Field, Page, ReasonAction, dt, humanize, type Approval, Input, SearchBox, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow,
} from "../ui/kit";
import { actionLabel, formatUnit, fromInput, inputSuffix, policyMeta, resourceLabel, roleLabel, toInput, toolLabel, type PolicyField } from "../ui/labels";
import { can, useMe } from "./me";
import { PERSONAS } from "./personas.gen";

export function InboxPage() {
  const q = useQuery({ queryKey: ["inbox"], queryFn: () => http<Approval[]>("GET", "/api/approvals/inbox") });
  const mine = useQuery({ queryKey: ["inbox", "mine"], queryFn: () => http<Approval[]>("GET", "/api/approvals/mine") });
  return (
    <Page title="Approvals inbox">
      <ErrorBox error={q.error} />
      <Card title={`Waiting for you (${q.data?.length ?? 0})`}>
        <div className="space-y-3">
          {q.data?.length === 0 && <p className="text-sm text-slate-500">Nothing to approve.</p>}
          {q.data?.map((a) => <ApprovalPanel key={a.id} approval={a} invalidate={[["inbox"]]} />)}
        </div>
      </Card>
      <Card title="Requested by you">
        <div className="space-y-3">{mine.data?.length === 0 && <p className="text-sm text-slate-500">You have not requested any approvals.</p>}{mine.data?.slice(0, 20).map((a) => <ApprovalPanel key={a.id} approval={a} invalidate={[["inbox"]]} />)}</div>
      </Card>
    </Page>
  );
}

type Verify = { chain: string; count: number; ok: boolean; first_bad_seq: number | null; problem: string | null };

export function AuditPage() {
  const me = useMe();
  const [filters, setFilters] = useState({ chain: "", actor: "", action: "", resource_id: "" });
  const verify = useQuery({ queryKey: ["audit-verify"], queryFn: () => http<Verify[]>("GET", "/api/audit/verify") });
  const [range, setRange] = useState({ start: new Date().toISOString().slice(0, 10), end: new Date().toISOString().slice(0, 10) });
  return (
    <Page title="Audit log">
      <Card title="Hash-chain verification">
        <div className="flex flex-wrap gap-2" data-testid="chain-status">
          {verify.data?.map((v) => (
            <Badge key={v.chain} tone={v.ok ? "green" : "red"}>
              {toolLabel(v.chain)}: {v.ok ? `Intact (${v.count.toLocaleString()} events)` : `Broken at event ${v.first_bad_seq}`}
            </Badge>
          ))}
        </div>
      </Card>
      {can(me.data, "core.audit.evidence") && (
        <Card title="Evidence pack">
          <div className="flex flex-wrap items-end gap-2">
            <Field label="From"><Input type="date" value={range.start} onChange={(e) => setRange({ ...range, start: e.target.value })} /></Field>
            <Field label="To"><Input type="date" value={range.end} onChange={(e) => setRange({ ...range, end: e.target.value })} /></Field>
            <ReasonAction
              label="Download evidence pack"
              onSubmit={async (reason) => {
                const r = await fetch(`/api/audit/evidence-pack?start=${range.start}&end=${range.end}&reason=${encodeURIComponent(reason)}`);
                if (!r.ok) throw new Error((await r.json()).detail);
                const a = document.createElement("a");
                a.href = URL.createObjectURL(await r.blob());
                a.download = `evidence-${range.start}-${range.end}.zip`;
                a.click();
              }}
            />
          </div>
        </Card>
      )}
      <div className="flex flex-wrap gap-2">
        {([["chain", "Chain", "kyc"], ["actor", "Actor", "Name"], ["action", "Action", "kyc.decided"], ["resource_id", "Record ID", "123"]] as const).map(([k, label, ph]) => (
          <SearchBox key={k} label={label} placeholder={ph} value={filters[k]} onChange={(v) => setFilters({ ...filters, [k]: v })} />
        ))}
      </div>
      <DataTable<{ id: number; seq: number; occurred_at: string; actor_name: string; action: string; resource: string; resource_id: string; reason: string | null; chain: string }>
        url="/api/audit/events"
        params={filters}
        columns={[
          { key: "seq", label: "Event" },
          { key: "occurred_at", label: "When", render: (r) => dt(r.occurred_at) },
          { key: "chain", label: "Chain", render: (r) => toolLabel(r.chain) },
          { key: "actor_name", label: "Actor" },
          { key: "action", label: "Action", render: (r) => actionLabel(r.action) },
          { key: "resource", label: "Record", render: (r) => resourceLabel(r.resource, r.resource_id) },
          { key: "reason", label: "Reason", render: (r) => r.reason ?? "---" },
        ]}
      />
    </Page>
  );
}

type Policy = { key: string; description: string; kind: string; approver: string; approver_roles?: string[]; value: unknown; version: number; pending_request_id: number | null };

const fieldValue = (value: unknown, f: PolicyField) => (f.key ? (value as Record<string, unknown>)?.[f.key] : value);

function PolicyChange({ p, onDone }: { p: Policy; onDone: () => void }) {
  const meta = policyMeta(p.key, p.kind, p.value);
  const init = () => Object.fromEntries(meta.fields.map((f, i) => [i, f.unit === "bool" ? Boolean(fieldValue(p.value, f)) : toInput(fieldValue(p.value, f), f)]));
  const [draft, setDraft] = useState<Record<number, string | boolean>>(init);
  const build = () => {
    const vals = meta.fields.map((f, i) => (f.unit === "bool" ? Boolean(draft[i]) : fromInput(String(draft[i]), f)));
    if (!meta.fields[0]?.key) return vals[0];
    return { ...(p.value as object), ...Object.fromEntries(meta.fields.map((f, i) => [f.key!, vals[i]])) };
  };
  return (
    <ReasonAction
      label="Request change"
      extra={
        <div className="space-y-2">
          <p className="text-sm font-semibold">{meta.name}</p>
          {meta.fields.map((f, i) =>
            f.unit === "bool" ? (
              <Checkbox key={i} label={f.label} checked={Boolean(draft[i])} onChange={(_, d) => setDraft({ ...draft, [i]: Boolean(d.checked) })} />
            ) : (
              <Field key={i} label={`${f.label}${inputSuffix(f) ? ` (${inputSuffix(f)})` : ""}`}>
                <Input type="number" value={String(draft[i])} onChange={(e) => setDraft({ ...draft, [i]: e.target.value })} />
              </Field>
            ),
          )}
        </div>
      }
      onSubmit={async (reason) => {
        await http("POST", `/api/policy/${p.key}/change-request`, { value: build(), reason });
        onDone();
      }}
    />
  );
}

export function PolicyPage() {
  const me = useMe();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["policy"], queryFn: () => http<Policy[]>("GET", "/api/policy") });
  return (
    <Page title="Policies" subtitle="Versioned settings; every change needs a second approver">
      <ErrorBox error={q.error} />
      <div className="overflow-x-auto rounded-lg border bg-white">
        <table className="w-full border-collapse text-sm">
          <thead className="bg-slate-100 text-left text-xs uppercase text-slate-600">
            <tr>
              <th className="w-[110px] px-3 py-2 font-semibold">Tool</th>
              <th className="px-3 py-2 font-semibold">Policy</th>
              <th className="w-[330px] px-3 py-2 font-semibold">Current value</th>
              <th className="w-[150px] px-3 py-2 font-semibold">Approved by</th>
              <th className="w-[90px] px-3 py-2 font-semibold">Version</th>
              <th className="w-[170px] px-3 py-2 font-semibold">Change</th>
            </tr>
          </thead>
          <tbody>
            {q.data?.map((p) => {
              const meta = policyMeta(p.key, p.kind, p.value);
              return (
                <tr key={p.key} className="border-t align-top" data-testid={`policy-${p.key}`}>
                  <td className="px-3 py-3">{toolLabel(p.key)}</td>
                  <td className="px-3 py-3"><div className="font-semibold">{meta.name}</div><div className="text-xs text-slate-500">{p.description.replace(/system:kyc-fastlane/g, "the fast lane")}</div></td>
                  <td className="px-3 py-3">
                    <dl className="grid grid-cols-[1fr_max-content] gap-x-4 gap-y-1">
                      {meta.fields.map((f) => (
                        <Fragment key={f.label}>
                          <dt className="text-slate-600">{f.label}</dt>
                          <dd className="whitespace-nowrap text-right font-semibold">{formatUnit(fieldValue(p.value, f), f)}</dd>
                        </Fragment>
                      ))}
                    </dl>
                  </td>
                  <td className="px-3 py-3">{p.approver_roles?.length ? p.approver_roles.map(roleLabel).join(", ") : "---"}</td>
                  <td className="whitespace-nowrap px-3 py-3">{p.version ? `Version ${p.version}` : "Default"}</td>
                  <td className="px-3 py-3">
                    {p.pending_request_id ? (
                      <Badge tone="amber">Pending approval (request {p.pending_request_id})</Badge>
                    ) : can(me.data, "core.policy.request") ? (
                      <PolicyChange p={p} onDone={() => qc.invalidateQueries({ queryKey: ["policy"] })} />
                    ) : "---"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Page>
  );
}

type JobRow = { id: number; kind: string; status: string; attempts: number; max_attempts: number; last_error: string | null; created_at: string };

export function JobsPage() {
  const me = useMe();
  const qc = useQueryClient();
  const [status, setStatus] = useState("");
  const q = useQuery({
    queryKey: ["jobs", status],
    queryFn: () => http<{ summary: { counts: Record<string, number> }; items: JobRow[] }>("GET", `/api/jobs${status ? `?status=${status}` : ""}`),
    refetchInterval: 3000,
  });
  return (
    <Page title="Background jobs">
      <div className="flex flex-wrap gap-2">
        {Object.entries(q.data?.summary.counts ?? {}).map(([s, n]) => (
          <Button key={s} onClick={() => setStatus(status === s ? "" : s)} variant={status === s ? "primary" : "secondary"}>
            {humanize(s)}: {n}
          </Button>
        ))}
      </div>
      <div className="overflow-x-auto rounded-lg border bg-white">
        <Table size="small" className="min-w-full text-sm">
          <TableHeader className="bg-slate-100 text-left text-xs uppercase text-slate-600">
            <TableRow><TableHeaderCell className="px-3 py-2">Job</TableHeaderCell><TableHeaderCell className="px-3 py-2">Type</TableHeaderCell><TableHeaderCell className="px-3 py-2">Status</TableHeaderCell><TableHeaderCell className="px-3 py-2">Attempts</TableHeaderCell><TableHeaderCell className="px-3 py-2">Created</TableHeaderCell><TableHeaderCell className="px-3 py-2">Last error</TableHeaderCell><TableHeaderCell className="px-3 py-2">Action</TableHeaderCell></TableRow>
          </TableHeader>
          <TableBody>
            {q.data?.items.map((j) => (
              <TableRow key={j.id} className="border-t align-top">
                <TableCell className="px-3 py-2">{j.id}</TableCell>
                <TableCell className="px-3 py-2">{toolLabel(j.kind)}: {humanize(j.kind.split(".").slice(1).join(" ") || j.kind)}</TableCell>
                <TableCell className="px-3 py-2"><Badge tone={j.status === "succeeded" ? "green" : j.status === "dead" ? "red" : "amber"}>{humanize(j.status)}</Badge></TableCell>
                <TableCell className="px-3 py-2">{j.attempts} of {j.max_attempts}</TableCell>
                <TableCell className="px-3 py-2 whitespace-nowrap">{dt(j.created_at)}</TableCell>
                <TableCell className="max-w-md truncate px-3 py-2 text-xs text-slate-600" title={j.last_error ?? undefined}>{j.last_error ?? "---"}</TableCell>
                <TableCell className="px-3 py-2">
                  {j.status === "dead" && can(me.data, "core.jobs.admin") && (
                    <ReasonAction label="Retry" onSubmit={async (reason) => { await http("POST", `/api/jobs/${j.id}/retry`, { reason }); qc.invalidateQueries({ queryKey: ["jobs"] }); }} />
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </Page>
  );
}

const OFFERED_ROLES = new Set(PERSONAS.flatMap((p) => p.roles));

type Matrix = { roles: Record<string, string[]>; permissions: { permission: string; description: string; routes: string[] }[]; separation_of_duties: string[] };

const ROLE_GROUP: Record<string, string> = {
  KYC: "KYC", Compliance: "Compliance", Support: "Support", Complaints: "Complaints", Finance: "Finance", AP: "AP", Eng: "Engineering", Platform: "Platform", Audit: "Audit",
};
const GROUP_ORDER = ["KYC", "Compliance", "Support", "Finance", "Complaints", "AP", "Engineering", "Platform", "Audit"];
const TOOL_ORDER = ["kyc", "refunds", "flags", "complaints", "ap", "core"];

export function AccessPage() {
  const q = useQuery({ queryKey: ["access"], queryFn: () => http<Matrix>("GET", "/api/access-matrix") });
  const group = (r: string) => ROLE_GROUP[r.split(".")[0]] ?? humanize(r.split(".")[0]);
  // Only roles someone can sign in as; test-only roles stay in code but are not shown.
  const roles = Object.keys(q.data?.roles ?? {}).filter((r) => OFFERED_ROLES.has(r)).sort((a, b) => GROUP_ORDER.indexOf(group(a)) - GROUP_ORDER.indexOf(group(b)) || roleLabel(a).localeCompare(roleLabel(b)));
  const tools = TOOL_ORDER.filter((t) => q.data?.permissions.some((p) => p.permission.startsWith(`${t}.`)));
  return (
    <Page title="Access matrix">
      <ErrorBox error={q.error} />
      <Card title="Separation of duties">
        <ul className="list-disc space-y-0.5 pl-5 text-sm">{q.data?.separation_of_duties.map((s) => <li key={s}>{s}</li>)}</ul>
      </Card>
      <div className="overflow-x-auto rounded-lg border bg-white" data-testid="access-matrix">
        <table className="w-full border-collapse text-xs">
          <thead className="sticky top-0 bg-slate-100 text-slate-700">
            <tr>
              <th className="sticky left-0 z-10 min-w-[220px] border-b border-r bg-slate-100 px-3 py-2 text-left font-semibold">Permission</th>
              {roles.map((r) => (
                <th key={r} className="w-[62px] min-w-[62px] border-b border-r px-1 py-2 text-center align-bottom font-semibold leading-tight">{roleLabel(r)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {tools.map((t) => (
              <Fragment key={t}>
                <tr className="bg-slate-50">
                  <td colSpan={roles.length + 1} className="sticky left-0 border-b px-3 py-1.5 text-sm font-semibold text-slate-800">{toolLabel(t)}</td>
                </tr>
                {q.data!.permissions.filter((p) => p.permission.startsWith(`${t}.`)).map((p) => (
                  <tr key={p.permission} className="hover:bg-blue-50">
                    <td className="sticky left-0 border-b border-r bg-white px-3 py-1.5">{p.description}</td>
                    {roles.map((r) => (
                      <td key={r} className="border-b border-r text-center text-sm" aria-label={q.data!.roles[r].includes(p.permission) ? `${roleLabel(r)}: yes` : `${roleLabel(r)}: no`}>
                        {q.data!.roles[r].includes(p.permission) ? <span className="font-bold text-blue-700">✓</span> : ""}
                      </td>
                    ))}
                  </tr>
                ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </Page>
  );
}
