from app.foundation.datacls import Classification as C
from app.foundation.registry import ApprovalKind, NavItem, PolicyDef, Schedule, ToolManifest
from app.tools.ap import seed, service
from app.tools.ap.routes import router

MANIFEST = ToolManifest(
    key="ap",
    name="AP invoices",
    description="Invoice intake with field extraction, human verification, duplicate and PO checks, tiered approvals, verified bank changes and payment batches.",
    permissions={
        "ap.read": "View invoices, vendors and bank-change requests (bank details masked)",
        "ap.upload": "Upload invoices and poll the AP inbox",
        "ap.verify": "Correct extracted fields, reject invoices and submit for approval",
        "ap.approve": "Approve invoices (first tier)",
        "ap.approve_tier2": "Approve invoices at or above the controller threshold",
        "ap.bank.request": "Request a vendor bank-detail change",
        "ap.bank.callback": "Record the out-of-band verification call-back for a bank change",
        "ap.bank.approve": "Approve a verified vendor bank-detail change",
        "ap.bank.reveal": "Reveal vendor bank details (audited)",
        "ap.batch": "Create and download payment batches",
    },
    grants={
        "AP.Clerk": ["ap.read", "ap.upload", "ap.verify", "ap.bank.request"],
        "AP.Approver": ["ap.read", "ap.approve", "ap.bank.callback"],
        "Finance.Controller": [
            "ap.read",
            "ap.approve_tier2",
            "ap.bank.approve",
            "ap.bank.reveal",
            "ap.batch",
        ],
        "Audit.Auditor": ["ap.read"],
    },
    router=router,
    nav=[
        NavItem("/ap", "AP invoices", "ap.read"),
        NavItem("/ap/bank-changes", "Vendor bank changes", "ap.read"),
    ],
    jobs={"ap.poll_inbox": service.poll_inbox},
    schedules=[Schedule("ap.poll_inbox", 60)],
    policies={
        "ap.confidence_threshold": PolicyDef(
            0.9, "Extracted fields below this confidence need a person to verify them", kind="float"
        ),
        "ap.tier2_threshold_cents": PolicyDef(
            1_000_000, "Invoices at or above this also need a financial controller", kind="cents"
        ),
        "ap.po_tolerance_bps": PolicyDef(
            200, "Allowed invoice overrun of the remaining PO value, in basis points", kind="int"
        ),
    },
    classifications={
        service.RES: {"remit_account": C.SENSITIVE, "remit_routing": C.SENSITIVE},
        service.VENDOR_RES: {"bank_account": C.SENSITIVE, "bank_routing": C.SENSITIVE},
        service.BANK_RES: {"new_account": C.SENSITIVE, "new_routing": C.SENSITIVE},
    },
    approval_kinds={
        "ap.invoice": ApprovalKind(
            on_approved=service.on_invoice_approved,
            on_rejected=service.on_invoice_rejected,
            label="Invoice approval",
        ),
        "ap.bank_change": ApprovalKind(
            on_approved=service.on_bank_approved,
            on_rejected=service.on_bank_rejected,
            label="Vendor bank change",
        ),
    },
    seed=seed.seed,
    seed_order=50,
)
