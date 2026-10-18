"""Directory adapter: re-validates app-role assignments (models Microsoft Graph appRoleAssignments)."""

from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

import httpx

from app.foundation.settings import get_settings


@dataclass(frozen=True)
class DirectoryEntry:
    oid: str
    enabled: bool
    roles: list[str]


class Directory(Protocol):
    def lookup(self, oid: str) -> DirectoryEntry | None: ...


class HttpDirectory:
    def __init__(self, base_url: str):
        self.base_url = base_url

    def lookup(self, oid: str) -> DirectoryEntry | None:
        r = httpx.get(f"{self.base_url}/directory/users/{oid}", timeout=3)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        d = r.json()
        return DirectoryEntry(oid=oid, enabled=d["accountEnabled"], roles=d["appRoles"])


_override: Directory | None = None


def set_directory(d: Directory | None) -> None:
    global _override
    _override = d


@lru_cache
def _default() -> HttpDirectory:
    return HttpDirectory(get_settings().mocks_base_url)


def get_directory() -> Directory:
    return _override or _default()
