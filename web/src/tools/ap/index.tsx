import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { http } from "../../api/client";
import { can, useMe } from "../../shell/me";
import {
  ApprovalPanel, AuditTimeline, Badge, Button, Card, DataTable, ErrorBox, Field, KeyValues, MaskedField, Page, ReasonAction, Select, cents, dt, type Approval, Input, Checkbox, SearchBox, RecordTabs, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow,
} from "../../ui/kit";
import type { ToolRoute } from "../registry";

type FieldX = { value: unknown; confidence: number };
type Invoice = {
  id: number; status: string; source: string; vendor_name: string | null; invoice_number: string | null; invoice_date: string | null; due_date: string | null;
  po_number: string | null; subtotal_cents: number | null; tax_cents: number | null; total_cents: number | null; remit_bank_name: string | null;
  remit_account: string | null; remit_routing: string | null; extraction: { engine: string; warnings: string[]; fields: Record<string, FieldX> };
  line_items: { description: string; quantity: number; unit_cents: number; amount_cents: number }[]; match: { issues?: string[]; po_remaining_cents?: number | null };
  duplicate_of: number | null; vendor_id: number | null; created_at: string; batch_id: number | null;
  approval?: Approval | null; vendor?: { id: number; name: string; bank_account: string; bank_routing: string; phone_on_file: string } | null;
  po?: { po_number: string; amount_cents: number; invoiced_cents: number; status: string } | null; can?: { verify: boolean; bank_request: boolean };
};
const TONE: Record<string, "slate" | "green" | "red" | "amber" | "blue"> = {
  needs_verification: "amber", exception: "red", duplicate: "slate", matched: "blue", pending_approval: "amber", approved: "green", batched: "green", rejected: "slate",
};
const money = (c: number | null | undefined) => (c == null ? "—" : cents(c));
const EXTRACT_TO_COL: Record<string, string> = { subtotal: "subtotal_cents", tax: "tax_cents", total: "total_cents" };

function Queue() {
  const nav = useNavigate();
  const me = useMe();
  const qc = useQueryClient();
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const stats = useQuery({ queryKey: ["ap-stats"], queryFn: () => http<{ by_status: { status: string; count: number; total_cents: number }[]; bank_changes_open: number }>("GET", "/api/ap/stats") });
  const upload = async (f: File) => {
    const fd = new FormData();
    fd.append("file", f);
    const r = await fetch("/api/ap/invoices", { method: "POST", body: fd, credentials: "include", headers: { "X-CSRF-Token": document.cookie.match(/itp_csrf=([^;]+)/)?.[1] ?? "" } });
    if (!r.ok) { setErr(new Error((await r.json()).detail ?? r.statusText)); return; }
    setErr(null);
    nav(`/ap/invoices/${(await r.json()).id}`);
  };
  return (
    <Page title="AP invoices" actions={
      <div className="flex gap-2">
        {can(me.data, "ap.upload") && (
          <>
            <label className="cursor-pointer rounded px-3 py-1.5 text-sm font-semibold text-white" style={{ background: "var(--colorBrandBackground)" }}>Upload PDF<input type="file" accept="application/pdf" className="sr-only" aria-label="Upload invoice PDF" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} /></label>
            <Button onClick={async () => { await http("POST", "/api/ap/inbox/poll"); qc.invalidateQueries(); }}>Poll AP inbox</Button>
          </>
        )}
        {can(me.data, "ap.batch") && <Button onClick={() => nav("/ap/batches")}>Payment batches</Button>}
      </div>
    }>
      <ErrorBox error={err} />
      <div className="flex flex-wrap gap-2 text-sm">
        {stats.data?.by_status.map((s) => <button key={s.status} onClick={() => setStatus(s.status)}><Badge tone={TONE[s.status]}>{s.status}: {s.count} · {cents(s.total_cents)}</Badge></button>)}
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <Select label="Status" value={status} onChange={setStatus} options={[["", "All"], ...Object.keys(TONE).map((k) => [k, k] as [string, string])]} />
        <SearchBox label="Search invoices" placeholder="vendor or number" value={q} onChange={(v) => setQ(v)} />
      </div>
      <DataTable<Invoice>
        url="/api/ap/invoices" params={{ status, q }} rowTestId="invoice-row" onRowClick={(r) => nav(`/ap/invoices/${r.id}`)}
        columns={[
          { key: "id", label: "#" }, { key: "vendor_name", label: "Vendor" }, { key: "invoice_number", label: "Invoice" },
          { key: "total_cents", label: "Total", render: (r) => money(r.total_cents) },
          { key: "status", label: "Status", render: (r) => <Badge tone={TONE[r.status]}>{r.status}</Badge> },
          { key: "issues", label: "Issues", render: (r) => (r.match.issues ?? []).join(", ") || "—" },
          { key: "source", label: "Source" }, { key: "created_at", label: "Received", render: (r) => dt(r.created_at) },
        ]}
      />
    </Page>
  );
}

