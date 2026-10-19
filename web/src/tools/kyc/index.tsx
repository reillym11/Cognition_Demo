import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { http } from "../../api/client";
import { can, useMe } from "../../shell/me";
import {
  ApprovalPanel, AuditTimeline, Badge, Button, Card, DataTable, ErrorBox, ExportButton, Field, KeyValues, MaskedField, Page, ReasonAction, Select, dt, type Approval, Choice, SearchBox, RecordTabs,
} from "../../ui/kit";
import type { ToolRoute } from "../registry";

type Case = {
  id: number; ref: string; applicant_name: string; email: string; dob: string; ssn: string; address: string; country: string; region: string;
  risk_level: string; vendor_score: number; watchlist_hits: number; docs_verified: boolean; status: string; requires_senior: boolean;
  assigned_name: string | null; recommendation: string | null; recommendation_code: string | null; decision: string | null; decision_code: string | null;
  decided_by: string | null; decided_at: string | null; qa_status: string | null; sla_due_at: string; sla_breached: boolean; created_at: string;
};

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
        {Object.entries(stats.data?.counts ?? {}).map(([s, n]) => <Badge key={s} tone={statusTone(s)}>{s}: {n.toLocaleString()}</Badge>)}
        <Badge tone="red">SLA breached: {stats.data?.sla_breached ?? 0}</Badge>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <Select label="Status" value={f.status} onChange={(v) => setF({ ...f, status: v })} options={[["open", "Open"], ["", "All"], ["new", "New"], ["in_review", "In review"], ["info_requested", "Info requested"], ["pending_decision", "Awaiting 2nd decision"], ["approved", "Approved"], ["rejected", "Rejected"], ["auto_cleared", "Auto-cleared"]]} />
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
          { key: "ref", label: "Ref", sortable: true },
          { key: "applicant_name", label: "Applicant (masked)" },
          { key: "region", label: "Region" },
          { key: "risk_level", label: "Risk", sortable: true, render: (r) => <Badge tone={riskTone(r.risk_level)}>{r.risk_level}{r.requires_senior ? " · senior" : ""}</Badge> },
          { key: "vendor_score", label: "Vendor score", sortable: true },
          { key: "status", label: "Status", render: (r) => <Badge tone={statusTone(r.status)}>{r.status}</Badge> },
          { key: "assigned_name", label: "Assigned" },
          { key: "sla_due_at", label: "SLA due", sortable: true, render: (r) => <span className={r.sla_breached ? "font-semibold text-red-700" : ""}>{dt(r.sla_due_at)}{r.sla_breached ? " (breached)" : ""}</span> },
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
    <Page subtitle="KYC case" title={`Case ${c.ref}`} status={<Badge tone={statusTone(c.status)}>{c.status}</Badge>}>
      <RecordTabs tabs={[{ key: "summary", label: "Summary", content: <>
      <ErrorBox error={err} />
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Applicant (PII masked; reveals are audited)">
          <KeyValues rows={[["Name", reveal("applicant_name")], ["Email", reveal("email")], ["Date of birth", reveal("dob")], ["SSN", reveal("ssn")], ["Address", reveal("address")], ["Country / region", `${c.country} / ${c.region}`]]} />
        </Card>
        <Card title="Risk">
          <KeyValues rows={[
            ["Risk level", <Badge tone={riskTone(c.risk_level)}>{c.risk_level}</Badge>],
            ["Vendor score", c.vendor_score], ["Watchlist hits", c.watchlist_hits], ["Documents verified", c.docs_verified ? "yes" : "no"],
            ["Senior review", c.requires_senior ? "required" : "no"], ["SLA due", <span className={c.sla_breached ? "text-red-700" : ""}>{dt(c.sla_due_at)}</span>],
            ["Assigned", c.assigned_name ?? "---"], ["Decision", c.decision_code ? `${c.decision} (${c.decision_code}) by ${c.decided_by}` : "---"],
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
                      {codes.map((k) => <option key={k}>{k}</option>)}
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

function QaQueue() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["kyc-qa"], queryFn: () => http<Case[]>("GET", "/api/kyc/qa") });
  const review = (id: number, result: string) => async (reason: string) => {
    await http("POST", `/api/kyc/cases/${id}/qa`, { result, reason });
    qc.invalidateQueries({ queryKey: ["kyc-qa"] });
  };
  return (
    <Page title="Auto-clear QA sample">
      <p className="text-sm text-slate-600">A random share (policy <code>kyc.qa_sample_rate</code>) of cases cleared by <code>system:kyc-fastlane</code> lands here. Failing one re-opens it for a senior reviewer.</p>
      <ErrorBox error={q.error} />
      {q.data?.length === 0 && <p className="text-sm">Nothing to review.</p>}
      <div className="space-y-2">
        {q.data?.map((c) => (
          <Card key={c.id}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-sm"><strong>{c.ref}</strong> · score {c.vendor_score} · cleared {dt(c.decided_at)}</span>
              <span className="flex gap-2">
                <ReasonAction label="Pass" variant="primary" onSubmit={review(c.id, "passed")} />
                <ReasonAction label="Fail" variant="danger" onSubmit={review(c.id, "failed")} />
              </span>
            </div>
          </Card>
        ))}
      </div>
    </Page>
  );
}

export const routes: ToolRoute[] = [
  { path: "/kyc", element: <Queue /> },
  { path: "/kyc/cases/:id", element: <CaseDetail /> },
  { path: "/kyc/qa", element: <QaQueue /> },
];
