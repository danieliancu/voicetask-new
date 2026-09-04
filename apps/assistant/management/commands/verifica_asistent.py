"""Verificare manuala a asistentului cu providerii configurati.

Testele automate ruleaza pe un model simulat: sunt rapide, deterministe si nu
consuma credit, dar nu spun nimic despre ce raspunde OpenAI la o fraza reala.
Comanda aceasta trece frazele problematice prin providerul configurat efectiv si
arata schita reconciliata, ca diferenta dintre model si parserul determinist sa se
vada, nu sa se presupuna.

    python manage.py verifica_asistent --user danii

Nu scrie nimic in baza de date: tot ce creeaza se anuleaza la final. Nu afiseaza
cheia API si nu salveaza transcrierile nicaieri.
"""

from __future__ import annotations

import contextlib
import sys

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import UserPreference
from apps.assistant import clarify, policy, services
from apps.core.providers.base import IntentParserProvider
from apps.core.providers.registry import get_provider, override_provider

#: Frazele din raportul de problema, in ordinea in care au fost cerute. Unde exista
#: un raspuns, comanda simuleaza si runda de clarificare.
FRAZE: tuple[tuple[str, str | None], ...] = (
    ("Mă întâlnesc mâine cu Ion.", "La trei după-amiaza."),
    ("Ma intalnesc MAINE cu Ion.", "La trei după-amiaza."),
    ("Mă văd mâine cu Ion.", None),
    ("Am întâlnire mâine cu Ion.", None),
    ("Programează o întâlnire mâine cu Ion.", None),
    ("Mă întâlnesc poimâine la 14 cu Ana.", None),
    ("Mă întâlnesc poimâine la două cu Ana.", "După-amiaza."),
    ("Mă văd vineri la 10 cu Maria.", None),
    ("Mă întâlnesc pe 5 septembrie la 14:30 cu Ion.", None),
    ("Peste două săptămâni mă întâlnesc cu medicul.", "La ora 11."),
    ("Mă întâlnesc mâine dimineață.", "La 9."),
    ("Mă întâlnesc vineri la 3.", "După-amiaza."),
    ("Mă văd vineri la trei.", "După-amiaza."),
    ("Programează o întâlnire cu Ion.", "Mâine la 10."),
    ("Programează o întâlnire cu medicul.", None),
    # Intervale, AM/PM si formulari care trebuie sa ramana intrebari.
    ("Ședință mâine de la 10 la 12.", None),
    ("Ședință mâine între 10 și 12 cu echipa.", None),
    ("Mă întâlnesc mâine la 3 PM cu Ion.", None),
    ("Ne vedem săptămâna viitoare.", "Miercuri."),
    ("Ne vedem 10-12.", "Pe 5 septembrie la 10."),
)

CAMPURI = ("intent", "date", "start_time", "end_time", "all_day", "title", "person", "location")


class _Inregistrat(IntentParserProvider):
    """Providerul configurat, cu raspunsul brut retinut pentru afisare.

    Fluxul ramane cel real — `services.interpret` nu stie de diferenta — dar
    raspunsul modelului se poate pune alaturi de schita reconciliata. Fara el, un
    „nu sunt sigur de dată" nu spune cine si cu ce a gresit.
    """

    def __init__(self, inner):
        self.inner = inner
        self.name = inner.name
        self.is_mock = inner.is_mock
        self.ultimul: dict | None = None

    def is_available(self) -> bool:
        return self.inner.is_available()

    def describe(self) -> dict:
        return self.inner.describe()

    def parse(self, text: str, *, context) -> dict:
        self.ultimul = self.inner.parse(text, context=context)
        return dict(self.ultimul)


