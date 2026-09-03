"""Gmail demonstrativ.

Returneaza un set fix de mesaje, cu date relative fata de momentul apelului, ca
demo-ul sa ramana relevant oricand. Interfata marcheaza contul ca „Demonstrativ",
niciodata ca „Conectat".
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from apps.core.providers.base import EmailMeta, GmailProvider, MessagePage
from apps.search.normalize import normalize

DEMO_MESSAGES: tuple[dict, ...] = (
    {
        "message_id": "demo-ana-popescu-1",
        "sender": "Ana Popescu <ana.popescu@example.com>",
        "subject": "Re: Oferta pentru proiectul Alpha",
        "snippet": "Îți trimit varianta revizuită. Aștept confirmarea ta până vineri.",
        "offset_hours": -20,
        "needs_follow_up": True,
    },
    {
        "message_id": "demo-clinica-1",
        "sender": "Clinica MedLife <programari@example.com>",
        "subject": "Confirmare programare control medical",
        "snippet": "Programarea ta este confirmată pentru vineri, ora 09:00.",
        "offset_hours": -46,
        "needs_follow_up": False,
    },
    {
        "message_id": "demo-energio-1",
        "sender": "Energio <facturi@example.com>",
        "subject": "Factura ta de energie este disponibilă",
        "snippet": "Total de plată 84,20 lei. Data limită 6 septembrie.",
        "offset_hours": -70,
        "needs_follow_up": True,
    },
    {
        "message_id": "demo-scoala-1",
        "sender": "Școala Nr. 12 <secretariat@example.com>",
        "subject": "Ședință cu părinții",
        "snippet": "Vă așteptăm luni, 27, la ora 17:30, în sala festivă.",
        "offset_hours": -96,
        "needs_follow_up": False,
    },
)


class MockGmailProvider(GmailProvider):
    name = "gmail-demo"
    is_mock = True

    def _messages(self) -> list[EmailMeta]:
        now = timezone.now()
        return [
            EmailMeta(
                message_id=item["message_id"],
                sender=item["sender"],
                subject=item["subject"],
                snippet=item["snippet"],
                received_at=now + timedelta(hours=item["offset_hours"]),
                thread_id=item["message_id"],
                needs_follow_up=item["needs_follow_up"],
            )
            for item in DEMO_MESSAGES
        ]

    def list_messages(
        self, account, *, query: str = "", cursor: str | None = None, limit: int = 25
    ) -> MessagePage:
        items = self._messages()
        if query:
            items = self._filter(items, query)
        return MessagePage(items=items[:limit], next_cursor=None)

    def search(self, account, query: str, *, limit: int = 25) -> MessagePage:
        return MessagePage(items=self._filter(self._messages(), query)[:limit], next_cursor=None)

    @staticmethod
    def _filter(items: list[EmailMeta], query: str) -> list[EmailMeta]:
        needle = normalize(query)
        if not needle:
            return items
        return [
            item
            for item in items
            if needle in normalize(f"{item.subject} {item.sender} {item.snippet}")
        ]
