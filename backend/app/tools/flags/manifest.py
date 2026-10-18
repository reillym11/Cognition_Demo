from app.foundation.registry import ApprovalKind, NavItem, Schedule, ToolManifest
from app.tools.flags import seed, service
from app.tools.flags.routes import router

MANIFEST = ToolManifest(
    key="flags",
    name="Feature flags",
    description="Thin flag admin: per-env rollout and targeting, prod changes need a second person, full history.",
    permissions={
        "flags.read": "View flags and their change history",
        "flags.create": "Create flags (start disabled everywhere)",
        "flags.edit": "Change dev/staging flag state",
        "flags.prod.request": "Request a production flag change",
        "flags.prod.approve": "Approve production flag changes",
        "flags.evaluate": "Call the evaluation endpoint",
    },
    grants={
        "Eng.Engineer": ["flags.read", "flags.create", "flags.edit", "flags.prod.request", "flags.evaluate"],
        "Eng.PM": ["flags.read", "flags.edit", "flags.prod.request", "flags.evaluate"],
        "Platform.Admin": ["flags.read", "flags.prod.approve", "flags.evaluate"],
        "Audit.Auditor": ["flags.read"],
    },
    router=router,
    nav=[NavItem("/flags", "Feature flags", "flags.read")],
    jobs={"flags.stale_report": service.stale_report},
    schedules=[Schedule("flags.stale_report", 86_400)],
    approval_kinds={
        "flags.prod_change": ApprovalKind(
            on_approved=service.on_prod_approved, label="Production flag change"
        )
    },
    seed=seed.seed,
    seed_order=30,
)
