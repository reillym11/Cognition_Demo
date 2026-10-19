from app.foundation.datacls import Classification as C
from app.foundation.registry import ApprovalKind, NavItem, PolicyDef, Schedule, ToolManifest
from app.tools.refunds import seed, service
from app.tools.refunds.routes import router

MANIFEST = ToolManifest(
    key="refunds",
    name="Refunds",
    description="Refund requests with cumulative caps, a second approver over threshold, and safe processor retries.",
    permissions={
        "refunds.read": "View transactions and refunds in your region (customer PII masked)",
        "refunds.all_regions": "See transactions and refunds for merchants in every region",
        "refunds.request": "Request a refund",
        "refunds.request.direct": "Refunds under the threshold execute without a second person",
        "refunds.approve": "Approve refunds that need a second person",
        "refunds.pii.reveal": "Reveal masked customer fields (audited, reason required)",
        "refunds.reconcile": "Trigger reconciliation of refunds with an unknown processor outcome",
        "refunds.export": "Export refunds",
    },
    grants={
        "Support.Agent": [
            "refunds.read",
            "refunds.all_regions",
            "refunds.request",
            "refunds.request.direct",
            "refunds.pii.reveal",
        ],
        "Support.Contractor": ["refunds.read", "refunds.request"],
        "Finance.Approver": ["refunds.read", "refunds.all_regions", "refunds.approve", "refunds.export"],
        "Finance.Controller": ["refunds.read", "refunds.all_regions", "refunds.export", "refunds.reconcile"],
        "Audit.Auditor": ["refunds.read", "refunds.all_regions", "refunds.export"],
    },
    router=router,
    nav=[
        NavItem("/refunds", "Refund requests", "refunds.read"),
        NavItem("/refunds/transactions", "Transactions", "refunds.read"),
    ],
    jobs={
        "refunds.execute": service.execute,
        "refunds.reconcile": service.reconcile,
        "refunds.reconcile_sweep": service.reconcile_sweep,
    },
    schedules=[Schedule("refunds.reconcile_sweep", 300)],
    policies={
        "refunds.approval_threshold_cents": PolicyDef(
            50_000, "Cumulative refunds on one charge above this need a Finance approver", kind="cents"
        ),
        "refunds.velocity": PolicyDef(
            {"window_minutes": 60, "max_requests": 10},
            "Requests per person per window before refunds are flagged and need approval",
            kind="json",
        ),
    },
    classifications={"refund_transaction": {"customer_name": C.PII, "customer_email": C.PII}},
    approval_kinds={
        "refunds.refund": ApprovalKind(
            on_approved=service.on_approved, on_rejected=service.on_rejected, label="Refund over threshold"
        )
    },
    seed=seed.seed,
    seed_order=20,
)
