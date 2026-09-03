"""Web Push real, prin VAPID.

Nu poate fi verificat pe masina de dezvoltare: are nevoie de HTTPS si de un
serviciu de push al browserului. Codul este scris complet; activarea se face
setand VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY si
PROVIDER_NOTIFICATION=apps.notifications.providers.webpush.WebPushProvider
"""

from __future__ import annotations

import json
import logging

from django.conf import settings

from apps.core.providers.base import NotificationProvider, ProviderUnavailable, PushResult

logger = logging.getLogger("voicetask.notifications")

#: Codurile prin care serviciul de push spune ca abonamentul nu mai exista.
GONE_STATUS = {404, 410}


class WebPushProvider(NotificationProvider):
    name = "webpush"

    def is_available(self) -> bool:
        return bool(settings.VAPID_PRIVATE_KEY and settings.VAPID_PUBLIC_KEY)

    def supports_push(self) -> bool:
        return self.is_available()

    def send(self, subscription, *, title: str, body: str, url: str, dedup_key: str) -> PushResult:
        if not self.is_available():
            raise ProviderUnavailable("Cheile VAPID nu sunt configurate.")
        try:
            from pywebpush import WebPushException, webpush
        except ImportError as exc:  # pragma: no cover
            raise ProviderUnavailable("Pachetul pywebpush nu este instalat.") from exc

        payload = json.dumps(
            {"title": title, "body": body, "url": url, "dedup_key": dedup_key},
            ensure_ascii=False,
        )
        try:
            webpush(
                subscription_info=subscription.as_subscription_info(),
                data=payload,
                vapid_private_key=settings.VAPID_PRIVATE_KEY,
                vapid_claims={"sub": f"mailto:{settings.VAPID_CONTACT_EMAIL}"},
                timeout=settings.PROVIDER_TIMEOUT_SECONDS,
            )
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in GONE_STATUS:
                subscription.is_active = False
                subscription.save(update_fields=["is_active", "updated_at"])
                return PushResult(delivered=False, detail="Abonament expirat.")
            logger.warning("push esuat dedup=%s status=%s", dedup_key, status)
            return PushResult(delivered=False, detail=f"Eroare push ({status}).")
        return PushResult(delivered=True)
