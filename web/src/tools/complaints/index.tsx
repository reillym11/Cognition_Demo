import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { http } from "../../api/client";
import { can, useMe } from "../../shell/me";
import {
  AuditTimeline, Badge, Button, Card, DataTable, ErrorBox, ExportButton, Field, KeyValues, MaskedField, Page, ReasonAction, Select, StageBar, dt, Input, Textarea, Choice, Checkbox, SearchBox, RecordTabs, humanize, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow,
} from "../../ui/kit";
import type { HomeWidget, ToolRoute } from "../registry";

type PathStage = { key: string; label: string; sla_hours: number; required: string[]; checklist: string[] };
type Complaint = {
  id: number; ref: string; customer_name: string; customer_email: string; channel: string; description: string;
  product: string | null; summary: string | null; category: string | null; regulatory: boolean; unfair_treatment: boolean;
  root_cause: string | null; compliance_notes: string | null; resolution: string | null; response_text: string | null;
  stage: string; stage_label: string; status: string; stage_due_at: string | null; overdue: boolean; assigned_name: string | null;
  checks: Record<string, boolean>; related: { kind: string; id: number }[]; received_at: string; age_days: number; path: PathStage[];
  can?: { work: boolean; claim: boolean; compliance: boolean; reveal: boolean };
};
type Meta = { categories: string[]; products: string[]; root_causes: Record<string, string[]>; stages: { key: string; label: string }[] };
const useMeta = () => useQuery({ queryKey: ["complaints-meta"], queryFn: () => http<Meta>("GET", "/api/complaints/meta"), staleTime: Infinity });

function Queue() {
  const nav = useNavigate();
  const me = useMe();
  const meta = useMeta();
  const [f, setF] = useState({ status: "open", stage: "", regulatory: "", overdue: "", mine: "", q: "" });
  const set = (k: keyof typeof f) => (v: string) => setF({ ...f, [k]: v });
  return (
    <Page title="Complaints" actions={can(me.data, "complaints.export") && <ExportButton url="/api/complaints/register.csv" params={{ status: f.status, regulatory: f.regulatory }} />}>
      <div className="flex flex-wrap items-end gap-3">
        <Select label="Status" value={f.status} onChange={set("status")} options={[["open", "Open"], ["closed", "Closed"], ["", "All"]]} />
        <Select label="Stage" value={f.stage} onChange={set("stage")} options={[["", "Any stage"], ...(meta.data?.stages.map((s) => [s.key, s.label] as [string, string]) ?? [])]} />
        <Select label="Regulatory" value={f.regulatory} onChange={set("regulatory")} options={[["", "All"], ["1", "Regulatory / unfair treatment"]]} />
        <Select label="Overdue" value={f.overdue} onChange={set("overdue")} options={[["", "Any SLA"], ["1", "Stage overdue"]]} />
        <Select label="Mine" value={f.mine} onChange={set("mine")} options={[["", "Anyone"], ["1", "Assigned to me"]]} />
        <SearchBox label="Search complaints" placeholder="ref or summary" value={f.q} onChange={(v) => set("q")(v)} />
      </div>
      <DataTable<Complaint>
        url="/api/complaints"
        params={f}
        rowTestId="complaint-row"
        onRowClick={(r) => nav(`/complaints/${r.id}`)}
        columns={[
          { key: "ref", label: "Reference", sortable: true },
          { key: "received_at", label: "Received", sortable: true, render: (r) => dt(r.received_at) },
          { key: "summary", label: "Summary", render: (r) => r.summary ?? <span className="text-slate-400">Not triaged</span> },
          { key: "stage", label: "Stage", render: (r) => <>{r.stage_label} {(r.regulatory || r.unfair_treatment) && <Badge tone="amber">Regulatory</Badge>}</> },
          { key: "stage_due_at", label: "Stage due", sortable: true, render: (r) => (r.stage_due_at ? <Badge tone={r.overdue ? "red" : "slate"}>{dt(r.stage_due_at)}</Badge> : "---") },
          { key: "assigned_name", label: "Assigned", render: (r) => r.assigned_name ?? "---" },
          { key: "age_days", label: "Age (days)" },
        ]}
      />
    </Page>
  );
}

const FIELD_LABELS: Record<string, string> = {
  product: "Product", summary: "Summary", category: "Category", root_cause: "Root cause", resolution: "Resolution",
  compliance_notes: "Compliance notes", response_text: "Customer response",
};

