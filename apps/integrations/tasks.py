"""Sincronizarea periodica a conturilor conectate."""

from __future__ import annotations

import logging

from celery import shared_task

from apps.integrations.models import ConnectedAccount
from apps.integrations.sync import sync_calendar, sync_emails

logger = logging.getLogger("voicetask.integrations")


@shared_task(name="integrations.sync_all_accounts", ignore_result=True)
def sync_all_accounts() -> int:
    synced = 0
    accounts = ConnectedAccount.objects.filter(
        status__in=[ConnectedAccount.Status.CONNECTED, ConnectedAccount.Status.MOCK]
    ).select_related("owner")
    for account in accounts:
        if account.provider == ConnectedAccount.Provider.GMAIL:
            result = sync_emails(account.owner, account)
        else:
            result = sync_calendar(account.owner, account)
        if result.ok:
            synced += 1
    return synced


@shared_task(name="integrations.sync_account", ignore_result=True)
def sync_account(account_id: int) -> bool:
    account = ConnectedAccount.objects.filter(pk=account_id).select_related("owner").first()
    if account is None:
        return False
    result = (
        sync_emails(account.owner, account)
        if account.provider == ConnectedAccount.Provider.GMAIL
        else sync_calendar(account.owner, account)
    )
    return result.ok
