"""Local mocks: KYC vendor, payment processor, Teams incoming-webhook sink, Entra directory, AP inbox.

All synthetic. Fault injection is controlled at runtime via POST /admin/faults so tests and demos can
simulate timeouts, 5xx and "succeeded but the response was lost".
"""

import json
import random
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

app = FastAPI(title="ITP mocks")

PERSONAS = Path(__file__).resolve().parents[2] / "infra/oidc/personas.json"

STATE: dict[str, Any] = {}


def reset() -> None:
    personas = json.loads(PERSONAS.read_text())["personas"]
    STATE.clear()
    STATE.update(
        directory={p["oid"]: {"accountEnabled": True, "appRoles": p.get("roles") or []} for p in personas},
        faults={},  # e.g. {"processor.refund": {"mode": "timeout_after_success", "times": 1}}
        refunds={},  # idempotency_key -> processor refund record
        teams=[],
        kyc_checks={},
        ap_inbox=[],
    )


reset()


def _fault(name: str) -> str | None:
    f = STATE["faults"].get(name)
    if not f:
        return None
    if f.get("times", 1) <= 0:
        return None
    f["times"] = f.get("times", 1) - 1
    return f["mode"]


class FaultIn(BaseModel):
    name: str
    mode: str  # error_500 | timeout | timeout_after_success
    times: int = 1


@app.post("/admin/faults")
def set_fault(f: FaultIn) -> dict[str, Any]:
    STATE["faults"][f.name] = {"mode": f.mode, "times": f.times}
    return STATE["faults"]


@app.post("/admin/reset")
def admin_reset() -> dict[str, str]:
    reset()
    return {"status": "reset"}


# ---------- Entra directory (Graph-shaped subset) ----------

@app.get("/directory/users/{oid}")
def dir_user(oid: str) -> dict[str, Any]:
    u = STATE["directory"].get(oid)
    if u is None:
        raise HTTPException(404)
    return {"id": oid, **u}


class RolesIn(BaseModel):
    appRoles: list[str] | None = None
    accountEnabled: bool | None = None


@app.patch("/directory/users/{oid}")
def dir_update(oid: str, body: RolesIn) -> dict[str, Any]:
    u = STATE["directory"].setdefault(oid, {"accountEnabled": True, "appRoles": []})
    if body.appRoles is not None:
        u["appRoles"] = body.appRoles
    if body.accountEnabled is not None:
        u["accountEnabled"] = body.accountEnabled
    return {"id": oid, **u}


# ---------- KYC vendor ----------

@app.get("/kyc-vendor/v1/checks/{applicant_ref}")
def kyc_check(applicant_ref: str) -> dict[str, Any]:
    mode = _fault("kyc.check")
    if mode == "error_500":
        raise HTTPException(500, "vendor error")
    if mode == "timeout":
        time.sleep(6)
    rnd = random.Random(applicant_ref)
    score = rnd.randint(0, 100)
    return {
        "applicant_ref": applicant_ref,
        "risk_score": score,
        "watchlist_hits": [] if rnd.random() > 0.08 else [{"list": "OFAC-SDN (synthetic)", "match": round(rnd.uniform(0.7, 0.99), 2)}],
        "documents": [{"type": t, "status": "verified" if rnd.random() > 0.15 else "unverified"} for t in ("passport", "proof_of_address")],
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


# ---------- Payment processor ----------

class RefundIn(BaseModel):
    charge_id: str
    amount_cents: int
    currency: str


@app.post("/processor/v1/refunds")
def processor_refund(body: RefundIn, request: Request) -> dict[str, Any]:
    key = request.headers.get("Idempotency-Key")
    if not key:
        raise HTTPException(400, "Idempotency-Key header required")
    if key in STATE["refunds"]:
        existing = STATE["refunds"][key]
        if existing["amount_cents"] != body.amount_cents or existing["charge_id"] != body.charge_id:
            raise HTTPException(409, "idempotency key reused with different parameters")
        return existing
    mode = _fault("processor.refund")
    if mode == "error_500":
        raise HTTPException(503, "processor unavailable")
    if mode == "timeout":
        time.sleep(6)
        raise HTTPException(504)
    rec = {"id": f"re_{len(STATE['refunds']) + 1:06d}", "charge_id": body.charge_id, "amount_cents": body.amount_cents,
           "currency": body.currency, "status": "succeeded", "idempotency_key": key}
    STATE["refunds"][key] = rec
    if mode == "timeout_after_success":
        time.sleep(6)  # refund recorded, but the caller times out and never sees the response
    return rec


@app.get("/processor/v1/refunds")
def processor_lookup(idempotency_key: str) -> dict[str, Any]:
    rec = STATE["refunds"].get(idempotency_key)
    if rec is None:
        raise HTTPException(404, "no refund for key")
    return rec


@app.get("/processor/admin/refund-count")
def processor_count(charge_id: str | None = None) -> dict[str, int]:
    recs = [r for r in STATE["refunds"].values() if charge_id is None or r["charge_id"] == charge_id]
    return {"count": len(recs)}


# ---------- Teams incoming webhook sink ----------

@app.post("/teams/webhook/{channel}")
async def teams_webhook(channel: str, request: Request) -> dict[str, str]:
    mode = _fault("teams.webhook")
    if mode == "error_500":
        raise HTTPException(500, "teams sink error")
    STATE["teams"].append({"channel": channel, "card": await request.json(), "at": time.time()})
    return {"status": "accepted"}


@app.get("/teams/messages")
def teams_messages(channel: str | None = None) -> list[dict[str, Any]]:
    return [m for m in STATE["teams"] if channel is None or m["channel"] == channel]


# ---------- AP inbox ----------

@app.post("/ap-inbox/messages")
async def ap_inbox_put(request: Request) -> dict[str, int]:
    STATE["ap_inbox"].append(await request.json())
    return {"queued": len(STATE["ap_inbox"])}


@app.post("/ap-inbox/messages/take")
def ap_inbox_take() -> list[dict[str, Any]]:
    items, STATE["ap_inbox"] = STATE["ap_inbox"], []
    return items
