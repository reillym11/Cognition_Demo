from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.foundation.datacls import Classification as C
from app.foundation.registry import ApprovalKind, NavItem, PolicyDef, Schedule, ToolManifest
from app.tools.kyc import seed, service
from app.tools.kyc.routes import router


class FastlaneCriteria(BaseModel):
    """Auto-clear never takes watch-list hits or unverified documents; the score stays in the low-risk band."""

    model_config = ConfigDict(extra="forbid", strict=True)
    max_vendor_score: int = Field(ge=0, le=35)
    max_watchlist_hits: int = Field(ge=0, le=0)
    require_docs_verified: Literal[True]


class SlaHours(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    low: int = Field(ge=1, le=720)
    medium: int = Field(ge=1, le=720)
    high: int = Field(ge=1, le=720)

    @model_validator(mode="after")
    def _riskier_is_faster(self) -> "SlaHours":
        if not self.high <= self.medium <= self.low:
            raise ValueError("SLA must not be longer for higher risk (high <= medium <= low)")
        return self


MANIFEST = ToolManifest(
    key="kyc",
    name="KYC review",
    description="Identity-verification review queue with four-eyes decisions and an audited auto-clear lane.",
    permissions={
        "kyc.case.read": "View KYC cases in your region (PII masked)",
        "kyc.case.work": "Claim, prepare and recommend on KYC cases",
        "kyc.decide": "Make the second-person decision on standard-risk cases",
        "kyc.decide_high": "Make the second-person decision on high-risk / escalated cases (senior)",
        "kyc.pii.reveal": "Reveal a masked PII field (audited, reason required)",
        "kyc.qa.review": "Review the random QA sample of auto-cleared cases",
        "kyc.export": "Export the KYC queue (masked)",
        "kyc.all_regions": "See cases in every region",
        "kyc.fastlane.run": "Trigger the auto-clear lane on demand",
        "kyc.policy.approve": "Approve changes to KYC policies (fast-lane criteria, QA rate, SLAs)",
    },
    grants={
        "KYC.Analyst": ["kyc.case.read", "kyc.case.work", "kyc.decide", "kyc.pii.reveal"],
        "KYC.SeniorReviewer": [
            "kyc.case.read",
            "kyc.case.work",
            "kyc.decide",
            "kyc.decide_high",
            "kyc.pii.reveal",
            "kyc.qa.review",
        ],
        "Compliance.Admin": [
            "kyc.case.read",
            "kyc.export",
            "kyc.all_regions",
            "kyc.qa.review",
            "kyc.fastlane.run",
            "kyc.policy.approve",
        ],
        "Audit.Auditor": ["kyc.case.read", "kyc.export", "kyc.all_regions"],
    },
    router=router,
    nav=[
        NavItem("/kyc", "Review queue", "kyc.case.read"),
        NavItem("/kyc/qa", "Auto-clear QA", "kyc.qa.review"),
    ],
    jobs={"kyc.fastlane": service.run_fastlane},
    schedules=[Schedule("kyc.fastlane", 60)],
    policies={
        "kyc.fastlane_criteria": PolicyDef(
            {"max_vendor_score": 20, "max_watchlist_hits": 0, "require_docs_verified": True},
            "Auto-clear lane: cases at or below these limits are cleared by system:kyc-fastlane",
            kind="json",
            schema=FastlaneCriteria,
            approver="kyc.policy.approve",
        ),
        "kyc.qa_sample_rate": PolicyDef(
            0.02, "Share of auto-cleared cases sent to human QA", kind="float", approver="kyc.policy.approve"
        ),
        "kyc.sla_hours": PolicyDef(
            {"low": 72, "medium": 48, "high": 24},
            "Review SLA by risk level (hours)",
            kind="json",
            schema=SlaHours,
            approver="kyc.policy.approve",
        ),
    },
    classifications={
        "kyc_case": {
            "applicant_name": C.PII,
            "email": C.PII,
            "dob": C.PII,
            "ssn": C.PII,
            "address": C.PII,
            "vendor_score": C.INTERNAL,
        }
    },
    approval_kinds={
        "kyc.decision": ApprovalKind(
            on_approved=service.on_decision_approved,
            on_rejected=service.on_decision_returned,
            label="KYC decision",
        )
    },
    seed=seed.seed,
    seed_order=10,
)
