import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { http } from "../api/client";
import { ApprovalPanel, Badge, Button, Card, DataTable, ErrorBox, Field, inputCls, Page, ReasonAction, dt, type Approval } from "../ui/kit";
import { can, useMe } from "./me";

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
        <div className="space-y-3">{mine.data?.slice(0, 20).map((a) => <ApprovalPanel key={a.id} approval={a} invalidate={[["inbox"]]} />)}</div>
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
              {v.chain}: {v.ok ? `OK (${v.count})` : `BROKEN at #${v.first_bad_seq}`}
            </Badge>
          ))}
        </div>
      </Card>
      {can(me.data, "core.audit.evidence") && (
        <Card title="Evidence pack">
          <div className="flex flex-wrap items-end gap-2">
            <Field label="From"><input type="date" className={inputCls} value={range.start} onChange={(e) => setRange({ ...range, start: e.target.value })} /></Field>
            <Field label="To"><input type="date" className={inputCls} value={range.end} onChange={(e) => setRange({ ...range, end: e.target.value })} /></Field>
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
        {(["chain", "actor", "action", "resource_id"] as const).map((k) => (
          <input key={k} aria-label={k} placeholder={k} className="rounded border px-2 py-1 text-sm" value={filters[k]} onChange={(e) => setFilters({ ...filters, [k]: e.target.value })} />
        ))}
      </div>
      <DataTable<{ id: number; seq: number; occurred_at: string; actor_name: string; action: string; resource: string; resource_id: string; reason: string | null; chain: string }>
        url="/api/audit/events"
        params={filters}
        columns={[
          { key: "seq", label: "#" },
          { key: "occurred_at", label: "When", render: (r) => dt(r.occurred_at) },
          { key: "chain", label: "Chain" },
          { key: "actor_name", label: "Actor" },
          { key: "action", label: "Action" },
          { key: "resource", label: "Resource", render: (r) => `${r.resource}:${r.resource_id}` },
          { key: "reason", label: "Reason" },
        ]}
      />
    </Page>
  );
}

type Policy = { key: string; description: string; kind: string; value: unknown; version: number; pending_request_id: number | null };

export function PolicyPage() {
  const me = useMe();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["policy"], queryFn: () => http<Policy[]>("GET", "/api/policy") });
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  return (
    <Page title="Policy (versioned; changes need a second approver)">
      <ErrorBox error={q.error} />
      <div className="overflow-x-auto rounded-lg border bg-white">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-100 text-left text-xs uppercase text-slate-600">
            <tr><th className="px-3 py-2">Key</th><th className="px-3 py-2">Value</th><th className="px-3 py-2">Version</th><th className="px-3 py-2">Change</th></tr>
          </thead>
          <tbody>
            {q.data?.map((p) => (
              <tr key={p.key} className="border-t align-top" data-testid={`policy-${p.key}`}>
                <td className="px-3 py-2"><code>{p.key}</code><div className="text-xs text-slate-500">{p.description}</div></td>
                <td className="px-3 py-2"><code>{JSON.stringify(p.value)}</code>{p.kind === "cents" && <span className="ml-1 text-xs text-slate-500">(cents)</span>}</td>
                <td className="px-3 py-2">v{p.version}</td>
                <td className="px-3 py-2">
                  {p.pending_request_id ? (
                    <Badge tone="amber">pending approval #{p.pending_request_id}</Badge>
                  ) : can(me.data, "core.policy.request") ? (
                    <ReasonAction
                      label="Request change"
                      extra={<Field label="New value (JSON)"><input className={inputCls} value={drafts[p.key] ?? JSON.stringify(p.value)} onChange={(e) => setDrafts({ ...drafts, [p.key]: e.target.value })} /></Field>}
                      onSubmit={async (reason) => {
                        await http("POST", `/api/policy/${p.key}/change-request`, { value: JSON.parse(drafts[p.key] ?? JSON.stringify(p.value)), reason });
                        qc.invalidateQueries({ queryKey: ["policy"] });
                      }}
                    />
                  ) : null}
                </td>
              </tr>
            ))}
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
            {s}: {n}
          </Button>
        ))}
      </div>
      <div className="overflow-x-auto rounded-lg border bg-white">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-100 text-left text-xs uppercase text-slate-600">
            <tr><th className="px-3 py-2">#</th><th className="px-3 py-2">Kind</th><th className="px-3 py-2">Status</th><th className="px-3 py-2">Attempts</th><th className="px-3 py-2">Last error</th><th className="px-3 py-2"></th></tr>
          </thead>
          <tbody>
            {q.data?.items.map((j) => (
              <tr key={j.id} className="border-t align-top">
                <td className="px-3 py-2">{j.id}</td>
                <td className="px-3 py-2"><code>{j.kind}</code></td>
                <td className="px-3 py-2"><Badge tone={j.status === "succeeded" ? "green" : j.status === "dead" ? "red" : "amber"}>{j.status}</Badge></td>
                <td className="px-3 py-2">{j.attempts}/{j.max_attempts}</td>
                <td className="max-w-md truncate px-3 py-2 text-xs text-slate-600">{j.last_error}</td>
                <td className="px-3 py-2">
                  {j.status === "dead" && can(me.data, "core.jobs.admin") && (
                    <ReasonAction label="Retry" onSubmit={async (reason) => { await http("POST", `/api/jobs/${j.id}/retry`, { reason }); qc.invalidateQueries({ queryKey: ["jobs"] }); }} />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Page>
  );
}

type Matrix = { roles: Record<string, string[]>; permissions: { permission: string; description: string; routes: string[] }[]; separation_of_duties: string[] };

export function AccessPage() {
  const q = useQuery({ queryKey: ["access"], queryFn: () => http<Matrix>("GET", "/api/access-matrix") });
  const roles = Object.keys(q.data?.roles ?? {});
  return (
    <Page title="Access matrix (generated from code)">
      <Card title="Separation of duties">
        <ul className="list-disc pl-5 text-sm">{q.data?.separation_of_duties.map((s) => <li key={s}>{s}</li>)}</ul>
      </Card>
      <div className="overflow-x-auto rounded-lg border bg-white">
        <table className="text-xs">
          <thead className="bg-slate-100">
            <tr>
              <th className="sticky left-0 bg-slate-100 px-2 py-1 text-left">Permission</th>
              {roles.map((r) => <th key={r} className="px-2 py-1 [writing-mode:vertical-rl]">{r}</th>)}
            </tr>
          </thead>
          <tbody>
            {q.data?.permissions.map((p) => (
              <tr key={p.permission} className="border-t">
                <td className="sticky left-0 bg-white px-2 py-1" title={p.description}><code>{p.permission}</code></td>
                {roles.map((r) => <td key={r} className="px-2 py-1 text-center">{q.data!.roles[r].includes(p.permission) ? "●" : ""}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Page>
  );
}
