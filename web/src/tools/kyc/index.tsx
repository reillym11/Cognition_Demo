import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { http } from "../../api/client";
import { can, useMe } from "../../shell/me";
import {
  ApprovalPanel, AuditTimeline, Badge, Button, Card, DataTable, ErrorBox, ExportButton, Field, KeyValues, MaskedField, Page, ReasonAction, Select, dt, type Approval, Choice, SearchBox, RecordTabs, DueCell, humanize, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow,
} from "../../ui/kit";
import type { ToolRoute } from "../registry";

type Case = {
  id: number; ref: string; applicant_name: string; email: string; dob: string; ssn: string; address: string; country: string; region: string;
  risk_level: string; vendor_score: number; watchlist_hits: number; docs_verified: boolean; status: string; requires_senior: boolean;
  assigned_name: string | null; recommendation: string | null; recommendation_code: string | null; decision: string | null; decision_code: string | null;
  decided_by: string | null; decided_at: string | null; qa_status: string | null; sla_due_at: string; sla_breached: boolean; created_at: string;
  decided_by_name?: string | null;
};

const STATUS_LABEL: Record<string, string> = {
  new: "New", in_review: "In review", info_requested: "Info requested", pending_decision: "Awaiting 2nd decision",
  approved: "Approved", rejected: "Rejected", auto_cleared: "Auto cleared",
};
const statusLabel = (s: string) => STATUS_LABEL[s] ?? humanize(s);
const DONE = new Set(["approved", "rejected", "auto_cleared"]);

const riskTone = (r: string) => (r === "high" ? "red" : r === "medium" ? "amber" : "green") as "red" | "amber" | "green";
const statusTone = (s: string) => (s === "approved" || s === "auto_cleared" ? "green" : s === "rejected" ? "red" : s === "pending_decision" ? "blue" : "slate") as "green" | "red" | "blue" | "slate";

function Queue() {
  const me = useMe();
  const nav = useNavigate();
  const [f, setF] = useState({ status: "open", risk: "", sla: "", assigned: "", q: "" });
  const stats = useQuery({ queryKey: ["kyc-stats"], queryFn: () => http<{ counts: Record<string, number>; sla_breached: number }>("GET", "/api/kyc/stats") });
  const qc = useQueryClient();
  return (
    <Page
      title="KYC review queue"
      actions={
        <>
          {can(me.data, "kyc.fastlane.run") && (
            <ReasonAction label="Run auto-clear lane" onSubmit={async (reason) => { await http("POST", "/api/kyc/fastlane/run", { reason }); qc.invalidateQueries(); }} />
          )}
          {can(me.data, "kyc.export") && <ExportButton url="/api/kyc/export" params={{ status: f.status, risk: f.risk, sla: f.sla }} />}
        </>
      }
    >
      <div className="flex flex-wrap gap-2 text-sm" data-testid="kyc-stats">
        {Object.entries(stats.data?.counts ?? {}).map(([s, n]) => <Badge key={s} tone={statusTone(s)}>{statusLabel(s)}: {n.toLocaleString()}</Badge>)}
        <Badge tone="red">SLA breached: {stats.data?.sla_breached ?? 0}</Badge>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <Select label="Status" value={f.status} onChange={(v) => setF({ ...f, status: v })} options={[["open", "Open"], ["", "All"], ["new", "New"], ["in_review", "In review"], ["info_requested", "Info requested"], ["pending_decision", "Awaiting 2nd decision"], ["approved", "Approved"], ["rejected", "Rejected"], ["auto_cleared", "Auto cleared"]]} />
        <Select label="Risk" value={f.risk} onChange={(v) => setF({ ...f, risk: v })} options={[["", "Any risk"], ["low", "Low"], ["medium", "Medium"], ["high", "High"]]} />
        <Select label="SLA" value={f.sla} onChange={(v) => setF({ ...f, sla: v })} options={[["", "Any SLA"], ["breached", "Breached"]]} />
        <Select label="Assigned" value={f.assigned} onChange={(v) => setF({ ...f, assigned: v })} options={[["", "Anyone"], ["me", "Mine"], ["unassigned", "Unassigned"]]} />
        <SearchBox label="Search reference" placeholder="KYC-000123" value={f.q} onChange={(v) => setF({ ...f, q: v })} />
      </div>
      <DataTable<Case>
        url="/api/kyc/cases"
        params={f}
        rowTestId="kyc-row"
        onRowClick={(r) => nav(`/kyc/cases/${r.id}`)}
        columns={[
          { key: "ref", label: "Reference", sortable: true },
          { key: "applicant_name", label: "Applicant (masked)" },
          { key: "region", label: "Region" },
          { key: "risk_level", label: "Risk", sortable: true, render: (r) => <Badge tone={riskTone(r.risk_level)}>{humanize(r.risk_level)}{r.requires_senior ? " · Senior" : ""}</Badge> },
          { key: "vendor_score", label: "Vendor score", sortable: true },
          { key: "status", label: "Status", render: (r) => <Badge tone={statusTone(r.status)}>{statusLabel(r.status)}</Badge> },
          { key: "assigned_name", label: "Assigned", render: (r) => r.assigned_name ?? "---" },
          { key: "sla_due_at", label: "SLA due", sortable: true, render: (r) => <DueCell iso={r.sla_due_at} breached={r.sla_breached} done={DONE.has(r.status)} /> },
        ]}
      />
    </Page>
  );
}

