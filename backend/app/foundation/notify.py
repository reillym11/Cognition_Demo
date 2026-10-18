"""Teams notifications via the outbox (jobs). A failed webhook never rolls back the business action."""

from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.foundation import jobs
from app.foundation.datacls import redact_text
from app.foundation.settings import get_settings


def teams(db: Session, channel: str, title: str, facts: dict[str, str], link: str | None = None) -> None:
    """Callers must not pass PII; text is also pattern-redacted before sending."""
    jobs.enqueue(db, "core.notify_teams", {"channel": channel, "title": title, "facts": facts, "link": link})


def deliver(db: Session, payload: dict[str, Any]) -> None:
    card = {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "content": {
                    "type": "AdaptiveCard",
                    "version": "1.4",
                    "body": [
                        {
                            "type": "TextBlock",
                            "text": redact_text(payload["title"]),
                            "weight": "bolder",
                            "wrap": True,
                        },
                        {
                            "type": "FactSet",
                            "facts": [
                                {"title": k, "value": redact_text(str(v))}
                                for k, v in payload["facts"].items()
                            ],
                        },
                    ],
                    "actions": (
                        [
                            {
                                "type": "Action.OpenUrl",
                                "title": "Open",
                                "url": get_settings().public_base_url + payload["link"],
                            }
                        ]
                        if payload.get("link")
                        else []
                    ),
                },
            }
        ],
    }
    r = httpx.post(
        f"{get_settings().mocks_base_url}/teams/webhook/{payload['channel']}", json=card, timeout=5
    )
    r.raise_for_status()
