"""Fluxul complet: audio sau text → transcriere → intentie → schita editabila."""

from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from apps.accounts.models import UserPreference
from apps.assistant import edits, policy, reconcile, resolver
from apps.assistant.models import IntentDraft, VoiceCapture
from apps.assistant.schemas import (
    MUTATING_INTENTS,
    Intent,
    IntentResult,
    IntentValidationError,
    parse_result,
)
from apps.core.enums import ItemKind
from apps.core.providers.base import ProviderError, ProviderUnavailable
from apps.core.providers.context import IntentContext
from apps.core.providers.registry import get_offline_provider, get_provider
from apps.core.registry import model_for_kind

logger = logging.getLogger("voicetask.assistant")


def build_context(user, *, mode: str = "create", target_kind=None, target_id=None) -> IntentContext:
    prefs = UserPreference.for_user(user)
    return IntentContext(
        # Fusul utilizatorului, nu cel activ pe server. „Mâine", rostit la 23:50 la
        # Londra, este alta zi decat „mâine" citit cu ceasul de la Bucuresti.
        now=timezone.localtime(timezone.now(), prefs.tzinfo),
        timezone_name=prefs.timezone,
        known_items=resolver.known_items(user),
        default_reminder_offset=prefs.default_reminder_offset,
        mode=mode,
        target_kind=target_kind,
        target_id=target_id,
    )


def transcribe(capture: VoiceCapture, audio: bytes) -> VoiceCapture:
    """Transcrie inregistrarea. Nu logam niciodata textul rezultat."""
    VoiceCapture.all_objects.filter(pk=capture.pk).update(
        status=VoiceCapture.Status.TRANSCRIBING
    )
    provider = get_provider("transcription")
    try:
        result = provider.transcribe(audio, content_type=capture.content_type or "audio/webm")
    except ProviderError as exc:
        capture.status = VoiceCapture.Status.FAILED
        capture.error = exc.user_message
        capture.save(update_fields=["status", "error", "updated_at"])
        logger.warning("transcriere esuata capture=%s tip=%s", capture.uid, type(exc).__name__)
        return capture

    text = (result.text or "").strip()
    if not text:
        capture.status = VoiceCapture.Status.FAILED
        capture.error = "Nu am auzit nimic. Încearcă din nou, mai aproape de microfon."
        capture.save(update_fields=["status", "error", "updated_at"])
        logger.info("transcriere goala capture=%s", capture.uid)
        return capture

    capture.transcript = text
    capture.transcript_confidence = result.confidence
    capture.duration_ms = result.duration_ms
    capture.status = VoiceCapture.Status.PARSING
    capture.save(
        update_fields=[
            "transcript",
            "transcript_confidence",
            "duration_ms",
            "status",
            "updated_at",
        ]
    )
    return capture


def _unclear_result() -> IntentResult:
    """Rezultatul folosit cand nicio interpretare nu a reusit."""
    return IntentResult(
        intent=Intent.UNKNOWN,
        confidence=0.0,
        clarification_required=True,
        clarification_question="Nu am putut interpreta comanda. Poți reformula?",
    )


def _parse_and_validate(parser, text: str, context: IntentContext) -> IntentResult:
    return parse_result(parser.parse(text, context=context))


def _interpret_text(text: str, context: IntentContext) -> tuple[IntentResult, bool]:
    """Interpreteaza textul, cu rezerva pe parserul determinist.

    Returneaza `(rezultat, degradat)`. Providerul configurat are prioritate.
    Daca esueaza — serviciul nu raspunde sau raspunsul nu trece de schema — se
    reia o singura data cu parserul local, care decide doar comenzile pe care le
    recunoaste sigur. Daca nici el nu poate decide, cerem reformularea.

    Doua limite deliberate:

    * o eroare de configurare (`ProviderUnavailable`: cheie lipsa sau respinsa)
      nu declanseaza rezerva. Altfel aplicatia ar parea sanatoasa la nesfarsit,
      iar greseala de configurare nu s-ar observa niciodata.
    * rezerva nu decide stergeri sau modificari. „Serviciul a cazut, deci
      presupun ca voiai sa stergi ceva" nu este un comportament acceptabil.

    Transcrierea nu are o astfel de rezerva: un text inventat ar fi mai rau
    decat o eroare onesta.
    """
    provider = get_provider("intent")
    try:
        return _parse_and_validate(provider, text, context), False
    except ProviderUnavailable as exc:
        # Configurare gresita: esec deschis, fara rezerva care sa il mascheze.
        logger.warning(
            "provider indisponibil provider=%s tip=%s", provider.name, type(exc).__name__
        )
        return _unclear_result(), False
    except ProviderError as exc:
        logger.warning("interpretare esuata provider=%s tip=%s", provider.name, type(exc).__name__)
    except IntentValidationError as exc:
        logger.warning("schema invalida provider=%s campuri=%s", provider.name, exc.fields)

    fallback = get_offline_provider("intent")
    if type(fallback) is type(provider):
        return _unclear_result(), False

    logger.warning("se reia interpretarea cu parserul local provider=%s", fallback.name)
    try:
        result = _parse_and_validate(fallback, text, context)
    except (ProviderError, IntentValidationError):
        return _unclear_result(), True

    if result.intent == Intent.UNKNOWN or result.intent in MUTATING_INTENTS:
        return _unclear_result(), True
    return result, True