type Detail = { case: Case; approval: Approval | null; can: { claim: boolean; work: boolean; reveal: boolean }; reason_codes: { approve: string[]; reject: string[] } };

function CaseDetail() {
  const { id } = useParams();
  const qc = useQueryClient();
  const key = ["kyc-case", id!];
  const q = useQuery({ queryKey: key, queryFn: () => http<Detail>("GET", `/api/kyc/cases/${id}`) });
  const [err, setErr] = useState<unknown>(null);
  const [rec, setRec] = useState({ decision: "approve", code: "" });
  const refresh = () => {
    qc.invalidateQueries({ queryKey: key });
    qc.invalidateQueries({ queryKey: [`/api/kyc/cases/${id}/audit`] });
  };
  const act = (path: string, body?: unknown) => async () => {
    setErr(null);
    try {
      await http("POST", `/api/kyc/cases/${id}/${path}`, body ?? {});
      refresh();
    } catch (e) {
      setErr(e);
    }
  };
  if (!q.data) return <ErrorBox error={q.error} />;
  const c = q.data.case;
  const codes = rec.decision === "approve" ? q.data.reason_codes.approve : q.data.reason_codes.reject;
  const reveal = (field: keyof Case) => <MaskedField field={field} value={String(c[field])} revealUrl={`/api/kyc/cases/${id}/reveal`} canReveal={q.data.can.reveal} />;
  return (
    <Page subtitle="KYC case" title={`Case ${c.ref}`} status={<Badge tone={statusTone(c.status)}>{statusLabel(c.status)}</Badge>}>
      <RecordTabs tabs={[{ key: "summary", label: "Summary", content: <>
      <ErrorBox error={err} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Applicant (PII masked; reveals are audited)">
          <KeyValues rows={[["Name", reveal("applicant_name")], ["Email", reveal("email")], ["Date of birth", reveal("dob")], ["SSN", reveal("ssn")], ["Address", reveal("address")], ["Country / region", `${c.country} / ${c.region}`]]} />
        </Card>
        <Card title="Risk">
          <KeyValues rows={[
            ["Risk level", <Badge tone={riskTone(c.risk_level)}>{humanize(c.risk_level)}</Badge>],
            ["Vendor score", c.vendor_score], ["Watchlist hits", c.watchlist_hits], ["Documents verified", c.docs_verified ? "Yes" : "No"],
            ["Senior review", c.requires_senior ? "Required" : "Not required"], ["SLA due", <DueCell iso={c.sla_due_at} breached={c.sla_breached} done={DONE.has(c.status)} />],
            ["Assigned", c.assigned_name ?? "---"],
            ["Recommendation", c.recommendation ? `${humanize(c.recommendation)} · ${humanize(c.recommendation_code)}` : "---"],
            ["Decision", c.decision_code ? `${c.decision === "approve" ? "Approved" : "Rejected"} · ${humanize(c.decision_code)}${c.decided_by_name ? ` · by ${c.decided_by_name}` : ""} · ${dt(c.decided_at)}` : "---"],
            ...(c.qa_status ? [["QA review", humanize(c.qa_status)] as [string, string]] : []),
          ]} />
        </Card>
      </div>
      <Card title="Actions">
        <div className="flex flex-wrap gap-2">
          {q.data.can.claim && <Button variant="primary" data-testid="claim" onClick={act("claim")}>Claim</Button>}
          {q.data.can.work && c.status === "in_review" && (
            <ReasonAction
              label="Recommend"
              variant="primary"
              testId="recommend"
              extra={
                <div className="flex gap-2">
                  <Field label="Recommendation">
                    <Choice  aria-label="Recommendation" value={rec.decision} onChange={(e) => setRec({ decision: e.target.value, code: "" })}>
                      <option value="approve">Approve</option>
                      <option value="reject">Reject</option>
                    </Choice>
                  </Field>
                  <Field label="Reason code">
                    <Choice  aria-label="Reason code" value={rec.code} onChange={(e) => setRec({ ...rec, code: e.target.value })}>
                      <option value="">Choose…</option>
                      {codes.map((k) => <option key={k} value={k}>{humanize(k)}</option>)}
                    </Choice>
                  </Field>
                </div>
              }
              onSubmit={async (reason) => { await http("POST", `/api/kyc/cases/${id}/recommend`, { decision: rec.decision, reason_code: rec.code, reason }); refresh(); }}
            />
          )}
          {q.data.can.work && c.status === "in_review" && <ReasonAction label="Request info" onSubmit={async (reason) => { await http("POST", `/api/kyc/cases/${id}/request-info`, { reason }); refresh(); }} />}
          {q.data.can.work && c.status === "info_requested" && <ReasonAction label="Info received" onSubmit={async (reason) => { await http("POST", `/api/kyc/cases/${id}/info-received`, { reason }); refresh(); }} />}
          {q.data.can.work && <ReasonAction label="Escalate to senior" onSubmit={async (reason) => { await http("POST", `/api/kyc/cases/${id}/escalate`, { reason }); refresh(); }} />}
          {q.data.can.work && <ReasonAction label="Release" onSubmit={async (reason) => { await http("POST", `/api/kyc/cases/${id}/release`, { reason }); refresh(); }} />}
        </div>
      </Card>
      {q.data.approval && <Card title="Second-person decision"><ApprovalPanel approval={q.data.approval} invalidate={[key, ["kyc-stats"]]} /></Card>}
      </> }, { key: "audit", label: "Audit history", content: <Card title="Audit trail"><AuditTimeline url={`/api/kyc/cases/${id}/audit`} /></Card> }]} />
    </Page>
  );
}

