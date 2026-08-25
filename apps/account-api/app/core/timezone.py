from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.core.config import settings

_API_TZ = ZoneInfo(settings.api_timezone)


def to_api_tz(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_API_TZ)
