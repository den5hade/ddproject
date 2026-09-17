from typing import Protocol


class NotificationProvider(Protocol):
    async def send(self, *, to: str, channel: str, code: str) -> None: ...

    async def send_message(
        self, *, to: str, channel: str, subject: str, body: str
    ) -> None: ...