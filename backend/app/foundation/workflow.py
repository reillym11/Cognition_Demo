"""Small reusable stage engine: ordered stages with required fields, checklists, per-stage SLA, an optional
completer permission, separation from earlier stages, and one level of conditional branching.
Deliberately not BPMN: no parallel stages, loops or visual designer. Tools own persistence."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.foundation.authz import Principal
from app.foundation.errors import Forbidden, Invalid


@dataclass(frozen=True)
class StageDef:
    key: str
    label: str
    sla_hours: int
    required_fields: tuple[str, ...] = ()
    checklist: tuple[str, ...] = ()
    permission: str | None = None
    separate_from: tuple[str, ...] = ()  # whoever completed these stages may not complete this one


@dataclass(frozen=True)
class Branch:
    after: str
    when: Callable[[dict[str, Any]], bool]
    insert: tuple[StageDef, ...]
    label: str = ""


@dataclass(frozen=True)
class WorkflowDef:
    key: str
    stages: tuple[StageDef, ...]
    branches: tuple[Branch, ...] = field(default=())

    def __post_init__(self) -> None:
        keys = [s.key for s in self.stages] + [s.key for b in self.branches for s in b.insert]
        if len(keys) != len(set(keys)):
            raise ValueError(f"workflow {self.key}: duplicate stage keys")
        for b in self.branches:
            if b.after not in {s.key for s in self.stages}:
                raise ValueError(f"workflow {self.key}: branch after unknown stage {b.after!r}")

    def path(self, data: dict[str, Any]) -> list[StageDef]:
        out: list[StageDef] = []
        for s in self.stages:
            out.append(s)
            for b in self.branches:
                if b.after == s.key and b.when(data):
                    out.extend(b.insert)
        return out

    def stage(self, key: str) -> StageDef:
        for s in [*self.stages, *(x for b in self.branches for x in b.insert)]:
            if s.key == key:
                return s
        raise Invalid(f"unknown stage {key!r}")

    def next_after(self, key: str, data: dict[str, Any]) -> StageDef | None:
        p = self.path(data)
        keys = [s.key for s in p]
        if key not in keys:
            raise Invalid(f"stage {key!r} is not on this case's path")
        i = keys.index(key)
        return p[i + 1] if i + 1 < len(p) else None


def missing(stage: StageDef, data: dict[str, Any], checks: dict[str, bool]) -> list[str]:
    out = [f for f in stage.required_fields if data.get(f) in (None, "", [])]
    out += [f"checklist:{c}" for c in stage.checklist if not checks.get(c)]
    return out


def advance(
    wf: WorkflowDef,
    current: str,
    data: dict[str, Any],
    checks: dict[str, bool],
    completers: dict[str, str],
    actor: Principal,
    now: datetime,
) -> tuple[StageDef | None, datetime | None]:
    """Validate completion of `current` by `actor`; return (next stage or None if finished, its due time)."""
    st = wf.stage(current)
    if st.permission and not actor.has(st.permission):
        raise Forbidden(f"stage '{st.label}' must be completed by someone with {st.permission}")
    for prior in st.separate_from:
        if completers.get(prior) == actor.oid:
            raise Forbidden(
                f"you completed '{wf.stage(prior).label}', so someone else must complete '{st.label}'",
                code="sod_violation",
            )
    gaps = missing(st, data, checks)
    if gaps:
        raise Invalid(f"stage '{st.label}' is missing: {', '.join(gaps)}", code="stage_incomplete")
    nxt = wf.next_after(current, data)
    return nxt, (now + timedelta(hours=nxt.sla_hours) if nxt else None)
