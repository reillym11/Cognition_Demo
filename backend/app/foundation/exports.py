"""Audited, masked CSV exports."""

import csv
import io
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.foundation import audit
from app.foundation.authz import Principal
from app.foundation.datacls import mask_record
from app.foundation.errors import Invalid, require_reason

MAX_ROWS = 50_000


def csv_export(
    db: Session,
    actor: Principal,
    *,
    resource: str,
    rows: Iterable[dict[str, Any]],
    columns: list[str],
    filename: str,
    reason: str | None,
    chain: str,
    filters: dict[str, Any],
) -> Response:
    reason = require_reason(reason, "an export")
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=columns, extrasaction="ignore")
    w.writeheader()
    n = 0
    for r in rows:
        n += 1
        if n > MAX_ROWS:
            raise Invalid(f"export exceeds {MAX_ROWS} rows; narrow the filters")
        masked = mask_record(resource, r)
        w.writerow({k: _cell(masked.get(k)) for k in columns})
    audit.record(
        db,
        actor,
        "export.csv",
        resource,
        filename,
        chain=chain,
        reason=reason,
        after={"rows": n, "filters": filters, "columns": columns},
    )
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return Response(
        buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}-{stamp}.csv"'},
    )


def _cell(v: Any) -> Any:
    # Neutralize spreadsheet formula injection.
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v
