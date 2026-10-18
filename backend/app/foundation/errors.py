class DomainError(Exception):
    """Business-rule violation surfaced to the client with a stable code."""

    status_code = 400

    def __init__(self, message: str, *, code: str = "domain_error", status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        if status_code is not None:
            self.status_code = status_code


class Forbidden(DomainError):
    status_code = 403


class Conflict(DomainError):
    status_code = 409


class NotFound(DomainError):
    status_code = 404


class Invalid(DomainError):
    status_code = 422


def require_reason(reason: str | None, what: str = "this action") -> str:
    r = (reason or "").strip()
    if len(r) < 3:
        raise Invalid(f"a reason is required for {what}", code="reason_required")
    return r
