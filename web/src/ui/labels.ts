import { humanize } from "./kit";

/** Display names for Entra app roles (match the sign-in personas). */
export const ROLE_LABELS: Record<string, string> = {
  "Audit.Auditor": "Auditor",
  "Compliance.Admin": "Compliance Admin",
  "Platform.Admin": "Platform Admin",
  "Finance.Controller": "Financial Controller",
  "Finance.Approver": "Finance Approver",
  "AP.Clerk": "AP Clerk",
  "AP.Approver": "AP Approver",
  "Complaints.Handler": "Complaints Handler",
  "Eng.Engineer": "Engineer",
  "Eng.PM": "Product Manager",
  "KYC.Analyst": "KYC Analyst",
  "KYC.SeniorReviewer": "KYC Senior Reviewer",
  "Support.Agent": "Support Agent",
  "Support.Contractor": "Outsourced Support (EU)",
};
export const roleLabel = (r: string) => ROLE_LABELS[r] ?? humanize(r);

export const TOOL_LABELS: Record<string, string> = {
  kyc: "KYC review", refunds: "Refunds", flags: "Feature flags", complaints: "Complaints", ap: "AP invoices", core: "Platform",
};
export const toolLabel = (keyOrPrefix: string) => TOOL_LABELS[keyOrPrefix.split(".")[0]] ?? humanize(keyOrPrefix.split(".")[0]);

/** "kyc.auto_cleared" -> "Auto cleared"; "ap.bank_change.approved" -> "Bank change approved". */
export const actionLabel = (a: string) => humanize(a.split(".").slice(1).join(" ") || a);

/** "kyc_case" + "12" -> "KYC case 12". */
export const resourceLabel = (res: string, id?: string | number | null) => `${humanize(res)}${id !== undefined && id !== null && id !== "" ? ` ${id}` : ""}`;

export type Unit = "count" | "pct" | "bps" | "cents" | "bool" | "hours" | "minutes" | "days";
export type PolicyField = { key?: string; label: string; unit: Unit; suffix?: string };
export type PolicyMeta = { name: string; fields: PolicyField[] };

export const POLICY_META: Record<string, PolicyMeta> = {
  "ap.confidence_threshold": { name: "Extraction confidence threshold", fields: [{ label: "Fields below this need checking", unit: "pct" }] },
  "ap.po_tolerance_bps": { name: "PO overrun tolerance", fields: [{ label: "Allowed over PO amount", unit: "bps" }] },
  "ap.tier2_threshold_cents": { name: "Controller approval threshold", fields: [{ label: "Invoices at or above", unit: "cents" }] },
  "core.evidence_pack_max_days": { name: "Evidence pack date range limit", fields: [{ label: "Longest range", unit: "days" }] },
  "core.evidence_pack_max_events": { name: "Evidence pack size limit", fields: [{ label: "Most events per pack", unit: "count", suffix: "events" }] },
  "kyc.fastlane_criteria": {
    name: "Auto-clear criteria",
    fields: [
      { key: "max_vendor_score", label: "Highest vendor score", unit: "count" },
      { key: "max_watchlist_hits", label: "Most watchlist hits", unit: "count" },
      { key: "require_docs_verified", label: "Documents must be verified", unit: "bool" },
    ],
  },
  "kyc.qa_sample_rate": { name: "QA sample rate", fields: [{ label: "Share of auto-cleared cases sampled", unit: "pct" }] },
  "kyc.sla_hours": {
    name: "Review SLA by risk level",
    fields: [
      { key: "low", label: "Low risk", unit: "hours" },
      { key: "medium", label: "Medium risk", unit: "hours" },
      { key: "high", label: "High risk", unit: "hours" },
    ],
  },
  "refunds.approval_threshold_cents": { name: "Second-approval threshold", fields: [{ label: "Refunds above (cumulative)", unit: "cents" }] },
  "refunds.velocity": {
    name: "Refund velocity limit",
    fields: [
      { key: "max_requests", label: "Most requests per merchant", unit: "count", suffix: "requests" },
      { key: "window_minutes", label: "Within", unit: "minutes" },
    ],
  },
};

/** Fallback for a policy without explicit metadata: one field per object key, or a single scalar field. */
export function policyMeta(key: string, kind: string, value: unknown): PolicyMeta {
  if (POLICY_META[key]) return POLICY_META[key];
  const unitOf = (v: unknown): Unit => (typeof v === "boolean" ? "bool" : kind === "cents" ? "cents" : "count");
  if (value && typeof value === "object")
    return { name: humanize(key.split(".").slice(1).join(" ")), fields: Object.entries(value as Record<string, unknown>).map(([k, v]) => ({ key: k, label: humanize(k), unit: unitOf(v) })) };
  return { name: humanize(key.split(".").slice(1).join(" ")), fields: [{ label: "Value", unit: unitOf(value) }] };
}

export function formatUnit(v: unknown, f: PolicyField): string {
  if (v === null || v === undefined) return "---";
  const n = Number(v);
  switch (f.unit) {
    case "bool": return v ? "Yes" : "No";
    case "pct": return `${+(n * 100).toFixed(2)}%`;
    case "bps": return `${+(n / 100).toFixed(2)}%`;
    case "cents": return (n / 100).toLocaleString(undefined, { style: "currency", currency: "USD" });
    case "hours": return `${n.toLocaleString()} ${n === 1 ? "hour" : "hours"}`;
    case "minutes": return `${n.toLocaleString()} minutes`;
    case "days": return `${n.toLocaleString()} days`;
    default: return `${n.toLocaleString()}${f.suffix ? ` ${f.suffix}` : ""}`;
  }
}

/** Value shown in an edit input (percent for pct/bps, dollars for cents). */
export function toInput(v: unknown, f: PolicyField): string {
  const n = Number(v);
  if (f.unit === "pct") return String(+(n * 100).toFixed(4));
  if (f.unit === "bps") return String(n / 100);
  if (f.unit === "cents") return (n / 100).toFixed(2);
  return String(v ?? "");
}

export function fromInput(s: string, f: PolicyField): number {
  const n = Number(s);
  if (s.trim() === "" || Number.isNaN(n)) throw new Error(`${f.label}: enter a number`);
  if (f.unit === "pct") return +(n / 100).toFixed(6);
  if (f.unit === "bps") return Math.round(n * 100);
  if (f.unit === "cents") return Math.round(n * 100);
  return n;
}

export const inputSuffix = (f: PolicyField) => ({ pct: "%", bps: "%", cents: "USD", hours: "hours", minutes: "minutes", days: "days", count: f.suffix ?? "", bool: "" })[f.unit];
