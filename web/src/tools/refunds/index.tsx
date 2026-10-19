import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { http } from "../../api/client";
import { can, useMe } from "../../shell/me";
import {
  ApprovalPanel, AuditTimeline, Badge, Card, DataTable, ErrorBox, ExportButton, Field, KeyValues, MaskedField, Page, ReasonAction, Select, dt, type Approval, Input, Choice, SearchBox, RecordTabs, Table, TableBody, TableCell, TableRow,
} from "../../ui/kit";
import type { ToolRoute } from "../registry";

type Txn = {
  id: number; charge_id: string; merchant: string; region: string; customer_name: string; customer_email: string; card_last4: string;
  amount_cents: number; amount: string; captured_at: string; reserved_cents?: number; remaining_cents?: number;
};
type Refund = {
  id: number; transaction_id: number; charge_id?: string; merchant?: string; amount: string; amount_cents: number; status: string;
  reason_code: string; reason: string; requested_by_name: string; processor_ref: string | null; needs_approval: boolean;
  approval_why: string | null; velocity_flag: boolean; attempts: number; last_error: string | null; created_at: string; executed_at: string | null;
};

const usd = (c: number) => `$${(c / 100).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
const tone = (s: string) =>
  (s === "succeeded" ? "green" : s === "failed" || s === "rejected" ? "red" : s === "unknown" ? "amber" : "blue") as "green" | "red" | "amber" | "blue";

function Transactions() {
  const nav = useNavigate();
  const [q, setQ] = useState("");
  return (
    <Page title="Transactions">
      <SearchBox label="Search charge or merchant" placeholder="ch_000123 or merchant" value={q} onChange={(v) => setQ(v)} />
      <DataTable<Txn>
        url="/api/refunds/transactions"
        params={{ q }}
        rowTestId="txn-row"
        onRowClick={(r) => nav(`/refunds/transactions/${r.id}`)}
        columns={[
          { key: "charge_id", label: "Charge", sortable: true },
          { key: "merchant", label: "Merchant" },
          { key: "region", label: "Region" },
          { key: "customer_email", label: "Customer (masked)" },
          { key: "amount_cents", label: "Captured", sortable: true, render: (r) => r.amount },
          { key: "captured_at", label: "Captured at", sortable: true, render: (r) => dt(r.captured_at) },
        ]}
      />
    </Page>
  );
}

function TransactionDetail() {
  const { id } = useParams();
  const me = useMe();
  const nav = useNavigate();
  const qc = useQueryClient();
  const key = ["refund-txn", id!];
  const q = useQuery({ queryKey: key, queryFn: () => http<{ transaction: Txn; refunds: Refund[]; reason_codes: string[]; can_reveal: boolean }>("GET", `/api/refunds/transactions/${id}`) });
  const [form, setForm] = useState({ amount: "", code: "" });
  if (!q.data) return <ErrorBox error={q.error} />;
  const t = q.data.transaction;
  return (
    <Page subtitle="Transaction" title={`Charge ${t.charge_id}`}>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Transaction">
          <KeyValues rows={[
            ["Merchant", t.merchant],
            ["Region", t.region],
            ["Customer", <MaskedField field="customer_name" value={t.customer_name} revealUrl={`/api/refunds/transactions/${id}/reveal`} canReveal={q.data.can_reveal} />],
            ["Email", <MaskedField field="customer_email" value={t.customer_email} revealUrl={`/api/refunds/transactions/${id}/reveal`} canReveal={q.data.can_reveal} />],
            ["Card", `•••• ${t.card_last4}`], ["Captured", t.amount], ["Reserved by refunds", usd(t.reserved_cents ?? 0)],
            ["Refundable balance", <strong data-testid="remaining">{usd(t.remaining_cents ?? 0)}</strong>],
          ]} />
        </Card>
        {can(me.data, "refunds.request") && (
          <Card title="Request a refund">
            <ReasonAction
              label="Request refund"
              variant="primary"
              testId="request-refund"
              extra={
                <div className="flex gap-2">
                  <Field label="Amount (USD)">
                    <Input  aria-label="Amount (USD)" inputMode="decimal" value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} />
                  </Field>
                  <Field label="Reason code">
                    <Choice  aria-label="Reason code" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })}>
                      <option value="">Choose…</option>
                      {q.data.reason_codes.map((c) => <option key={c}>{c}</option>)}
                    </Choice>
                  </Field>
                </div>
              }
              onSubmit={async (reason) => {
                const cents = Math.round(Number(form.amount) * 100);
                const r = await http<{ id: number }>("POST", `/api/refunds/transactions/${id}/refunds`, { amount_cents: cents, reason_code: form.code, reason });
                qc.invalidateQueries();
                nav(`/refunds/requests/${r.id}`);
              }}
            />
          </Card>
        )}
      </div>
      <Card title="Refunds on this charge">
        <Table size="small" className="min-w-full text-sm">
          <TableBody>
            {q.data.refunds.map((r) => (
              <TableRow key={r.id} className="cursor-pointer border-t hover:bg-blue-50" onClick={() => nav(`/refunds/requests/${r.id}`)}>
                <TableCell className="px-2 py-1">#{r.id}</TableCell><TableCell>{r.amount}</TableCell><TableCell><Badge tone={tone(r.status)}>{r.status}</Badge></TableCell><TableCell>{r.requested_by_name}</TableCell><TableCell>{dt(r.created_at)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
        {q.data.refunds.length === 0 && <p className="text-sm text-slate-500">None yet.</p>}
      </Card>
    </Page>
  );
}

function Requests() {
  const me = useMe();
  const nav = useNavigate();
  const [f, setF] = useState({ status: "", mine: "" });
  const stats = useQuery({ queryKey: ["refund-stats"], queryFn: () => http<Record<string, { count: number; total: string }>>("GET", "/api/refunds/stats") });
  return (
    <Page title="Refund requests" actions={can(me.data, "refunds.export") && <ExportButton url="/api/refunds/export" params={f} />}>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-6" data-testid="refund-totals">
        {["pending_approval", "approved", "unknown", "succeeded", "failed", "rejected"].map((s) => (
          <Card key={s}><div className="text-xs uppercase text-slate-500">{s}</div><div className="text-lg font-semibold">{stats.data?.[s]?.total ?? "$0.00"}</div><div className="text-xs">{stats.data?.[s]?.count ?? 0} refunds</div></Card>
        ))}
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <Select label="Status" value={f.status} onChange={(v) => setF({ ...f, status: v })} options={[["", "All"], ["pending_approval", "Pending approval"], ["approved", "Approved (executing)"], ["unknown", "Unknown outcome"], ["succeeded", "Succeeded"], ["failed", "Failed"], ["rejected", "Rejected"]]} />
        <Select label="Requester" value={f.mine} onChange={(v) => setF({ ...f, mine: v })} options={[["", "Anyone"], ["1", "Mine"]]} />
      </div>
      <DataTable<Refund>
        url="/api/refunds/requests"
        params={f}
        rowTestId="refund-row"
        onRowClick={(r) => nav(`/refunds/requests/${r.id}`)}
        columns={[
          { key: "id", label: "#", sortable: true },
          { key: "charge_id", label: "Charge" },
          { key: "amount_cents", label: "Amount", sortable: true, render: (r) => r.amount },
          { key: "status", label: "Status", render: (r) => <Badge tone={tone(r.status)}>{r.status}</Badge> },
          { key: "velocity_flag", label: "Flags", render: (r) => (r.velocity_flag ? <Badge tone="amber">velocity</Badge> : r.needs_approval ? <Badge>2nd person</Badge> : "—") },
          { key: "requested_by_name", label: "Requested by" },
          { key: "created_at", label: "Created", sortable: true, render: (r) => dt(r.created_at) },
        ]}
      />
    </Page>
  );
}

function RequestDetail() {
  const { id } = useParams();
  const me = useMe();
  const qc = useQueryClient();
  const key = ["refund", id!];
  const q = useQuery({ queryKey: key, queryFn: () => http<{ refund: Refund; approval: Approval | null }>("GET", `/api/refunds/requests/${id}`), refetchInterval: 3000 });
  if (!q.data) return <ErrorBox error={q.error} />;
  const r = q.data.refund;
  return (
    <Page subtitle="Refund request" title={`Refund #${r.id}`} status={<Badge tone={tone(r.status)}>{r.status}</Badge>}>
      <RecordTabs tabs={[{ key: "summary", label: "Summary", content: <>
      <Card>
        <KeyValues rows={[
          ["Charge", r.charge_id], ["Merchant", r.merchant], ["Amount", r.amount], ["Reason", `${r.reason_code} — ${r.reason}`],
          ["Requested by", r.requested_by_name], ["Second person needed", r.approval_why ?? "no (under threshold)"],
          ["Processor ref", r.processor_ref ?? "—"], ["Attempts", r.attempts], ["Last error", r.last_error ?? "—"], ["Executed", dt(r.executed_at)],
        ]} />
        {r.status === "unknown" && can(me.data, "refunds.reconcile") && (
          <div className="mt-3"><ReasonAction label="Reconcile now" onSubmit={async (reason) => { await http("POST", `/api/refunds/requests/${id}/reconcile`, { reason }); qc.invalidateQueries({ queryKey: key }); }} /></div>
        )}
      </Card>
      {q.data.approval && <Card title="Approval"><ApprovalPanel approval={q.data.approval} invalidate={[key, ["refund-stats"]]} /></Card>}
      </> }, { key: "audit", label: "Audit history", content: <Card title="Audit trail"><AuditTimeline url={`/api/refunds/requests/${id}/audit`} /></Card> }]} />
    </Page>
  );
}

export const routes: ToolRoute[] = [
  { path: "/refunds", element: <Requests /> },
  { path: "/refunds/transactions", element: <Transactions /> },
  { path: "/refunds/transactions/:id", element: <TransactionDetail /> },
  { path: "/refunds/requests/:id", element: <RequestDetail /> },
];
