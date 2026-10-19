import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import {
  Badge as FBadge, Button as FButton, Caption1, Card as FCard, CardHeader, Checkbox, Dialog, DialogActions, DialogBody,
  DialogContent, DialogSurface, DialogTitle, Field as FField, Input, Label, MessageBar, MessageBarBody, Select as FSelect,
  Spinner, Subtitle2, Tab, TabList, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, Textarea, Title3,
  makeStyles, mergeClasses, tokens, type ButtonProps,
} from "@fluentui/react-components";
import { ArrowDownload20Regular, Checkmark12Filled, ChevronLeft20Regular, ChevronRight20Regular, Eye20Regular } from "@fluentui/react-icons";
import { http } from "../api/client";

/** Fluent UI v9 controls used directly by tool pages. Import from here so every tool looks the same. */
export { Checkbox, Input, FSelect as Choice, Table, TableBody, TableCell, TableHeader, TableHeaderCell, TableRow, Textarea };

export function cents(c: number | null | undefined, currency = "USD"): string {
  if (c === null || c === undefined) return "---";
  const sign = c < 0 ? "-" : "";
  const a = Math.abs(c);
  const whole = Math.floor(a / 100).toLocaleString("en-US");
  return `${sign}${currency === "USD" ? "$" : currency + " "}${whole}.${String(a % 100).padStart(2, "0")}`;
}

export function dt(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }) : "---";
}

export function day(iso: string | null | undefined): string {
  if (!iso) return "---";
  const d = /^\d{4}-\d{2}-\d{2}$/.test(iso) ? new Date(`${iso}T00:00:00`) : new Date(iso);
  return d.toLocaleDateString(undefined, { dateStyle: "medium" });
}

const UPPER = new Set(["kyc", "ap", "po", "pii", "sla", "api", "ui", "csv", "pdf", "id", "us", "eu", "uk", "qa", "sso"]);

/** Readable label for an enum / snake_case / UPPER_CASE value: "auto_cleared" -> "Auto cleared". */
export function humanize(v: string | null | undefined): string {
  if (v === null || v === undefined || v === "") return "---";
  const words = String(v).replace(/[._-]+/g, " ").trim().toLowerCase().split(/\s+/);
  return words.map((w, i) => (UPPER.has(w) ? w.toUpperCase() : i === 0 ? w[0].toUpperCase() + w.slice(1) : w)).join(" ");
}