type Check = { label: string; required: string; actual: string; met: boolean };
type QaCase = Case & { fastlane: { criteria_version: number; checks: Check[] } };

function QaQueue() {
  const qc = useQueryClient();
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["kyc-qa"], queryFn: () => http<QaCase[]>("GET", "/api/kyc/qa") });
  const [sel, setSel] = useState<number | null>(null);
  const review = (id: number, result: string) => async (reason: string) => {
    await http("POST", `/api/kyc/cases/${id}/qa`, { result, reason });
    setSel(null);
    qc.invalidateQueries({ queryKey: ["kyc-qa"] });
  };
  const items = q.data ?? [];
  const c = items.find((x) => x.id === sel) ?? items[0];
  return (
    <Page title="Auto-clear QA sample" subtitle="KYC review">
      <p className="text-sm text-slate-600">
        A random sample of cases cleared automatically by the fast lane. Check each one against the criteria it was judged on.
        Pass confirms the clearance; Fail re-opens the case for a senior reviewer.
      </p>
      <ErrorBox error={q.error} />
      {q.data && items.length === 0 && <Card><p className="text-sm text-slate-600">Nothing to review. New samples appear after the next auto-clear run.</p></Card>}
      {c && (
        <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
          <Card title={`To review (${items.length})`}>
            <ul className="-mx-2 divide-y divide-slate-100" data-testid="qa-list">
              {items.map((x) => (
                <li key={x.id}>
                  <button
                    type="button"
                    onClick={() => setSel(x.id)}
                    className={`flex w-full items-center justify-between gap-2 rounded px-2 py-2 text-left text-sm ${x.id === c.id ? "bg-blue-50 font-semibold text-blue-900" : "hover:bg-slate-50"}`}
                  >
                    <span>
                      <span className="block">{x.ref}</span>
                      <span className="block text-xs font-normal text-slate-500">Cleared {dt(x.decided_at)}</span>
                    </span>
                    <Badge tone={x.fastlane.checks.every((k) => k.met) ? "green" : "red"}>
                      {x.fastlane.checks.every((k) => k.met) ? "Criteria met" : "Check"}
                    </Badge>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
          <div className="space-y-4" data-testid="qa-case">
            <Card title={`Case ${c.ref}`}>
              <div className="grid gap-4 md:grid-cols-2">
                <KeyValues rows={[
                  ["Risk level", <Badge tone={riskTone(c.risk_level)}>{humanize(c.risk_level)}</Badge>],
                  ["Vendor score", c.vendor_score],
                  ["Watchlist hits", c.watchlist_hits],
                  ["Documents verified", c.docs_verified ? "Yes" : "No"],
                ]} />
                <KeyValues rows={[
                  ["Country / region", `${c.country} / ${c.region}`],
                  ["Received", dt(c.created_at)],
                  ["Auto cleared", dt(c.decided_at)],
                  ["Criteria version", c.fastlane.criteria_version ? `Version ${c.fastlane.criteria_version}` : "Default"],
                ]} />
              </div>
            </Card>
            <Card title="Why it qualified">
              <Table size="small" className="min-w-full text-sm">
                <TableHeader><TableRow><TableHeaderCell>Criterion</TableHeaderCell><TableHeaderCell>Required</TableHeaderCell><TableHeaderCell>This case</TableHeaderCell><TableHeaderCell>Result</TableHeaderCell></TableRow></TableHeader>
                <TableBody>
                  {c.fastlane.checks.map((k) => (
                    <TableRow key={k.label}>
                      <TableCell>{k.label}</TableCell>
                      <TableCell>{k.required}</TableCell>
                      <TableCell className="font-semibold">{k.actual}</TableCell>
                      <TableCell><Badge tone={k.met ? "green" : "red"}>{k.met ? "Meets" : "Does not meet"}</Badge></TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <p className="mt-2 text-xs text-slate-500">
                {c.fastlane.checks.every((k) => k.met)
                  ? "Every fast-lane criterion was met when the case was cleared."
                  : "At least one fact no longer meets the criteria; consider failing this case."}
              </p>
            </Card>
            <Card title="QA decision">
              <div className="flex flex-wrap items-center gap-2">
                <ReasonAction label="Pass" variant="primary" onSubmit={review(c.id, "passed")} />
                <ReasonAction label="Fail and re-open" variant="danger" onSubmit={review(c.id, "failed")} />
                <Button onClick={() => nav(`/kyc/cases/${c.id}`)}>Open full case</Button>
              </div>
            </Card>
          </div>
        </div>
      )}
    </Page>
  );
}

export const routes: ToolRoute[] = [
  { path: "/kyc", element: <Queue /> },
  { path: "/kyc/cases/:id", element: <CaseDetail /> },
  { path: "/kyc/qa", element: <QaQueue /> },
];