function VerifyForm({ inv, onDone }: { inv: Invoice; onDone: () => void }) {
  const editable = ["vendor_name", "invoice_number", "invoice_date", "due_date", "po_number", "subtotal_cents", "tax_cents", "total_cents", "remit_bank_name", "remit_account", "remit_routing"];
  const conf = (k: string) => inv.extraction.fields[Object.entries(EXTRACT_TO_COL).find(([, v]) => v === k)?.[0] ?? k]?.confidence ?? 1;
  const [vals, setVals] = useState<Record<string, string>>({});
  return (
    <Card title="Verify extracted fields">
      <p className="mb-2 text-xs text-slate-500">Engine {inv.extraction.engine}. Fields under 90% confidence are highlighted; bank fields are masked, re-type them only if the PDF differs.</p>
      {inv.extraction.warnings.map((w) => <p key={w} className="text-sm text-amber-800">⚠ {w}</p>)}
      <div className="grid grid-cols-2 gap-2">
        {editable.map((k) => (
          <Field key={k} label={`${k} (${Math.round(conf(k) * 100)}%)`}>
            <Input aria-label={k} className={conf(k) < 0.9 ? "ring-2 ring-amber-400" : undefined} placeholder={String((inv as unknown as Record<string, unknown>)[k] ?? "")}
              value={vals[k] ?? ""} onChange={(e) => setVals({ ...vals, [k]: e.target.value })} />
          </Field>
        ))}
      </div>
      <ReasonAction label="Save corrections" variant="primary" testId="verify" onSubmit={async (reason) => {
        const fields = Object.fromEntries(Object.entries(vals).filter(([, v]) => v !== "").map(([k, v]) => [k, k.endsWith("_cents") ? Number(v) : v]));
        await http("POST", `/api/ap/invoices/${inv.id}/verify`, { fields, reason });
        onDone();
      }} />
    </Card>
  );
}