def interpret(
    user,
    text: str,
    *,
    capture: VoiceCapture | None = None,
    mode: str = "create",
    target_kind: str | None = None,
    target_id: int | None = None,
) -> IntentDraft:
    """Interpreteaza textul si creeaza schita. Nu salveaza nimic in aplicatie."""
    context = build_context(user, mode=mode, target_kind=target_kind, target_id=target_id)
    result, degraded = _interpret_text(text, context)
    # Nimic din ce a spus modelul nu ajunge in schita neverificat: data si ora sunt
    # recitite determinist din transcriere, iar detaliile fara acoperire in text cad.
    result = reconcile.reconcile(result, text, context)

    candidates: list[resolver.Candidate] = []
    if result.intent == Intent.FOLLOW_UP_EMAIL and result.target_id is None:
        # Emailul se alege, nu se ghiceste. O singura potrivire se preselecteaza —
        # dar tot se afiseaza; mai multe raman la latitudinea utilizatorului.
        candidates = resolver.resolve_email(user, result.person or result.title or text)
        if len(candidates) == 1:
            result = result.model_copy(
                update={"target_id": candidates[0].pk, "target_kind": ItemKind.EMAIL}
            )
        elif not candidates:
            result = result.model_copy(
                update={"ambiguity": [*result.ambiguity, "email_negasit"]}
            )
    elif result.needs_target and result.target_id is None:
        found_id, found_kind, candidates = resolver.resolve(
            user, result.title or text, kind=result.target_kind or target_kind
        )
        if found_id is not None:
            result = result.model_copy(update={"target_id": found_id, "target_kind": found_kind})

    if result.intent == Intent.UPDATE_ITEM:
        result = _apply_edit_rules(result, text, context)

    decision = policy.decide(result, candidate_count=len(candidates), degraded=degraded)

    draft = IntentDraft.objects.create(
        owner=user,
        capture=capture,
        intent=result.intent,
        payload=result.model_dump(mode="json"),
        confidence=result.confidence,
        status=(
            IntentDraft.Status.NEEDS_CLARIFICATION
            if decision.needs_clarification
            else IntentDraft.Status.DRAFT
        ),
        clarification_question=decision.question,
        candidates=[candidate.as_dict() for candidate in candidates],
        target_kind=result.target_kind or "",
        target_id=result.target_id,
        source_text=text,
        expires_at=timezone.now() + timedelta(minutes=settings.DRAFT_TTL_MINUTES),
    )

    if capture is not None:
        capture.status = VoiceCapture.Status.READY
        capture.save(update_fields=["status", "updated_at"])

    return draft


#: Cat de lung poate fi un titlu construit mecanic dintr-o notita.
NOTE_TITLE_LIMIT = 80


def note_title(text: str) -> str:
    """Titlul unei notite, taiat mecanic — nu rezumat.

    Primul rand nevid; daca trece de `NOTE_TITLE_LIMIT`, se taie la ultima limita de
    cuvant. Nu se scoate nimic din text: titlul este o eticheta, iar continutul ramane
    intreg. Nu intervine niciun model si nicio interpretare.
    """
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if len(first) <= NOTE_TITLE_LIMIT:
        return first
    taiat = first[:NOTE_TITLE_LIMIT]
    spatiu = taiat.rfind(" ")
    return (taiat[:spatiu] if spatiu > 0 else taiat).rstrip(" ,.;:-") + "…"


def capture_note(user, text: str, *, capture: VoiceCapture | None = None) -> IntentDraft:
    """Salveaza textul ca notita, fara sa il interpreteze.

    Cand utilizatorul a ales explicit tipul „Notă", ce a dictat nu este o comanda.
    „Mâine la ora 3 mă întâlnesc cu Ion" este continutul notitei, nu o programare —
    deci nu se cheama providerul de intentii, nu se cheama parserul local si nu se
    face nicio reconciliere temporala. Schita ramane editabila: titlul, continutul,
    categoria si „Fixează" pot fi schimbate inainte de salvare.
    """
    content = (text or "").strip()
    result = IntentResult(
        intent=Intent.CREATE_NOTE,
        title=note_title(content),
        description=content,
        verbatim=True,
    )
    draft = IntentDraft.objects.create(
        owner=user,
        capture=capture,
        intent=result.intent,
        payload=result.model_dump(mode="json"),
        confidence=result.confidence,
        status=IntentDraft.Status.DRAFT,
        source_text=content,
        expires_at=timezone.now() + timedelta(minutes=settings.DRAFT_TTL_MINUTES),
    )
    if capture is not None:
        capture.status = VoiceCapture.Status.READY
        capture.save(update_fields=["status", "updated_at"])
    return draft