class Command(BaseCommand):
    help = "Trece frazele de control prin providerii configurați și arată schița reconciliată."

    def add_arguments(self, parser):
        parser.add_argument(
            "--user", help="Utilizatorul în al cărui fus orar se interpretează comenzile"
        )
        parser.add_argument("--text", action="append", help="O frază proprie (se poate repeta)")
        parser.add_argument(
            "--raspuns", help="Răspunsul la clarificare, folosit împreună cu un singur --text"
        )

    def handle(self, *args, **options):
        # Consola Windows este cp1252 implicit, iar frazele au diacritice.
        with contextlib.suppress(AttributeError, ValueError):
            sys.stdout.reconfigure(encoding="utf-8")

        user = self._user(options.get("user"))
        prefs = UserPreference.for_user(user)
        provider = get_provider("intent")
        transcription = get_provider("transcription")

        self.stdout.write(f"Utilizator: {user.get_username()} · fus orar: {prefs.timezone}")
        self.stdout.write(f"Provider intenții: {provider.describe()}")
        self.stdout.write(f"Provider transcriere: {transcription.describe()}")
        if provider.is_mock:
            self.stdout.write(
                self.style.WARNING(
                    "Providerul de intenții este unul simulat. Pentru verificarea reală, "
                    "pornește cu AI_ENABLED=True și PROVIDER_INTENT setat pe OpenAI."
                )
            )
        self.stdout.write("")

        if options.get("text"):
            perechi = [(text, options.get("raspuns")) for text in options["text"]]
        else:
            perechi = list(FRAZE)

        inregistrat = _Inregistrat(provider)
        # Tot ce se creeaza aici este material de verificare, nu date reale.
        with transaction.atomic(), override_provider("intent", inregistrat):
            for text, answer in perechi:
                self._verifica(user, text, answer, inregistrat)
            transaction.set_rollback(True)

    # ------------------------------------------------------------------ intern

    def _user(self, username: str | None):
        User = get_user_model()
        if username:
            user = User.objects.filter(username=username).first()
            if user is None:
                raise CommandError(f"Nu există utilizatorul „{username}”.")
            return user
        user = User.objects.order_by("pk").first()
        if user is None:
            raise CommandError("Nu există niciun utilizator. Creează unul cu createsuperuser.")
        return user

    def _verifica(self, user, text: str, answer: str | None, inregistrat) -> None:
        self.stdout.write(self.style.MIGRATE_HEADING(f"„{text}”"))
        draft = services.interpret(user, text)
        self._arata_modelul(inregistrat.ultimul)
        self._arata(draft)

        if not answer:
            self.stdout.write("")
            return

        reason = services.pending_reason(draft)
        if not reason:
            self.stdout.write("  (nu s-a cerut nicio clarificare; răspunsul nu se mai aplică)\n")
            return

        self.stdout.write(f"  → răspuns: „{answer}”")
        result = services.result_from_draft(draft)
        context = services.build_context(user)
        updated, outcome = clarify.apply_answer(result, answer, reason, context)
        if outcome != clarify.Outcome.MERGED:
            self.stdout.write(self.style.ERROR(f"  răspunsul nu a fost folosit ({outcome})"))
            self.stdout.write("")
            return

        services.update_draft(draft, updated, answer=answer)
        self._arata(draft)
        self.stdout.write("")

    def _arata_modelul(self, payload: dict | None) -> None:
        if payload is None:
            return
        interesante = {
            name: payload.get(name) for name in ("intent", "date", "start_time", "title", "person")
        }
        valori = " · ".join(f"{name}={value!r}" for name, value in interesante.items())
        self.stdout.write(f"  model: {valori}")

    def _arata(self, draft) -> None:
        result = services.result_from_draft(draft)
        valori = " · ".join(f"{name}={getattr(result, name)!r}" for name in CAMPURI)
        self.stdout.write(f"  {valori}")
        self.stdout.write(f"  încredere={result.confidence} · ambiguity={result.ambiguity}")

        if draft.clarification_question:
            self.stdout.write(self.style.WARNING(f"  întrebare: {draft.clarification_question}"))
        else:
            lipsuri = policy.missing_fields(result)
            eticheta = "gata de confirmare" if not lipsuri else f"incomplet: {lipsuri}"
            self.stdout.write(self.style.SUCCESS(f"  {eticheta}"))
