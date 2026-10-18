"""Generate the mock IdP persona login page from infra/oidc/personas.json."""

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TENANT = "11111111-2222-4333-8444-555555555555"


def claims_for(p: dict) -> dict:
    c = {
        "oid": p["oid"],
        "tid": TENANT,
        "name": p["name"],
        "preferred_username": f"{p['username']}@contoso-fintech.test",
        "region": p["region"],
    }
    if p.get("overage"):
        c["_claim_names"] = {"groups": "src1"}
        c["_claim_sources"] = {"src1": {"endpoint": f"https://graph.microsoft.com/v1.0/users/{p['oid']}/getMemberObjects"}}
    elif p.get("roles"):
        c["roles"] = p["roles"]
    return c


def main() -> None:
    personas = json.loads((ROOT / "infra/oidc/personas.json").read_text())["personas"]
    buttons = []
    for p in personas:
        claims = html.escape(json.dumps(claims_for(p)), quote=True)
        roles = ", ".join(p.get("roles") or ["(groups overage)"])
        buttons.append(
            f'<form method="post"><input type="hidden" name="username" value="{html.escape(p["oid"])}">'
            f'<input type="hidden" name="claims" value="{claims}">'
            f'<button type="submit" data-persona="{html.escape(p["username"])}"><strong>{html.escape(p["name"])}</strong>'
            f'<span>{html.escape(p["persona"])}</span><code>{html.escape(roles)}</code></button></form>'
        )
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Mock Entra ID sign-in</title>
<style>body{{font-family:system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem;color:#1b1f24}}
h1{{font-size:1.3rem}}p{{color:#57606a}}.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:.6rem}}
button{{width:100%;text-align:left;padding:.6rem .8rem;border:1px solid #d0d7de;border-radius:8px;background:#fff;cursor:pointer;display:flex;flex-direction:column;gap:.2rem}}
button:hover,button:focus{{border-color:#0969da;outline:2px solid #0969da33}}span{{font-size:.85rem;color:#57606a}}code{{font-size:.75rem;color:#0a3069}}</style></head>
<body><h1>Mock Entra ID &mdash; choose a synthetic persona</h1>
<p>Local mock identity provider (mock-oauth2-server). Tokens carry Entra-shaped claims (<code>oid</code>, <code>tid</code>, app <code>roles</code>). No passwords.</p>
<div class="grid">{''.join(buttons)}</div></body></html>
"""
    (ROOT / "infra/oidc/login.html").write_text(page)


if __name__ == "__main__":
    main()
