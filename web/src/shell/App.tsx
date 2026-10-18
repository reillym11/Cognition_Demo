import { Link, NavLink, Navigate, Route, Routes, useLocation, useSearchParams } from "react-router-dom";
import { http } from "../api/client";
import { toolRoutes } from "../tools/registry";
import { AccessPage, AuditPage, InboxPage, JobsPage, PolicyPage } from "./admin";
import { useMe } from "./me";

const LOGIN_ERRORS: Record<string, string> = {
  groups_overage:
    "Your token has no app roles and a groups overage claim (more than 200 groups). Ask IT to assign an Entra app role for this application.",
  no_roles: "You have no role in this application.",
  state_mismatch: "Sign-in session mismatch. Please try again.",
};

export function LoginPage() {
  const [sp] = useSearchParams();
  const err = sp.get("error");
  return (
    <main className="mx-auto mt-24 max-w-md space-y-4 rounded-lg border bg-white p-6 shadow">
      <h1 className="text-xl font-semibold">Internal Tools</h1>
      <p className="text-sm text-slate-600">Sign in with your organization account (local mock of Microsoft Entra ID).</p>
      {err && (
        <div role="alert" className="rounded border border-red-300 bg-red-50 p-2 text-sm text-red-800" data-testid="login-error">
          {LOGIN_ERRORS[err] ?? `Sign-in failed (${err}).`}
        </div>
      )}
      <a className="inline-block rounded bg-blue-700 px-4 py-2 text-sm font-medium text-white" href={`/api/auth/login?return_to=${encodeURIComponent(sp.get("next") ?? "/")}`}>
        Sign in with Microsoft (mock)
      </a>
    </main>
  );
}

function Home() {
  const me = useMe();
  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">Welcome, {me.data?.name}</h1>
      <p className="text-sm text-slate-600">Roles: {me.data?.roles.join(", ")}</p>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {me.data?.nav.map((n) => (
          <Link key={n.path} to={n.path} className="rounded-lg border bg-white p-4 shadow-sm hover:border-blue-500">
            <div className="text-xs uppercase text-slate-500">{n.tool_name}</div>
            <div className="font-medium">{n.label}</div>
          </Link>
        ))}
      </div>
    </div>
  );
}

export function App() {
  const me = useMe();
  const loc = useLocation();
  if (loc.pathname === "/login") return <LoginPage />;
  if (me.isLoading) return <p className="p-6 text-sm">Loading…</p>;
  if (me.error) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />;
  const groups = new Map<string, NonNullable<typeof me.data>["nav"]>();
  me.data?.nav.forEach((n) => groups.set(n.tool_name, [...(groups.get(n.tool_name) ?? []), n]));
  return (
    <div className="flex min-h-screen">
      <nav aria-label="Tools" className="w-60 shrink-0 space-y-4 border-r border-slate-200 bg-white p-4">
        <Link to="/" className="block font-semibold">Internal Tools</Link>
        <NavLink to="/inbox" className="block text-sm">Approvals inbox</NavLink>
        {[...groups.entries()].map(([tool, items]) => (
          <div key={tool}>
            <div className="text-xs font-semibold uppercase text-slate-500">{tool}</div>
            {items!.map((n) => (
              <NavLink key={n.path} to={n.path} className={({ isActive }) => `block rounded px-2 py-1 text-sm ${isActive ? "bg-blue-50 text-blue-800" : ""}`}>
                {n.label}
              </NavLink>
            ))}
          </div>
        ))}
        <div className="border-t pt-3 text-xs text-slate-600">
          <div data-testid="whoami">{me.data?.name}</div>
          <button
            className="mt-1 underline"
            onClick={async () => {
              await http("POST", "/api/auth/logout");
              window.location.href = "/login";
            }}
          >
            Sign out
          </button>
        </div>
      </nav>
      <main className="min-w-0 flex-1 p-6">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/inbox" element={<InboxPage />} />
          <Route path="/admin/audit" element={<AuditPage />} />
          <Route path="/admin/policy" element={<PolicyPage />} />
          <Route path="/admin/jobs" element={<JobsPage />} />
          <Route path="/admin/access" element={<AccessPage />} />
          {toolRoutes.map((r) => (
            <Route key={r.path} path={r.path} element={r.element} />
          ))}
          <Route path="*" element={<p>Not found</p>} />
        </Routes>
      </main>
    </div>
  );
}