function StageForm({ c, meta, onSaved }: { c: Complaint; meta: Meta; onSaved: () => void }) {
  const stage = c.path.find((s) => s.key === c.stage)!;
  const [vals, setVals] = useState<Record<string, string | boolean>>(() => Object.fromEntries(stage.required.map((k) => [k, (c as unknown as Record<string, string>)[k] ?? ""])));
  const [checks, setChecks] = useState<Record<string, boolean>>(c.checks);
  const [regs, setRegs] = useState({ regulatory: c.regulatory, unfair_treatment: c.unfair_treatment });
  const [err, setErr] = useState<unknown>(null);
  const save = useMutation({
    mutationFn: (reason?: string) =>
      http("PATCH", `/api/complaints/${c.id}`, {
        fields: { ...vals, ...(c.stage === "classify" ? regs : {}) },
        checks: Object.fromEntries(stage.checklist.map((k) => [k, !!checks[k]])),
        reason,
      }),
    onSuccess: () => { setErr(null); onSaved(); },
    onError: setErr,
  });
  const input = (k: string) => {
    const v = String(vals[k] ?? "");
    const on = (x: string) => setVals({ ...vals, [k]: x });
    if (k === "product" || k === "category") {
      const opts = k === "product" ? meta.products : meta.categories;
      return <Choice aria-label={FIELD_LABELS[k]} value={v} onChange={(e) => on(e.target.value)}><option value="">choose…</option>{opts.map((o) => <option key={o}>{o}</option>)}</Choice>;
    }
    if (k === "root_cause")
      return (
        <Choice aria-label="Root cause" value={v} onChange={(e) => on(e.target.value)}>
          <option value="">choose…</option>
          {Object.entries(meta.root_causes).map(([g, rcs]) => <optgroup key={g} label={g}>{rcs.map((r) => <option key={r}>{r}</option>)}</optgroup>)}
        </Choice>
      );
    return k === "summary" ? <Input aria-label={FIELD_LABELS[k]} value={v} onChange={(e) => on(e.target.value)} /> : <Textarea aria-label={FIELD_LABELS[k]} rows={3} value={v} onChange={(e) => on(e.target.value)} />;
  };
  return (
    <Card title={`Stage: ${stage.label} (SLA ${stage.sla_hours} h)`}>
      <div className="space-y-2">
        {stage.required.map((k) => <Field key={k} label={`${FIELD_LABELS[k] ?? humanize(k)} *`}>{input(k)}</Field>)}
        {c.stage === "classify" && (
          <div className="flex gap-4 text-sm">
            <Checkbox checked={regs.regulatory} onChange={(e) => setRegs({ ...regs, regulatory: e.target.checked })} label={<>Regulatory</>} />
            <Checkbox checked={regs.unfair_treatment} onChange={(e) => setRegs({ ...regs, unfair_treatment: e.target.checked })} label={<>Possible unfair treatment</>} />
            <span className="text-xs text-slate-500">Either tag adds a compliance-review stage.</span>
          </div>
        )}
        {stage.checklist.map((k) => (
          <Checkbox checked={!!checks[k]} onChange={(e) => setChecks({ ...checks, [k]: e.target.checked })} label={<>{humanize(k)}</>} />
        ))}
        <ErrorBox error={err} />
        <div className="flex gap-2">
          {c.stage === "compliance_review" ? (
            <ReasonAction label="Save notes" onSubmit={async (r) => { await save.mutateAsync(r); }} />
          ) : (
            <Button onClick={() => save.mutate(undefined)} disabled={save.isPending}>Save</Button>
          )}
          <ReasonAction
            label="Complete stage"
            variant="primary"
            testId="complete-stage"
            onSubmit={async (reason) => { await save.mutateAsync(reason).catch(() => undefined); await http("POST", `/api/complaints/${c.id}/advance`, { reason }); onSaved(); }}
          />
        </div>
      </div>
    </Card>
  );
}

