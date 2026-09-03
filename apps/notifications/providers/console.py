"""Provider de notificari implicit: scrie in log, nu pretinde ca trimite push.

`supports_push()` returneaza False, iar interfata afiseaza corect starea: fara
chei VAPID nu exista notificari in browser, si nu spunem contrariul.
"""

from __future__ import annotations

import logging

from apps.core.providers.base import NotificationProvider, PushResult

logger = logging.getLogger("voicetask.notifications")


class ConsoleNotificationProvider(NotificationProvider):
    name = "notificari-consola"
    is_mock = True

    def supports_push(self) -> bool:
        return False

    def send(self, subscription, *, title: str, body: str, url: str, dedup_key: str) -> PushResult:
        # Logam doar metadate: titlul unei notificari poate contine date personale.
        logger.info("notificare pregatita dedup=%s url=%s", dedup_key, url)
        return PushResult(delivered=False, detail="Push indisponibil: provider de consolă.")