function Detail() {
  const { id } = useParams();
  const qc = useQueryClient();
  const nav = useNavigate();
  const qk = ["ap-invoice", id!];
  const q = useQuery({ queryKey: qk, queryFn: () => http<Invoice>("GET", `/api/ap/invoices/${id}`) });
  if (!q.data) return <ErrorBox error={q.error} />;
  const inv = q.data;
  const refresh = () => qc.invalidateQueries({ queryKey: qk });
  const workable = ["needs_verification", "exception"].includes(inv.status);
  const bankDiff = (inv.match.issues ?? []).includes("bank_details_differ");
  return (
    <Page subtitle="Vendor invoice" title={`Invoice ${inv.invoice_number ?? `#${inv.id}`}`} status={<Badge tone={TONE[inv.status]}>{inv.status}</Badge>}>
      <RecordTabs tabs={[{ key: "summary", label: "Summary", content: <>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Document"><iframe title="Invoice PDF" src={`/api/ap/invoices/${inv.id}/file`} className="h-[520px] w-full rounded border" /></Card>
        <div className="space-y-4">
          <Card title="Extracted">
            <KeyValues rows={[
              ["Vendor", inv.vendor_name ?? "—"], ["Invoice", inv.invoice_number ?? "—"], ["Dates", `${inv.invoice_date ?? "?"} → due ${inv.due_date ?? "?"}`],
              ["PO", inv.po ? `${inv.po.po_number} (remaining ${money(inv.po.amount_cents - inv.po.invoiced_cents)})` : inv.po_number ?? "—"],
              ["Subtotal / tax / total", `${money(inv.subtotal_cents)} / ${money(inv.tax_cents)} / ${money(inv.total_cents)}`],
              ["Remit to", <>{inv.remit_bank_name} · acct {inv.remit_account} · routing {inv.remit_routing}</>],
              ["On file", inv.vendor ? <>acct <MaskedField field="bank_account" value={inv.vendor.bank_account} revealUrl={`/api/ap/vendors/${inv.vendor.id}/reveal`} canReveal={false} /></> : "unknown vendor"],
              ["Issues", (inv.match.issues ?? []).map((i) => <Badge key={i} tone="red">{i}</Badge>)],
              ["Duplicate of", inv.duplicate_of ? <a className="text-blue-700 underline" href={`/ap/invoices/${inv.duplicate_of}`}>#{inv.duplicate_of}</a> : "—"],
            ]} />
            <Table size="small" className="mt-2 min-w-full text-xs"><TableBody>{inv.line_items.map((l, i) => <TableRow key={i} className="border-t"><TableCell>{l.description}</TableCell><TableCell>{l.quantity}</TableCell><TableCell>{money(l.unit_cents)}</TableCell><TableCell>{money(l.amount_cents)}</TableCell></TableRow>)}</TableBody></Table>
          </Card>
          <div className="flex flex-wrap gap-2">
            {inv.can?.verify && inv.status === "matched" && <ReasonAction label="Submit for approval" variant="primary" testId="submit" onSubmit={async (reason) => { await http("POST", `/api/ap/invoices/${inv.id}/submit`, { reason }); refresh(); }} />}
            {inv.can?.verify && [...["needs_verification", "exception", "duplicate", "matched"]].includes(inv.status) && <ReasonAction label="Reject" onSubmit={async (reason) => { await http("POST", `/api/ap/invoices/${inv.id}/reject`, { reason }); refresh(); }} />}
            {inv.can?.bank_request && bankDiff && inv.vendor && (
              <ReasonAction label="Request bank change from this invoice" onSubmit={async (reason) => {
                const r = await http<{ id: number }>("POST", `/api/ap/vendors/${inv.vendor!.id}/bank-changes`, { from_invoice: inv.id, reason });
                nav(`/ap/bank-changes/${r.id}`);
              }} />
            )}
          </div>
          {inv.can?.verify && workable && <VerifyForm key={inv.status} inv={inv} onDone={refresh} />}
          {inv.approval && <Card title="Approval"><ApprovalPanel approval={inv.approval} invalidate={[qk]} /></Card>}
        </div>
      </div>
      </> }, { key: "audit", label: "Audit history", content: <Card title="Audit trail"><AuditTimeline url={`/api/ap/invoices/${inv.id}/audit`} /></Card> }]} />
    </Page>
  );
}

type BankChange = { id: number; vendor_name: string; phone_on_file: string; status: string; new_bank_name: string; new_account: string; new_routing: string; requested_by_name: string; request_reason: string; callback_notes: string | null; created_at: string; approval?: Approval | null; current?: { bank_name: string; bank_account: string }; can?: { callback: boolean } };

function BankChanges() {
  const nav = useNavigate();
  const q = useQuery({ queryKey: ["ap-bank"], queryFn: () => http<BankChange[]>("GET", "/api/ap/bank-changes") });
  return (
    <Page title="Vendor bank changes">
      <p className="text-sm text-slate-600">Every change is verified by a call-back to the phone number already on file (by someone other than the requester) and approved by a financial controller (a third person).</p>
      <ErrorBox error={q.error} />
      <Table size="small" className="min-w-full text-sm"><TableHeader className="text-left text-xs uppercase text-slate-500"><TableRow><TableHeaderCell>#</TableHeaderCell><TableHeaderCell>Vendor</TableHeaderCell><TableHeaderCell>Status</TableHeaderCell><TableHeaderCell>Requested by</TableHeaderCell><TableHeaderCell>When</TableHeaderCell></TableRow></TableHeader>
        <TableBody>{q.data?.map((b) => <TableRow key={b.id} className="cursor-pointer border-t hover:bg-slate-50" onClick={() => nav(`/ap/bank-changes/${b.id}`)}><TableCell className="py-1">{b.id}</TableCell><TableCell>{b.vendor_name}</TableCell><TableCell><Badge tone={b.status === "applied" ? "green" : b.status === "rejected" ? "slate" : "amber"}>{b.status}</Badge></TableCell><TableCell>{b.requested_by_name}</TableCell><TableCell>{dt(b.created_at)}</TableCell></TableRow>)}</TableBody>
      </Table>
    </Page>
  );
}

function BankChangeDetail() {
  const { id } = useParams();
  const qc = useQueryClient();
  const qk = ["ap-bank", id!];
  const q = useQuery({ queryKey: qk, queryFn: () => http<BankChange>("GET", `/api/ap/bank-changes/${id}`) });
  const [confirmed, setConfirmed] = useState(true);
  if (!q.data) return <ErrorBox error={q.error} />;
  const b = q.data;
  return (
    <Page subtitle="Vendor bank change" title={`Bank change #${b.id} · ${b.vendor_name}`} status={<Badge tone="amber">{b.status}</Badge>}>
      <Card title="Change">
        <KeyValues rows={[["Current", `${b.current?.bank_name} · acct ${b.current?.bank_account}`], ["Requested", `${b.new_bank_name} · acct ${b.new_account} · routing ${b.new_routing}`],
          ["Requested by", `${b.requested_by_name}: ${b.request_reason}`], ["Phone on file", b.phone_on_file], ["Call-back notes", b.callback_notes ?? "—"]]} />
      </Card>
      {b.can?.callback && (
        <Card title="Record call-back">
          <p className="mb-2 text-sm">Call <strong>{b.phone_on_file}</strong> (the number on file, never one from the invoice or email) and confirm the change with a known contact.</p>
          <Checkbox checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} label={<>Vendor confirmed the new details</>} />
          <ReasonAction label="Record call-back" variant="primary" testId="callback" onSubmit={async (notes) => { await http("POST", `/api/ap/bank-changes/${b.id}/callback`, { confirmed, notes }); qc.invalidateQueries({ queryKey: qk }); }} />
        </Card>
      )}
      {b.approval && <Card title="Controller approval"><ApprovalPanel approval={b.approval} invalidate={[qk]} /></Card>}
    </Page>
  );
}

function Batches() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["ap-batches"], queryFn: () => http<{ id: number; count: number; total_cents: number; sha256: string; created_by: string; created_at: string }[]>("GET", "/api/ap/batches") });
  return (
    <Page title="Payment batches" actions={<ReasonAction label="Create batch from approved invoices" variant="primary" onSubmit={async (reason) => { await http("POST", "/api/ap/batches", { reason }); qc.invalidateQueries(); }} />}>
      <ErrorBox error={q.error} />
      <Table size="small" className="min-w-full text-sm"><TableHeader className="text-left text-xs uppercase text-slate-500"><TableRow><TableHeaderCell>#</TableHeaderCell><TableHeaderCell>Invoices</TableHeaderCell><TableHeaderCell>Total</TableHeaderCell><TableHeaderCell>SHA-256</TableHeaderCell><TableHeaderCell>By</TableHeaderCell><TableHeaderCell>When</TableHeaderCell><TableHeaderCell /></TableRow></TableHeader>
        <TableBody>{q.data?.map((b) => (
          <TableRow key={b.id} className="border-t"><TableCell className="py-1">{b.id}</TableCell><TableCell>{b.count}</TableCell><TableCell>{cents(b.total_cents)}</TableCell><TableCell className="font-mono text-xs">{b.sha256.slice(0, 16)}…</TableCell><TableCell>{b.created_by}</TableCell><TableCell>{dt(b.created_at)}</TableCell>
            <TableCell><ReasonAction label="Download" onSubmit={async (reason) => { window.location.href = `/api/ap/batches/${b.id}/file?reason=${encodeURIComponent(reason)}`; }} /></TableCell></TableRow>
        ))}</TableBody>
      </Table>
    </Page>
  );
}

export const routes: ToolRoute[] = [
  { path: "/ap", element: <Queue /> },
  { path: "/ap/invoices/:id", element: <Detail /> },
  { path: "/ap/bank-changes", element: <BankChanges /> },
  { path: "/ap/bank-changes/:id", element: <BankChangeDetail /> },
  { path: "/ap/batches", element: <Batches /> },
];