function Detail() {
  const { id } = useParams();
  const qc = useQueryClient();
  const meta = useMeta();
  const qk = ["complaint", id!];
  const q = useQuery({ queryKey: qk, queryFn: () => http<Complaint>("GET", `/api/complaints/${id}`) });
  const refresh = () => qc.invalidateQueries({ queryKey: qk });
  const [link, setLink] = useState({ kind: "refund", id: "" });
  if (!q.data || !meta.data) return <ErrorBox error={q.error ?? meta.error} />;
  const c = q.data;
  const reveal = (field: "customer_name" | "customer_email") => <MaskedField field={field} value={c[field]} revealUrl={`/api/complaints/${c.id}/reveal`} canReveal={!!c.can?.reveal} />;
  return (
    <Page subtitle="Complaint" title={`${c.ref} · ${c.summary ?? "Untriaged"}`} actions={c.can?.claim && <Button onClick={async () => { await http("POST", `/api/complaints/${c.id}/claim`); refresh(); }}>Claim</Button>}>
      {c.status === "open" ? <StageBar stages={c.path} current={c.stage} /> : <Badge tone="green">Closed</Badge>}
      <RecordTabs tabs={[{ key: "summary", label: "Summary", content: <>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Complaint">
          <KeyValues rows={[
            ["Customer", reveal("customer_name")], ["Email", reveal("customer_email")], ["Channel", humanize(c.channel)], ["Received", dt(c.received_at)],
            ["Stage due", c.stage_due_at ? <Badge tone={c.overdue ? "red" : "slate"}>{dt(c.stage_due_at)}</Badge> : "---"],
            ["Assigned", c.assigned_name ?? "---"], ["Product", c.product ?? "---"], ["Category", c.category ?? "---"],
            ["Tags", <>{c.regulatory && <Badge tone="amber">Regulatory</Badge>} {c.unfair_treatment && <Badge tone="amber">Unfair treatment</Badge>}</>],
            ["Root cause", c.root_cause ?? "---"], ["Resolution", c.resolution ?? "---"], ["Compliance notes", c.compliance_notes ?? "---"],
            ["Description", c.description],
          ]} />
        </Card>
        <div className="space-y-4">
          {(c.can?.work || c.can?.compliance) && <StageForm key={c.stage} c={c} meta={meta.data} onSaved={refresh} />}
          <Card title="Related cases">
            <ul className="text-sm">{c.related.map((r) => <li key={`${r.kind}${r.id}`}><a className="text-blue-700 underline" href={r.kind === "kyc" ? `/kyc/cases/${r.id}` : `/refunds/requests/${r.id}`}>{r.kind === "kyc" ? "KYC case" : "Refund"} {r.id}</a></li>)}</ul>
            {c.related.length === 0 && <p className="text-sm text-slate-500">No linked cases.</p>}
            {c.can?.work && (
              <ReasonAction label="Link case" extra={
                <div className="flex gap-2">
                  <Choice aria-label="Link kind" value={link.kind} onChange={(e) => setLink({ ...link, kind: e.target.value })}><option value="refund">Refund</option><option value="kyc">KYC case</option></Choice>
                  <Input aria-label="Link id" value={link.id} onChange={(e) => setLink({ ...link, id: e.target.value })} placeholder="Record ID" />
                </div>
              } onSubmit={async (reason) => { await http("POST", `/api/complaints/${c.id}/links`, { kind: link.kind, id: Number(link.id), reason }); refresh(); }} />
            )}
          </Card>
        </div>
      </div>
      </> }, { key: "audit", label: "Audit history", content: <Card title="Audit trail"><AuditTimeline url={`/api/complaints/${c.id}/audit`} /></Card> }]} />
    </Page>
  );
}

function Aging() {
  const q = useQuery({ queryKey: ["complaints-aging"], queryFn: () => http<{ buckets: { bucket: string; count: number }[]; stages: { stage: string; label: string; open: number; overdue: number }[]; open: number; closed_last_30d: number; regulatory_open: number }>("GET", "/api/complaints/aging") });
  if (!q.data) return <ErrorBox error={q.error} />;
  const max = Math.max(1, ...q.data.buckets.map((b) => b.count));
  return (
    <section className="space-y-3" data-testid="complaint-aging" aria-label="Complaint aging">
      <div className="grid gap-4 sm:grid-cols-3">
        <Card title="Open"><p className="text-2xl font-semibold">{q.data.open}</p></Card>
        <Card title="Regulatory open"><p className="text-2xl font-semibold">{q.data.regulatory_open}</p></Card>
        <Card title="Closed (30 days)"><p className="text-2xl font-semibold">{q.data.closed_last_30d}</p></Card>
      </div>
      <Card title="Open complaints by age (days since received)">
        <div className="space-y-1">
          {q.data.buckets.map((b) => (
            <div key={b.bucket} className="flex items-center gap-2 text-sm">
              <span className="w-14">{b.bucket}</span>
              <div className="h-4 rounded bg-blue-600" style={{ width: `${(b.count / max) * 70}%` }} aria-hidden />
              <span>{b.count}</span>
            </div>
          ))}
        </div>
      </Card>
      <Card title="By stage">
        <Table size="small" className="min-w-full text-sm"><TableHeader className="text-left text-xs uppercase text-slate-500"><TableRow><TableHeaderCell>Stage</TableHeaderCell><TableHeaderCell>Open</TableHeaderCell><TableHeaderCell>Overdue</TableHeaderCell></TableRow></TableHeader>
          <TableBody>{q.data.stages.map((s) => <TableRow key={s.stage} className="border-t"><TableCell className="py-1">{s.label}</TableCell><TableCell>{s.open}</TableCell><TableCell className={s.overdue ? "font-semibold text-red-700" : ""}>{s.overdue}</TableCell></TableRow>)}</TableBody>
        </Table>
      </Card>
    </section>
  );
}

export const homeWidgets: HomeWidget[] = [{ below: "/complaints", element: <Aging /> }];

export const routes: ToolRoute[] = [
  { path: "/complaints", element: <Queue /> },
  { path: "/complaints/:id", element: <Detail /> },
];
