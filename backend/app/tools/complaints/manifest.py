from app.foundation.datacls import Classification as C
from app.foundation.registry import NavItem, ToolManifest
from app.tools.complaints import seed
from app.tools.complaints.routes import router

MANIFEST = ToolManifest(
    key="complaints",
    name="Complaints",
    description="Staged complaint handling on the shared workflow engine, with a compliance branch, aging and a register export.",
    permissions={
        "complaints.read": "View complaints (PII masked)",
        "complaints.work": "Claim and progress complaints through their stages",
        "complaints.compliance_review": "Complete the compliance-review stage on regulatory complaints",
        "complaints.pii.reveal": "Reveal masked customer details (audited)",
        "complaints.export": "Export the complaint register",
    },
    grants={
        "Complaints.Handler": ["complaints.read", "complaints.work", "complaints.pii.reveal"],
        "Compliance.Admin": ["complaints.read", "complaints.compliance_review", "complaints.export"],
        "Audit.Auditor": ["complaints.read", "complaints.export"],
    },
    router=router,
    nav=[
        NavItem("/complaints", "Complaints", "complaints.read"),
    ],
    classifications={
        "complaint": {"customer_name": C.PII, "customer_email": C.PII, "description": C.INTERNAL}
    },
    seed=seed.seed,
    seed_order=40,
)