def process_capture(
    capture: VoiceCapture, audio: bytes, *, intent: str | None = None
) -> IntentDraft | None:
    """Transcrie si, daca nu este o notita, interpreteaza.

    Pentru o notita se opreste dupa transcriere: singurul provider folosit este cel
    de transcriere.
    """
    capture = transcribe(capture, audio)
    if capture.status == VoiceCapture.Status.FAILED:
        return None
    if intent == Intent.CREATE_NOTE:
        return capture_note(capture.owner, capture.transcript, capture=capture)
    return interpret(
        capture.owner,
        capture.transcript,
        capture=capture,
        mode=capture.mode,
    )


def _apply_edit_rules(result: IntentResult, text: str, context: IntentContext) -> IntentResult:
    """Decide ce se intampla cu titlul si descrierea la o modificare.

    Implicit, nimic: titlul si descrierea obiectului raman ale lui. Se schimba doar
    la o cerere explicita, iar completarea se calculeaza aici, nu la salvare — asa
    utilizatorul vede in formular exact textul care se va scrie, iar o a doua
    confirmare nu poate adauga inca o data.
    """
    obiect = _target_object(result, context)
    cerere = edits.detect(text)

    update: dict = {"title": None, "description": None}
    if cerere.ambiguous:
        update["ambiguity"] = [*result.ambiguity, "editare_ambigua"]
        return result.model_copy(update=update)

    if obiect is None:
        # Fara obiect nu stim ce completam. Politica va cere oricum tinta.
        return result.model_copy(update=update)

    if cerere.title:
        update["title"] = cerere.title[:200]
    if cerere.replace_description:
        update["description"] = cerere.replace_description
    elif cerere.append:
        update["description"] = edits.append_to_description(
            _current_description(obiect), cerere.append, context.now
        )
    return result.model_copy(update=update)


def _target_object(result: IntentResult, context: IntentContext):
    kind = result.target_kind or context.target_kind
    pk = result.target_id or context.target_id
    if not kind or not pk:
        return None
    model = model_for_kind(kind)
    return model.objects.filter(pk=pk).first() if model else None


def _current_description(obiect) -> str:
    """Notitele tin textul in `content`, restul in `description`."""
    return getattr(obiect, "description", None) or getattr(obiect, "content", "") or ""


def update_draft(
    draft: IntentDraft, result: IntentResult, *, answer: str | None = None
) -> IntentDraft:
    """Rescrie schita existenta dupa o completare, pastrandu-i identitatea.

    Aceeasi schita, acelasi `uid`, aceeasi adresa. Politica este recalculata pe
    starea noua, deci o schita completata iese singura din clarificare, iar una
    care mai are o lipsa primeste urmatoarea intrebare.
    """
    decision = policy.decide(result)
    draft.intent = result.intent
    draft.payload = result.model_dump(mode="json")
    draft.confidence = result.confidence
    draft.status = (
        IntentDraft.Status.NEEDS_CLARIFICATION
        if decision.needs_clarification
        else IntentDraft.Status.DRAFT
    )
    draft.clarification_question = decision.question
    draft.target_kind = result.target_kind or ""
    draft.target_id = result.target_id
    if answer:
        # Ecranul de confirmare arata `source_text` ca transcriere. Raspunsul se
        # adauga la ea, ca utilizatorul sa vada tot ce a spus, nu doar prima fraza.
        draft.source_text = f"{draft.source_text} {answer}".strip()
    draft.save(
        update_fields=[
            "intent",
            "payload",
            "confidence",
            "status",
            "clarification_question",
            "target_kind",
            "target_id",
            "source_text",
            "updated_at",
        ]
    )
    return draft


def pending_reason(draft: IntentDraft) -> str:
    """Motivul intrebarii afisate acum.

    `policy.decide` este o functie pura de rezultat, deci motivul se recalculeaza
    din payload ori de cate ori e nevoie. Asa nu trebuie tinut nicaieri si nu poate
    ramane in urma fata de schita.
    """
    return policy.decide(result_from_draft(draft), candidate_count=len(draft.candidates)).reason


def result_from_draft(draft: IntentDraft) -> IntentResult:
    return IntentResult.model_validate(draft.payload)
