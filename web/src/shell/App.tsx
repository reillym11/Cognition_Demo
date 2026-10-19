import { Avatar, Body1, Caption1, Card, Field, Menu, MenuItem, MenuList, MenuPopover, MenuTrigger, Select, Subtitle1, Title3, makeStyles, mergeClasses, tokens } from "@fluentui/react-components";
import {
  ArrowUndo20Regular, ChatWarning20Regular, DocumentText20Regular, Flag20Regular, Home20Regular, MailInbox20Regular,
  PersonSearch20Regular, ShieldCheckmark20Regular, SignOut20Regular,
} from "@fluentui/react-icons";
import { useState, type ReactElement } from "react";
import { Link, NavLink, Navigate, Route, Routes, useLocation, useSearchParams } from "react-router-dom";
import { http } from "../api/client";
import { toolRoutes } from "../tools/registry";
import { ErrorBox } from "../ui/kit";
import { AccessPage, AuditPage, InboxPage, JobsPage, PolicyPage } from "./admin";
import { useMe } from "./me";
import { PERSONAS } from "./personas.gen";

const LOGIN_ERRORS: Record<string, string> = {
  groups_overage:
    "Your token has no app roles and a groups overage claim (more than 200 groups). Ask IT to assign an Entra app role for this application.",
  no_roles: "You have no role in this application.",
  state_mismatch: "Sign-in session mismatch. Please try again.",
  signin_busy: "Too many sign-ins are in progress. Please try again in a few minutes.",
};

const ICONS: [string, ReactElement][] = [
  ["/kyc", <PersonSearch20Regular />], ["/refunds", <ArrowUndo20Regular />], ["/flags", <Flag20Regular />],
  ["/complaints", <ChatWarning20Regular />], ["/ap", <DocumentText20Regular />], ["/admin", <ShieldCheckmark20Regular />],
];
const iconFor = (path: string) => ICONS.find(([p]) => path.startsWith(p))?.[1] ?? <Home20Regular />;

const useStyles = makeStyles({
  header: {
    display: "flex", alignItems: "center", justifyContent: "space-between", height: "48px", padding: "0 16px",
    backgroundColor: tokens.colorBrandBackground, color: tokens.colorNeutralForegroundOnBrand,
  },
  brand: { color: tokens.colorNeutralForegroundOnBrand, textDecorationLine: "none", fontWeight: tokens.fontWeightSemibold, fontSize: tokens.fontSizeBase400 },
  sitemap: {
    width: "232px", flexShrink: 0, padding: "8px 0", backgroundColor: tokens.colorNeutralBackground1,
    borderRight: `1px solid ${tokens.colorNeutralStroke2}`, overflowY: "auto",
  },
  group: {
    padding: "12px 16px 4px", fontSize: tokens.fontSizeBase200, fontWeight: tokens.fontWeightSemibold, color: tokens.colorNeutralForeground3,
  },
  item: {
    display: "flex", alignItems: "center", gap: "10px", padding: "6px 16px", margin: "1px 4px", borderRadius: tokens.borderRadiusMedium,
    color: tokens.colorNeutralForeground1, textDecorationLine: "none", fontSize: tokens.fontSizeBase300,
    ":hover": { backgroundColor: tokens.colorNeutralBackground1Hover },
  },
  active: {
    backgroundColor: tokens.colorNeutralBackground1Selected, fontWeight: tokens.fontWeightSemibold,
    boxShadow: `inset 3px 0 0 ${tokens.colorBrandStroke1}`,
  },
  login: { width: "420px", padding: "32px", margin: "0 auto" },
  loginMain: { paddingTop: "96px" },
  signIn: {
    display: "inline-flex", alignItems: "center", padding: "6px 16px", borderRadius: tokens.borderRadiusMedium,
    backgroundColor: tokens.colorBrandBackground, color: tokens.colorNeutralForegroundOnBrand, textDecorationLine: "none",
    fontWeight: tokens.fontWeightSemibold, ":hover": { backgroundColor: tokens.colorBrandBackgroundHover },
  },
  tile: { padding: "16px", textDecorationLine: "none", color: "inherit" },
  muted: { color: tokens.colorNeutralForeground3 },
});

const PERSONA_GROUPS = [...new Set(PERSONAS.map((p) => p.group))];

