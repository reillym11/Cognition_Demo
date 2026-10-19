"""Tool manifests and the registry the host builds at startup.

A tool is a package under app/tools/<key>/ exposing `MANIFEST` in manifest.py. The host discovers
tools by scanning that package, so adding a tool never edits host code.
"""

import importlib
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.foundation.datacls import Classification


@dataclass(frozen=True)
class NavItem:
    path: str
    label: str
    permission: str


@dataclass(frozen=True)
class Schedule:
    job_kind: str
    every_seconds: int


POLICY_KINDS = ("int", "cents", "float", "json")


@dataclass(frozen=True)
class PolicyDef:
    """`approver` is the permission whose holders may approve a change (namespaced under the owning tool).

    kind="json" policies must declare a pydantic `schema`; values are validated against it on change and on read.
    """

    default: Any
    description: str
    kind: str = "int"  # int | cents | float | json
    schema: type[BaseModel] | None = None
    approver: str = ""


@dataclass(frozen=True)
class ApprovalKind:
    """Hooks run inside the deciding transaction once a request closes.

    `can_view(db, req, principal)` applies the tool's row scope to the request's subject; approvers who can't
    see the subject can't list, read or decide the request.
    """

    on_approved: Callable[[Session, Any], None]
    on_rejected: Callable[[Session, Any], None] | None = None
    label: str = ""
    can_view: Callable[[Session, Any, Any], bool] | None = None


@dataclass
class ToolManifest:
    key: str
    name: str
    description: str
    permissions: dict[str, str]
    grants: dict[str, list[str]]
    router: APIRouter | None = None
    nav: list[NavItem] = field(default_factory=list)
    jobs: dict[str, Callable[[Session, dict[str, Any]], None]] = field(default_factory=dict)
    schedules: list[Schedule] = field(default_factory=list)
    policies: dict[str, PolicyDef] = field(default_factory=dict)
    classifications: dict[str, dict[str, Classification]] = field(default_factory=dict)
    approval_kinds: dict[str, ApprovalKind] = field(default_factory=dict)
    seed: Callable[[Session, int], None] | None = None
    seed_order: int = 100


class Registry:
    def __init__(self, manifests: list[ToolManifest]):
        keys = [m.key for m in manifests]
        if len(set(keys)) != len(keys):
            raise RuntimeError(f"duplicate tool keys: {keys}")
        self.manifests = manifests
        self.permissions: dict[str, str] = {}
        self.role_permissions: dict[str, set[str]] = {}
        self.jobs: dict[str, Callable[[Session, dict[str, Any]], None]] = {}
        self.policies: dict[str, PolicyDef] = {}
        self.classifications: dict[str, dict[str, Classification]] = {}
        self.approval_kinds: dict[str, ApprovalKind] = {}
        for m in manifests:
            for p, desc in m.permissions.items():
                if not p.startswith(m.key + "."):
                    raise RuntimeError(f"permission {p!r} must be namespaced under {m.key!r}")
                self.permissions[p] = desc
            for kind, fn in m.jobs.items():
                self._unique(self.jobs, kind, fn, "job")
            for k, pdef in m.policies.items():
                self._unique(self.policies, k, pdef, "policy")
            for res, fields in m.classifications.items():
                self._unique(self.classifications, res, fields, "classification")
            for kind, ak in m.approval_kinds.items():
                self._unique(self.approval_kinds, kind, ak, "approval kind")
        for m in manifests:
            for role, perms in m.grants.items():
                for p in perms:
                    if p not in self.permissions:
                        raise RuntimeError(f"tool {m.key} grants unknown permission {p!r}")
                self.role_permissions.setdefault(role, set()).update(perms)
        for m in manifests:
            for k, pdef in m.policies.items():
                self._check_policy(m.key, k, pdef)

    def _check_policy(self, tool: str, key: str, d: PolicyDef) -> None:
        if not key.startswith(tool + "."):
            raise RuntimeError(f"policy {key!r} must be namespaced under {tool!r}")
        if d.kind not in POLICY_KINDS:
            raise RuntimeError(f"policy {key!r} has unknown kind {d.kind!r}")
        if not d.approver.startswith(tool + ".") or d.approver not in self.permissions:
            raise RuntimeError(f"policy {key!r} needs an approver permission declared by {tool!r}")
        if not any(d.approver in perms for perms in self.role_permissions.values()):
            raise RuntimeError(f"policy {key!r} approver {d.approver!r} is not granted to any role")
        if d.kind == "json":
            if d.schema is None:
                raise RuntimeError(f"json policy {key!r} must declare a schema")
            try:
                d.schema.model_validate(d.default)
            except ValidationError as e:
                raise RuntimeError(f"policy {key!r} default does not match its schema: {e}") from None

    @staticmethod
    def _unique(d: dict[str, Any], k: str, v: Any, what: str) -> None:
        if k in d:
            raise RuntimeError(f"duplicate {what} {k!r}")
        d[k] = v

    def permissions_for(self, roles: frozenset[str]) -> frozenset[str]:
        out: set[str] = set()
        for r in roles:
            out |= self.role_permissions.get(r, set())
        return frozenset(out)


def discover() -> list[ToolManifest]:
    import app.tools
    from app.foundation.core_manifest import MANIFEST as CORE

    found = [CORE]
    for mod in sorted(pkgutil.iter_modules(app.tools.__path__), key=lambda m: m.name):
        if not mod.ispkg:
            continue
        manifest_mod = importlib.import_module(f"app.tools.{mod.name}.manifest")
        found.append(manifest_mod.MANIFEST)
    return found


_registry: Registry | None = None


def get_registry() -> Registry:
    global _registry
    if _registry is None:
        _registry = Registry(discover())
    return _registry
