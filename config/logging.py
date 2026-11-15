"""One JSON object per log line, so Render's log search can filter on fields.

Never log secrets, learner questions or learner code. As a safety net, the redact filter
replaces the values of the secret settings if one ever ends up in a message.
"""

import json
import logging
from datetime import datetime, timezone

SECRET_SETTINGS = (
    "SECRET_KEY", "GOOGLE_CLIENT_SECRET", "GROQ_API_KEY", "CF_API_TOKEN", "EMAIL_HOST_PASSWORD", "DATABASE_URL",
)


class JsonFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            "time": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(timespec="seconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["error"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


class RedactSecrets(logging.Filter):
    def filter(self, record):
        from django.conf import settings

        secrets = [str(getattr(settings, name, "") or "") for name in SECRET_SETTINGS]
        message = record.getMessage()
        for secret in secrets:
            if len(secret) >= 8 and secret in message:
                message = message.replace(secret, "[redacted]")
        record.msg, record.args = message, None
        return True
