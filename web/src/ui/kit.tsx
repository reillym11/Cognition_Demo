import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { http } from "../api/client";

export function cents(c: number | null | undefined, currency = "USD"): string {
  if (c === null || c === undefined) return "—";
  const sign = c < 0 ? "-" : "";
  const a = Math.abs(c);
  const whole = Math.floor(a / 100).toLocaleString("en-US");
  return `${sign}${currency === "USD" ? "$" : currency + " "}${whole}.${String(a % 100).padStart(2, "0")}`;
}

export function dt(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString() : "—";
}

export function Page({ title, actions, children }: { title: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-xl font-semibold">{title}</h1>
        <div className="flex gap-2">{actions}</div>
      </div>
      {children}
    </section>
  );
}

export function Card({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      {title && <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-600">{title}</h2>}
      {children}
    </div>
  );
}

export function Badge({ children, tone = "slate" }: { children: ReactNode; tone?: "slate" | "green" | "red" | "amber" | "blue" }) {
  const tones = {
    slate: "bg-slate-100 text-slate-700",
    green: "bg-green-100 text-green-800",
    red: "bg-red-100 text-red-800",
    amber: "bg-amber-100 text-amber-900",
    blue: "bg-blue-100 text-blue-800",
  };
  return <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${tones[tone]}`}>{children}</span>;
}

export function Button(props: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "danger" }) {
  const { variant = "secondary", className = "", ...rest } = props;
  const v = {
    primary: "bg-blue-700 text-white hover:bg-blue-800",
    secondary: "border border-slate-300 bg-white hover:bg-slate-50",
    danger: "bg-red-700 text-white hover:bg-red-800",
  }[variant];
  return <button {...rest} className={`rounded px-3 py-1.5 text-sm font-medium disabled:opacity-50 ${v} ${className}`} />;
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <div role="alert" className="rounded border border-red-300 bg-red-50 p-2 text-sm text-red-800">
      {error instanceof Error ? error.message : String(error)}
    </div>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block font-medium text-slate-700">{label}</span>
      {children}
    </label>
  );
}

export const inputCls = "w-full rounded border border-slate-300 px-2 py-1.5 text-sm";

export function KeyValues({ rows }: { rows: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-slate-500">{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export type Column<T> = { key: string; label: string; render?: (row: T) => ReactNode; sortable?: boolean };

/** Server-side paginated/sorted table. Filters live in the caller and are part of `params`. */
export function DataTable<T extends { id: number | string }>({
  url, params, columns, onRowClick, rowTestId,
}: {
  url: string;
  params: Record<string, string | number | undefined>;
  columns: Column<T>[];
  onRowClick?: (row: T) => void;
  rowTestId?: string;
}) {
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<string | undefined>(undefined);
  const qs = new URLSearchParams();
  Object.entries({ ...params, page, sort }).forEach(([k, v]) => v !== undefined && v !== "" && qs.set(k, String(v)));
  const q = useQuery({ queryKey: [url, qs.toString()], queryFn: () => http<{ total: number; items: T[]; page_size: number }>("GET", `${url}?${qs}`) });
  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / q.data.page_size)) : 1;
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
      <ErrorBox error={q.error} />
      <table className="min-w-full text-sm">
        <thead className="bg-slate-100 text-left text-xs uppercase text-slate-600">
          <tr>
            {columns.map((c) => (
              <th key={c.key} className="px-3 py-2" scope="col">
                {c.sortable ? (
                  <button className="uppercase" onClick={() => setSort(sort === c.key ? `-${c.key}` : c.key)}>
                    {c.label} {sort === c.key ? "▲" : sort === `-${c.key}` ? "▼" : ""}
                  </button>
                ) : (
                  c.label
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {q.data?.items.map((row) => (
            <tr key={row.id} data-testid={rowTestId} className={`border-t border-slate-100 ${onRowClick ? "cursor-pointer hover:bg-blue-50" : ""}`} onClick={() => onRowClick?.(row)}>
              {columns.map((c) => (
                <td key={c.key} className="px-3 py-2">
                  {c.render ? c.render(row) : String((row as Record<string, unknown>)[c.key] ?? "—")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="flex items-center justify-between border-t border-slate-100 px-3 py-2 text-sm text-slate-600">
        <span data-testid="table-total">{q.isLoading ? "Loading…" : `${q.data?.total.toLocaleString() ?? 0} results`}</span>
        <span className="flex items-center gap-2">
          <Button disabled={page <= 1} onClick={() => setPage(page - 1)}>Prev</Button>
          <span>Page {page} / {pages}</span>
          <Button disabled={page >= pages} onClick={() => setPage(page + 1)}>Next</Button>
        </span>
      </div>
    </div>
  );
}

/** Every decision needs a reason: one dialog used by all tools. */
export function ReasonAction({
  label, variant = "secondary", onSubmit, extra, disabled, testId,
}: {
  label: string;
  variant?: "primary" | "secondary" | "danger";
  onSubmit: (reason: string) => Promise<unknown>;
  extra?: ReactNode;
  disabled?: boolean;
  testId?: string;
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  if (!open)
    return (
      <Button variant={variant} disabled={disabled} onClick={() => setOpen(true)} data-testid={testId}>
        {label}
      </Button>
    );
  return (
    <div className="w-full space-y-2 rounded border border-slate-300 bg-slate-50 p-3">
      {extra}
      <Field label={`Reason for "${label}" (required)`}>
        <textarea className={inputCls} rows={2} value={reason} onChange={(e) => setReason(e.target.value)} />
      </Field>
      <ErrorBox error={err} />
      <div className="flex gap-2">
        <Button
          variant={variant}
          disabled={busy || reason.trim().length < 3}
          onClick={async () => {
            setBusy(true);
            setErr(null);
            try {
              await onSubmit(reason);
              setOpen(false);
              setReason("");
            } catch (e) {
              setErr(e);
            } finally {
              setBusy(false);
            }
          }}
        >
          Confirm {label}
        </Button>
        <Button onClick={() => setOpen(false)}>Cancel</Button>
      </div>
    </div>
  );
}

export type Approval = {
  id: number; kind: string; title: string; status: string; current_stage: number; requested_by_name: string;
  request_reason: string; requested_at: string; stages: { name: string; permission: string; min_approvers: number }[];
  decisions: { stage: number; decided_by_name: string; decision: string; reason: string; decided_at: string }[];
  can_decide?: boolean; cannot_decide_reason?: string; note: string; payload: Record<string, unknown>; subject_type: string; subject_id: string;
};

export function ApprovalPanel({ approval, invalidate }: { approval: Approval; invalidate: string[][] }) {
  const qc = useQueryClient();
  const decide = async (decision: string, reason: string) => {
    await http("POST", `/api/approvals/${approval.id}/decide`, { decision, reason });
    invalidate.forEach((k) => qc.invalidateQueries({ queryKey: k }));
    qc.invalidateQueries({ queryKey: ["inbox"] });
    qc.invalidateQueries({ predicate: (q) => String(q.queryKey[0]).endsWith("/audit") });
  };
  const tone = approval.status === "approved" ? "green" : approval.status === "rejected" ? "red" : "amber";
  return (
    <div className="space-y-2 rounded border border-slate-200 p-3" data-testid="approval-panel">
      <div className="flex items-center justify-between">
        <strong className="text-sm">{approval.title}</strong>
        <Badge tone={tone}>{approval.status}</Badge>
      </div>
      <p className="text-xs text-slate-600">
        Requested by {approval.requested_by_name} · {dt(approval.requested_at)} · “{approval.request_reason}”
      </p>
      {approval.note && <p className="text-xs text-slate-600">{approval.note}</p>}
      <ol className="flex flex-wrap gap-2 text-xs">
        {approval.stages.map((s, i) => (
          <li key={i} className={`rounded px-2 py-1 ${i < approval.current_stage || approval.status === "approved" ? "bg-green-100" : i === approval.current_stage && approval.status === "open" ? "bg-amber-100" : "bg-slate-100"}`}>
            {i + 1}. {s.name}
          </li>
        ))}
      </ol>
      {approval.decisions.map((d, i) => (
        <p key={i} className="text-xs">
          <Badge tone={d.decision === "approve" ? "green" : "red"}>{d.decision}</Badge> {d.decided_by_name}: “{d.reason}”
        </p>
      ))}
      {approval.status === "open" &&
        (approval.can_decide ? (
          <div className="flex flex-wrap gap-2">
            <ReasonAction label="Approve" variant="primary" testId="approve" onSubmit={(r) => decide("approve", r)} />
            <ReasonAction label="Reject" variant="danger" testId="reject" onSubmit={(r) => decide("reject", r)} />
          </div>
        ) : (
          <p className="text-xs text-slate-500" data-testid="cannot-decide">You can't decide this: {approval.cannot_decide_reason}</p>
        ))}
    </div>
  );
}

export type AuditItem = { seq: number; occurred_at: string; actor_name: string; action: string; reason: string | null; before: unknown; after: unknown };

export function AuditTimeline({ url }: { url: string }) {
  const q = useQuery({ queryKey: [url], queryFn: () => http<AuditItem[]>("GET", url) });
  return (
    <ol className="space-y-2 text-sm" data-testid="audit-timeline">
      <ErrorBox error={q.error} />
      {q.data?.map((e) => (
        <li key={e.seq} className="border-l-2 border-slate-300 pl-3">
          <div className="flex justify-between">
            <span className="font-medium">{e.action}</span>
            <span className="text-xs text-slate-500">{dt(e.occurred_at)}</span>
          </div>
          <div className="text-xs text-slate-600">
            {e.actor_name}
            {e.reason ? ` — “${e.reason}”` : ""}
          </div>
          {e.after != null && <code className="block truncate text-xs text-slate-500">{JSON.stringify(e.after)}</code>}
        </li>
      ))}
    </ol>
  );
}

/** Masked by default; reveal calls an audited endpoint and shows the value until navigation. */
export function MaskedField({ value, revealUrl, canReveal, field }: { value: string | null; revealUrl: string; canReveal: boolean; field: string }) {
  const [shown, setShown] = useState<string | null>(null);
  const m = useMutation({
    mutationFn: (reason: string) => http<{ value: string }>("POST", revealUrl, { field, reason }),
    onSuccess: (d) => setShown(d.value),
  });
  return (
    <span className="inline-flex flex-wrap items-center gap-2" data-testid={`masked-${field}`}>
      <code>{shown ?? value ?? "—"}</code>
      {canReveal && shown === null && value && (
        <ReasonAction label="Reveal" onSubmit={(r) => m.mutateAsync(r)} testId={`reveal-${field}`} />
      )}
    </span>
  );
}

export function ExportButton({ url, params }: { url: string; params: Record<string, string | number | undefined> }) {
  return (
    <ReasonAction
      label="Export CSV"
      testId="export"
      onSubmit={async (reason) => {
        const qs = new URLSearchParams();
        Object.entries({ ...params, reason }).forEach(([k, v]) => v !== undefined && v !== "" && qs.set(k, String(v)));
        const r = await fetch(`${url}?${qs}`, { credentials: "same-origin" });
        if (!r.ok) throw new Error((await r.json()).detail ?? r.statusText);
        const blob = await r.blob();
        const a = document.createElement("a");
        a.href = URL.createObjectURL(blob);
        a.download = (r.headers.get("content-disposition") ?? "").match(/filename="([^"]+)"/)?.[1] ?? "export.csv";
        a.click();
      }}
    />
  );
}

export function StageBar({ stages, current }: { stages: { key: string; label: string }[]; current: string }) {
  const idx = stages.findIndex((s) => s.key === current);
  return (
    <ol className="flex flex-wrap gap-1 text-xs" data-testid="stage-bar">
      {stages.map((s, i) => (
        <li key={s.key} className={`rounded px-2 py-1 ${i < idx ? "bg-green-100 text-green-900" : i === idx ? "bg-blue-700 text-white" : "bg-slate-100 text-slate-600"}`}>
          {s.label}
        </li>
      ))}
    </ol>
  );
}

export function Select({ value, onChange, options, label }: { value: string; onChange: (v: string) => void; options: [string, string][]; label: string }) {
  return (
    <label className="text-sm">
      <span className="sr-only">{label}</span>
      <select aria-label={label} className="rounded border border-slate-300 px-2 py-1.5 text-sm" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map(([v, l]) => (
          <option key={v} value={v}>{l}</option>
        ))}
      </select>
    </label>
  );
}