export function LoginPage() {
  const s = useStyles();
  const [sp] = useSearchParams();
  const [who, setWho] = useState(PERSONAS[0].username);
  const err = sp.get("error");
  const chosen = PERSONAS.find((p) => p.username === who);
  const href = `/api/auth/login?return_to=${encodeURIComponent(sp.get("next") ?? "/")}&login_hint=${encodeURIComponent(who)}`;
  return (
    <main className={s.loginMain}>
      <Card className={mergeClasses(s.login, "space-y-4")}>
        <Title3 as="h1">Internal Tools</Title3>
        <Body1>Choose a role to sign in. Demo environment, synthetic data only.</Body1>
        {err && (
          <div data-testid="login-error">
            <ErrorBox error={LOGIN_ERRORS[err] ?? `Sign-in failed (${err}).`} />
          </div>
        )}
        <Field label="Sign in as" hint={chosen?.description}>
          <Select value={who} onChange={(_, d) => setWho(d.value)}>
            {PERSONA_GROUPS.map((g) => (
              <optgroup key={g} label={g}>
                {PERSONAS.filter((p) => p.group === g).map((p) => (
                  <option key={p.username} value={p.username}>{p.name}</option>
                ))}
              </optgroup>
            ))}
          </Select>
        </Field>
        <div>
          <a className={s.signIn} href={href}>Sign in</a>
        </div>
      </Card>
    </main>
  );
}

function Home() {
  const s = useStyles();
  const me = useMe();
  return (
    <div className="space-y-4">
      <Title3 as="h1" block>Welcome, {me.data?.name}</Title3>
      <Caption1 className={s.muted}>Roles: {me.data?.roles.join(", ")}</Caption1>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {me.data?.nav.map((n) => (
          <Card key={n.path} className={s.tile} as="div">
            <Link to={n.path} className="flex items-center gap-3" style={{ color: "inherit", textDecoration: "none" }}>
              {iconFor(n.path)}
              <div>
                <Caption1 className={s.muted} block>{n.tool_name}</Caption1>
                <Subtitle1>{n.label}</Subtitle1>
              </div>
            </Link>
          </Card>
        ))}
      </div>
    </div>
  );
}

export function App() {
  const s = useStyles();
  const me = useMe();
  const loc = useLocation();
  if (loc.pathname === "/login") return <LoginPage />;
  if (me.isLoading) return <p className="p-6 text-sm">Loading…</p>;
  if (me.error) return <Navigate to={`/login?next=${encodeURIComponent(loc.pathname + loc.search)}`} replace />;
  const groups = new Map<string, NonNullable<typeof me.data>["nav"]>();
  me.data?.nav.forEach((n) => groups.set(n.tool_name, [...(groups.get(n.tool_name) ?? []), n]));
  const item = ({ isActive }: { isActive: boolean }) => mergeClasses(s.item, isActive && s.active);
  return (
    <div className="flex min-h-screen flex-col">
      <header className={s.header}>
        <Link to="/" className={s.brand}>Internal Tools</Link>
        <Menu>
          <MenuTrigger disableButtonEnhancement>
            <button className="flex items-center gap-2" aria-label="Account">
              <span data-testid="whoami">{me.data?.name}</span>
              <Avatar size={28} name={me.data?.name} color="neutral" />
            </button>
          </MenuTrigger>
          <MenuPopover>
            <MenuList>
              <MenuItem icon={<SignOut20Regular />} onClick={async () => { await http("POST", "/api/auth/logout"); window.location.href = "/login"; }}>
                Sign out
              </MenuItem>
            </MenuList>
          </MenuPopover>
        </Menu>
      </header>
      <div className="flex min-h-0 flex-1">
        <nav aria-label="Tools" className={s.sitemap}>
          <NavLink to="/" end className={item}><Home20Regular /> Home</NavLink>
          <NavLink to="/inbox" className={item}><MailInbox20Regular /> Approvals inbox</NavLink>
          {[...groups.entries()].map(([tool, items]) => (
            <div key={tool}>
              <div className={s.group}>{tool}</div>
              {items!.map((n) => (
                <NavLink key={n.path} to={n.path} end className={item}>
                  {iconFor(n.path)} {n.label}
                </NavLink>
              ))}
            </div>
          ))}
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
    </div>
  );
}
