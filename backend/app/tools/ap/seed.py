"""Vendors, POs and ~60 synthetic invoice PDFs pushed through the real intake path (clean, low-confidence,
duplicate, changed bank details, unknown PO)."""

import random
from datetime import timedelta

from faker import Faker
from sqlalchemy.orm import Session

from app.foundation.authz import system_principal
from app.foundation.db import utcnow
from app.tools.ap import pdfgen, service
from app.tools.ap.models import PurchaseOrder, Vendor

ITEMS = [
    "Consulting hours",
    "Cloud hosting",
    "Card stock",
    "Security audit",
    "Legal review",
    "Office supplies",
    "Data feed licence",
]


def seed(db: Session, scale: float = 1.0) -> None:
    rng = random.Random(5)
    fake = Faker()
    Faker.seed(5)
    vendors = []
    for i in range(40):
        v = Vendor(
            code=f"V{1000 + i}",
            name=f"{fake.unique.company()}",
            phone_on_file=f"+1-555-01{i:02d}",
            bank_name=rng.choice(["First Synthetic Bank", "Example Trust", "Demo Credit Union"]),
            bank_account=str(rng.randint(10**9, 10**10 - 1)),
            bank_routing=f"0{rng.randint(10**7, 10**8 - 1)}",
        )
        db.add(v)
        vendors.append(v)
    db.flush()
    pos = []
    for i in range(200):
        po = PurchaseOrder(
            po_number=f"PO-{50000 + i}",
            vendor_id=rng.choice(vendors).id,
            amount_cents=rng.randint(5, 400) * 10_000,
        )
        db.add(po)
        pos.append(po)
    db.flush()
    actor = system_principal("seed")
    today = utcnow().date()
    by_id = {v.id: v for v in vendors}
    made: list[bytes] = []
    for n in range(max(6, int(60 * scale))):
        po = rng.choice(pos)
        v = by_id[po.vendor_id]
        kind = rng.choices(["clean", "garbled", "dup", "bank", "nopo"], [70, 10, 8, 7, 5])[0]
        if kind == "dup" and made:
            service.ingest(db, actor, f"dup-{n}.pdf", rng.choice(made), "inbox")
            continue
        budget = max(10_000, po.amount_cents // 3)
        items = [
            (rng.choice(ITEMS), rng.randint(1, 5), rng.randint(20, max(21, budget // 500)) * 100)
            for _ in range(rng.randint(1, 3))
        ]
        d = today - timedelta(days=rng.randint(0, 40))
        pdf = pdfgen.invoice_pdf(
            vendor=v.name,
            invoice_number=f"INV-{v.code}-{n:04d}",
            invoice_date=d.isoformat(),
            due_date=(d + timedelta(days=30)).isoformat(),
            po_number=None if kind == "nopo" else po.po_number,
            items=items,
            tax_cents=sum(q * u for _, q, u in items) // 20,
            bank_name=v.bank_name,
            account=str(rng.randint(10**9, 10**10 - 1)) if kind == "bank" else v.bank_account,
            routing=v.bank_routing,
            garble=rng.sample(["total", "invoice_date", "remit_account"], 1) if kind == "garbled" else (),
        )
        made.append(pdf)
        service.ingest(db, actor, f"invoice-{n}.pdf", pdf, rng.choice(["upload", "inbox"]))
