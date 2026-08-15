from typing import Protocol


class NotificationProvider(Protocol):
    async def send(self, *, to: str, channel: str, code: str) -> None: ...