/** "3 h", "2 d 4 h", "25 min" for a duration in milliseconds. */
export function duration(ms: number): string {
  const m = Math.round(Math.abs(ms) / 60000);
  if (m < 60) return `${m} min`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h} h`;
  const d = Math.floor(h / 24);
  return h % 24 ? `${d} d ${h % 24} h` : `${d} d`;
}

/** SLA cell: relative due time on top, readable date below. */
export function DueCell({ iso, breached, done }: { iso: string | null | undefined; breached?: boolean; done?: boolean }) {
  if (!iso) return <>---</>;
  const ms = new Date(iso).getTime() - Date.now();
  const overdue = breached ?? ms < 0;
  const rel = done ? "Closed" : overdue ? `Overdue ${duration(ms)}` : `Due in ${duration(ms)}`;
  return (
    <span className="inline-flex flex-col leading-tight" title={new Date(iso).toLocaleString()}>
      <span className={!done && overdue ? "font-semibold text-red-700" : ""}>{rel}</span>
      <span className="text-xs text-slate-500">{dt(iso)}</span>
    </span>
  );
}

const useStyles = makeStyles({
  commandBar: {
    display: "flex", flexWrap: "wrap", alignItems: "center", gap: "4px", padding: "6px 8px",
    backgroundColor: tokens.colorNeutralBackground1, borderRadius: tokens.borderRadiusMedium, boxShadow: tokens.shadow2,
    ":empty": { display: "none" },
  },
  header: { display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: "16px", flexWrap: "wrap" },
  card: { padding: "16px" },
  danger: {
    backgroundColor: tokens.colorPaletteRedBackground3, color: tokens.colorNeutralForegroundOnBrand,
    ":hover": { backgroundColor: tokens.colorPaletteRedForeground1, color: tokens.colorNeutralForegroundOnBrand },
    ":hover:active": { backgroundColor: tokens.colorPaletteRedForeground1, color: tokens.colorNeutralForegroundOnBrand },
  },
  tableWrap: { backgroundColor: tokens.colorNeutralBackground1, borderRadius: tokens.borderRadiusMedium, boxShadow: tokens.shadow2, overflowX: "auto" },
  rowClick: { cursor: "pointer" },
  footer: {
    display: "flex", alignItems: "center", justifyContent: "space-between", padding: "6px 12px",
    borderTop: `1px solid ${tokens.colorNeutralStroke2}`, color: tokens.colorNeutralForeground2, fontSize: tokens.fontSizeBase200,
  },
  muted: { color: tokens.colorNeutralForeground3 },
  stage: {
    display: "flex", alignItems: "center", gap: "6px", minWidth: "120px", padding: "6px 22px 6px 24px",
    clipPath: "polygon(0 0, calc(100% - 12px) 0, 100% 50%, calc(100% - 12px) 100%, 0 100%, 12px 50%)",
    backgroundColor: tokens.colorNeutralBackground3, color: tokens.colorNeutralForeground2, fontSize: tokens.fontSizeBase200,
  },
  stageFirst: { clipPath: "polygon(0 0, calc(100% - 12px) 0, 100% 50%, calc(100% - 12px) 100%, 0 100%)", paddingLeft: "12px" },
  stageDone: { backgroundColor: tokens.colorPaletteGreenBackground2, color: tokens.colorPaletteGreenForeground2 },
  stageActive: { backgroundColor: tokens.colorBrandBackground, color: tokens.colorNeutralForegroundOnBrand, fontWeight: tokens.fontWeightSemibold },
  timelineItem: { borderLeft: `2px solid ${tokens.colorBrandStroke2}`, paddingLeft: "12px", position: "relative" },
  code: { fontFamily: tokens.fontFamilyMonospace, fontSize: tokens.fontSizeBase200, color: tokens.colorNeutralForeground3 },
});

/**
 * Power Apps model-driven layout: command bar on top, then the page/record header, then content.
 * `status` sits on the right of the header like a record's status reason.
 */
export function Page({ title, subtitle, actions, status, children }: { title: string; subtitle?: string; actions?: ReactNode; status?: ReactNode; children: ReactNode }) {
  const s = useStyles();
  return (
    <section className="space-y-4">
      {actions && <div role="toolbar" aria-label="Commands" className={s.commandBar}>{actions}</div>}
      <div className={s.header}>
        <div>
          {subtitle && <Caption1 className={s.muted}>{subtitle}</Caption1>}
          <Title3 as="h1" block>{title}</Title3>
        </div>
        {status && <div className="flex items-center gap-2">{status}</div>}
      </div>
      {children}
    </section>
  );
}

export function Card({ title, children }: { title?: string; children: ReactNode }) {
  const s = useStyles();
  return (
    <FCard className={s.card}>
      {title && <CardHeader header={<Subtitle2 as="h2">{title}</Subtitle2>} />}
      <div>{children}</div>
    </FCard>
  );
}

/** Record pages: Summary / Audit history tabs like a model-driven form. */
export function RecordTabs({ tabs }: { tabs: { key: string; label: string; content: ReactNode }[] }) {
  const [sel, setSel] = useState(tabs[0]?.key);
  const cur = tabs.find((t) => t.key === sel) ?? tabs[0];
  return (
    <div className="space-y-4">
      <TabList selectedValue={cur?.key} onTabSelect={(_, d) => setSel(String(d.value))}>
        {tabs.map((t) => <Tab key={t.key} value={t.key}>{t.label}</Tab>)}
      </TabList>
      <div role="tabpanel" className="space-y-4">{cur?.content}</div>
    </div>
  );
}

type Tone = "slate" | "green" | "red" | "amber" | "blue";
const TONE_COLOR = { slate: "informative", green: "success", red: "danger", amber: "warning", blue: "brand" } as const;

export function Badge({ children, tone = "slate" }: { children: ReactNode; tone?: Tone }) {
  return <FBadge appearance="tint" shape="rounded" color={TONE_COLOR[tone]}>{children}</FBadge>;
}

type BtnProps = {
  variant?: "primary" | "secondary" | "danger" | "subtle";
  children?: ReactNode;
  onClick?: React.MouseEventHandler<HTMLButtonElement>;
  disabled?: boolean;
  icon?: ButtonProps["icon"];
  size?: ButtonProps["size"];
  className?: string;
  title?: string;
  "aria-label"?: string;
  "data-testid"?: string;
};

export function Button({ variant = "secondary", className, ...rest }: BtnProps) {
  const s = useStyles();
  const appearance = variant === "danger" ? "primary" : variant;
  return <FButton {...rest} appearance={appearance} className={mergeClasses(variant === "danger" && s.danger, className)} />;
}

export function ErrorBox({ error }: { error: unknown }) {
  if (!error) return null;
  return (
    <div role="alert">
      <MessageBar intent="error"><MessageBarBody>{error instanceof Error ? error.message : String(error)}</MessageBarBody></MessageBar>
    </div>
  );
}

export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return <FField label={label} hint={hint}>{children}</FField>;
}

export function KeyValues({ rows }: { rows: [string, ReactNode][] }) {
  const s = useStyles();
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-2 text-sm">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className={s.muted}>{k}</dt>
          <dd>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

export type Column<T> = { key: string; label: string; render?: (row: T) => ReactNode; sortable?: boolean };

/** Server-side paginated/sorted list view. Filters live in the caller and are part of `params`. */
export function DataTable<T extends { id: number | string }>({
  url, params, columns, onRowClick, rowTestId,
}: {
  url: string;
  params: Record<string, string | number | undefined>;
  columns: Column<T>[];
  onRowClick?: (row: T) => void;
  rowTestId?: string;
}) {
  const s = useStyles();
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<string | undefined>(undefined);
  const qs = new URLSearchParams();
  Object.entries({ ...params, page, sort }).forEach(([k, v]) => v !== undefined && v !== "" && qs.set(k, String(v)));
  const q = useQuery({ queryKey: [url, qs.toString()], queryFn: () => http<{ total: number; items: T[]; page_size: number }>("GET", `${url}?${qs}`) });
  const pages = q.data ? Math.max(1, Math.ceil(q.data.total / q.data.page_size)) : 1;
  const dir = (k: string) => (sort === k ? "ascending" : sort === `-${k}` ? "descending" : undefined);
  return (
    <div className={s.tableWrap}>
      <ErrorBox error={q.error} />
      <Table size="small" aria-label="Records">
        <TableHeader>
          <TableRow>
            {columns.map((c) =>
              c.sortable ? (
                <TableHeaderCell key={c.key} sortable sortDirection={dir(c.key)} onClick={() => setSort(sort === c.key ? `-${c.key}` : c.key)}>
                  {c.label}
                </TableHeaderCell>
              ) : (
                <TableHeaderCell key={c.key}>{c.label}</TableHeaderCell>
              ),
            )}
          </TableRow>
        </TableHeader>
        <TableBody>
          {q.data?.items.map((row, i) => (
            <TableRow key={`${row.id ?? i}`} data-testid={rowTestId} className={onRowClick ? s.rowClick : undefined} onClick={() => onRowClick?.(row)}>
              {columns.map((c) => (
                <TableCell key={c.key}>{c.render ? c.render(row) : String((row as Record<string, unknown>)[c.key] ?? "---")}</TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <div className={s.footer}>
        <span data-testid="table-total">{q.isLoading ? "Loading…" : `${q.data?.total.toLocaleString() ?? 0} records`}</span>
        <span className="flex items-center gap-1">
          <FButton appearance="subtle" size="small" icon={<ChevronLeft20Regular />} aria-label="Previous page" disabled={page <= 1} onClick={() => setPage(page - 1)} />
          <span>Page {page} of {pages}</span>
          <FButton appearance="subtle" size="small" icon={<ChevronRight20Regular />} aria-label="Next page" disabled={page >= pages} onClick={() => setPage(page + 1)} />
        </span>
      </div>
    </div>
  );
}

/** Every decision needs a reason: one dialog used by all tools. */
export function ReasonAction({
  label, variant = "secondary", onSubmit, extra, disabled, testId, icon,
}: {
  label: string;
  variant?: "primary" | "secondary" | "danger" | "subtle";
  onSubmit: (reason: string) => Promise<unknown>;
  extra?: ReactNode;
  disabled?: boolean;
  testId?: string;
  icon?: ButtonProps["icon"];
}) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [err, setErr] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  return (
    <>
      <Button variant={variant} disabled={disabled} icon={icon} onClick={() => setOpen(true)} data-testid={testId}>
        {label}
      </Button>
      <Dialog open={open} onOpenChange={(_, d) => { setOpen(d.open); if (!d.open) setErr(null); }}>
        <DialogSurface>
          <DialogBody>
            <DialogTitle>{label}</DialogTitle>
            <DialogContent className="space-y-3">
              {extra}
              <FField label={`Reason for "${label}"`} required hint="Recorded in the audit trail.">
                <Textarea rows={3} value={reason} onChange={(_, d) => setReason(d.value)} />
              </FField>
              <ErrorBox error={err} />
            </DialogContent>
            <DialogActions>
              <Button onClick={() => setOpen(false)}>Cancel</Button>
              <Button
                variant={variant === "danger" ? "danger" : "primary"}
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
            </DialogActions>
          </DialogBody>
        </DialogSurface>
      </Dialog>
    </>
  );
}

export type Approval = {
  id: number; kind: string; title: string; status: string; current_stage: number; requested_by_name: string;
  request_reason: string; requested_at: string; stages: { name: string; permission: string; min_approvers: number }[];
  decisions: { stage: number; decided_by_name: string; decision: string; reason: string; decided_at: string }[];
  can_decide?: boolean; cannot_decide_reason?: string; note: string; payload: Record<string, unknown>; subject_type: string; subject_id: string;
};

/** Styled like a Power Automate approval: request, stages, responses, Approve / Reject. */
export function ApprovalPanel({ approval, invalidate }: { approval: Approval; invalidate: string[][] }) {
  const s = useStyles();
  const qc = useQueryClient();
  const decide = async (decision: string, reason: string) => {
    await http("POST", `/api/approvals/${approval.id}/decide`, { decision, reason });
    invalidate.forEach((k) => qc.invalidateQueries({ queryKey: k }));
    qc.invalidateQueries({ queryKey: ["inbox"] });
    qc.invalidateQueries({ predicate: (q) => String(q.queryKey[0]).endsWith("/audit") });
  };
  const tone = approval.status === "approved" ? "green" : approval.status === "rejected" ? "red" : "amber";
  const stageState = (i: number) => (i < approval.current_stage || approval.status === "approved" ? "done" : i === approval.current_stage && approval.status === "open" ? "active" : "todo");
  return (
    <div className="space-y-3" data-testid="approval-panel">
      <div className="flex items-center justify-between gap-2">
        <strong className="text-sm">{approval.title}</strong>
        <Badge tone={tone}>{humanize(approval.status)}</Badge>
      </div>
      <Caption1 className={s.muted} block>
        Requested by {approval.requested_by_name} · {dt(approval.requested_at)} · “{approval.request_reason}”
      </Caption1>
      {approval.note && <Caption1 className={s.muted} block>{approval.note}</Caption1>}
      <StageBar stages={approval.stages.map((st, i) => ({ key: String(i), label: `${i + 1}. ${st.name}`, state: stageState(i) }))} current="" testId="approval-stages" />
      {approval.decisions.map((d, i) => (
        <p key={i} className="text-sm">
          <Badge tone={d.decision === "approve" ? "green" : "red"}>{d.decision === "approve" ? "Approved" : "Rejected"}</Badge> {d.decided_by_name}: “{d.reason}”
        </p>
      ))}
      {approval.status === "open" &&
        (approval.can_decide ? (
          <div className="flex flex-wrap gap-2">
            <ReasonAction label="Approve" variant="primary" testId="approve" onSubmit={(r) => decide("approve", r)} />
            <ReasonAction label="Reject" variant="danger" testId="reject" onSubmit={(r) => decide("reject", r)} />
          </div>
        ) : (
          <Caption1 className={s.muted} block data-testid="cannot-decide">You can't decide this: {approval.cannot_decide_reason}</Caption1>
        ))}
    </div>
  );
}

export type AuditItem = { seq: number; occurred_at: string; actor_name: string; action: string; reason: string | null; before: unknown; after: unknown };

/** Activity timeline. */
export function AuditTimeline({ url }: { url: string }) {
  const s = useStyles();
  const q = useQuery({ queryKey: [url], queryFn: () => http<AuditItem[]>("GET", url) });
  return (
    <ol className="space-y-3 text-sm" data-testid="audit-timeline">
      <ErrorBox error={q.error} />
      {q.isLoading && <Spinner size="tiny" />}
      {q.data?.map((e) => (
        <li key={e.seq} className={s.timelineItem}>
          <div className="flex justify-between gap-2">
            <span className="font-semibold">{humanize(e.action.split(".").slice(1).join(" ") || e.action)}</span>
            <Caption1 className={s.muted}>{dt(e.occurred_at)}</Caption1>
          </div>
          <div className={s.muted}>
            {e.actor_name}
            {e.reason ? `: “${e.reason}”` : ""}
          </div>
          {e.after != null && <AuditFacts value={e.after} />}
        </li>
      ))}
    </ol>
  );
}

function factValue(v: unknown): string {
  if (v === null || v === undefined || v === "") return "---";
  if (typeof v === "boolean") return v ? "Yes" : "No";
  if (Array.isArray(v)) return v.length ? v.map(factValue).join(", ") : "None";
  if (typeof v === "object") return Object.entries(v as Record<string, unknown>).map(([k, x]) => `${humanize(k)} ${factValue(x)}`).join(", ");
  if (typeof v === "string" && /^[a-z]+(_[a-z]+)+$/.test(v)) return humanize(v);
  return String(v);
}

/** Audit "after" payload as readable label/value pairs instead of raw JSON. */
function AuditFacts({ value }: { value: unknown }) {
  if (typeof value !== "object" || value === null) return <div className="text-xs text-slate-600">{factValue(value)}</div>;
  const entries = Object.entries(value as Record<string, unknown>);
  if (!entries.length) return null;
  return (
    <div className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-slate-600">
      {entries.map(([k, v]) => <span key={k}><span className="text-slate-500">{humanize(k)}:</span> {factValue(v)}</span>)}
    </div>
  );
}

/** Masked by default; reveal calls an audited endpoint and shows the value until navigation. */
export function MaskedField({ value, revealUrl, canReveal, field }: { value: string | null; revealUrl: string; canReveal: boolean; field: string }) {
  const s = useStyles();
  const [shown, setShown] = useState<string | null>(null);
  const m = useMutation({
    mutationFn: (reason: string) => http<{ value: string }>("POST", revealUrl, { field, reason }),
    onSuccess: (d) => setShown(d.value),
  });
  return (
    <span className="inline-flex flex-wrap items-center gap-2" data-testid={`masked-${field}`}>
      <code className={s.code}>{shown ?? value ?? "---"}</code>
      {canReveal && shown === null && value && (
        <ReasonAction label="Reveal" variant="subtle" icon={<Eye20Regular />} onSubmit={(r) => m.mutateAsync(r)} testId={`reveal-${field}`} />
      )}
    </span>
  );
}

export function ExportButton({ url, params }: { url: string; params: Record<string, string | number | undefined> }) {
  return (
    <ReasonAction
      label="Export CSV"
      variant="subtle"
      icon={<ArrowDownload20Regular />}
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

/** Business-process-flow style stage bar (chevrons; completed stages ticked). */
export function StageBar({ stages, current, testId = "stage-bar" }: { stages: { key: string; label: string; state?: "done" | "active" | "todo" }[]; current: string; testId?: string }) {
  const s = useStyles();
  const idx = stages.findIndex((x) => x.key === current);
  return (
    <ol className="flex flex-wrap gap-0.5" data-testid={testId} aria-label="Stages">
      {stages.map((x, i) => {
        const state = x.state ?? (i < idx ? "done" : i === idx ? "active" : "todo");
        return (
          <li
            key={x.key}
            aria-current={state === "active" ? "step" : undefined}
            className={mergeClasses(s.stage, i === 0 && s.stageFirst, state === "done" && s.stageDone, state === "active" && s.stageActive)}
          >
            {state === "done" && <Checkmark12Filled />}
            {x.label}
          </li>
        );
      })}
    </ol>
  );
}

/** Compact view filter (label above a Fluent select), used above list views. */
export function Select({ value, onChange, options, label }: { value: string; onChange: (v: string) => void; options: [string, string][]; label: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <Label size="small">{label}</Label>
      <FSelect size="small" aria-label={label} value={value} onChange={(_, d) => onChange(d.value)}>
        {options.map(([v, l]) => (
          <option key={v} value={v}>{l}</option>
        ))}
      </FSelect>
    </div>
  );
}

export function SearchBox({ label, placeholder, value, onChange }: { label: string; placeholder?: string; value: string; onChange: (v: string) => void }) {
  return (
    <div className="flex flex-col gap-0.5">
      <Label size="small">{label}</Label>
      <Input size="small" aria-label={label} placeholder={placeholder} value={value} onChange={(_, d) => onChange(d.value)} />
    </div>
  );
}
