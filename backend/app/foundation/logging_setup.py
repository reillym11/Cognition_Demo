import json
import logging
import sys
from datetime import UTC, datetime

from app.foundation.datacls import redact_text
from app.foundation.request_context import current_request_id

_STD = set(vars(logging.LogRecord("", 0, "", 0, "", None, None)).keys()) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out = {
            "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": current_request_id(),
        }
        for k, v in record.__dict__.items():
            if k not in _STD:
                out[k] = v
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return redact_text(json.dumps(out, default=str))


def configure(level: int = logging.INFO) -> None:
    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [h]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").disabled = True
