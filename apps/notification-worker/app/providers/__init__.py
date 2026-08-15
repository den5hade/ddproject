from app.config import settings
from app.providers.base import NotificationProvider

_provider: NotificationProvider | None = None


def get_provider() -> NotificationProvider:
    global _provider
    if _provider is None:
        if settings.notification_provider == "smtp":
            from app.providers.smtp import build_provider
        else:
            from app.providers.console import build_provider
        _provider = build_provider()
    return _provider


__all__ = ["get_provider", "NotificationProvider"]