import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST
from django.views.generic import TemplateView

from apps.assistant import clarify, services
from apps.assistant import drafts as drafts_module
from apps.assistant.forms import DraftForm, TextCommandForm
from apps.assistant.models import IntentDraft, VoiceCapture
from apps.assistant.schemas import Intent, IntentResult
from apps.core.enums import ItemKind
from apps.core.files import validate_audio_upload
from apps.core.mixins import OwnerQuerysetMixin
from apps.core.providers.registry import get_provider
from apps.core.ratelimit import limited
from apps.core.registry import model_for_kind

logger = logging.getLogger("voicetask.assistant")

CAPTURE_TYPES = (
    (Intent.CREATE_NOTE, "Notă", "note"),
    (Intent.CREATE_APPOINTMENT, "Programare", "calendar"),
    (Intent.CREATE_REMINDER, "Alarmă", "bell"),
    (Intent.FOLLOW_UP_EMAIL, "Email", "mail"),
)


class CaptureView(OwnerQuerysetMixin, TemplateView):
    """Ecranul „Adaugă": voce sau scanare, cu tipul dorit."""

    template_name = "assistant/capture.html"

    def get_queryset(self):
        return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        transcription = get_provider("transcription")
        context.update(
            {
                "page": "capture",
                "capture_types": CAPTURE_TYPES,
                "selected_type": self.request.GET.get("tip", Intent.CREATE_NOTE),
                "mode": self.request.GET.get("mod", "voce"),
                "text_form": TextCommandForm(),
                "transcription_is_demo": transcription.is_mock,
                "transcription_unavailable": not transcription.is_available(),
                "max_audio_bytes": settings.MAX_UPLOAD_AUDIO_BYTES,
            }
        )
        return context


@login_required
@require_POST
@limited("voice")
def voice_upload(request):
    """Primeste inregistrarea, o valideaza si porneste interpretarea."""
    audio_file = request.FILES.get("audio")
    try:
        detected = validate_audio_upload(audio_file, max_bytes=settings.MAX_UPLOAD_AUDIO_BYTES)
    except ValidationError as exc:
        return JsonResponse({"eroare": exc.messages[0]}, status=400)

    audio_file.seek(0)
    payload = audio_file.read()

    capture = VoiceCapture(
        owner=request.user,
        content_type=detected.content_type,
        mode=request.POST.get("mod", "create"),
        status=VoiceCapture.Status.PENDING,
    )
    capture.audio.save(f"comanda.{detected.extension}", ContentFile(payload), save=False)
    capture.save()

    draft = services.process_capture(capture, payload)
    if draft is None:
        return JsonResponse(
            {"eroare": capture.error or "Înregistrarea nu a putut fi procesată."}, status=502
        )
    return JsonResponse(
        {"id": str(draft.uid), "url": reverse("assistant:draft", args=[draft.uid])}, status=201
    )


@login_required
@require_POST
@limited("ai")
def text_command(request):
    """Aceeasi interpretare, dar pornind de la text scris."""
    form = TextCommandForm(request.POST)
    if not form.is_valid():
        return render(request, "assistant/_text_form.html", {"text_form": form}, status=400)
    draft = services.interpret(
        request.user, form.cleaned_data["text"], mode=form.cleaned_data.get("mode") or "create"
    )
    return _render_draft(request, draft)


def _render_draft(
    request,
    draft: IntentDraft,
    *,
    form: DraftForm | None = None,
    status: int = 200,
    full_page: bool = False,
):
    """Fragment pentru HTMX, pagina completa pentru navigarea fara JavaScript."""
    result = IntentResult.model_validate(draft.payload)
    template = (
        "assistant/_draft_form.html"
        if getattr(request, "htmx", False) and not full_page
        else "assistant/draft.html"
    )
    return render(
        request,
        template,
        {
            "draft": draft,
            "result": result,
            "form": form or DraftForm(draft=draft),
            "needs_clarification": draft.status == IntentDraft.Status.NEEDS_CLARIFICATION,
            "is_destructive": result.is_destructive,
            "candidates": draft.candidates,
            "page": "capture",
        },
        status=status,
    )


@login_required
def draft_detail(request, uid):
    draft = get_object_or_404(IntentDraft.objects.for_user(request.user), uid=uid)
    return _render_draft(request, draft)


@login_required
@require_POST
def draft_clarify(request, uid):
    """Raspunsul la o intrebare de clarificare: alegerea unui candidat sau text nou."""
    draft = get_object_or_404(IntentDraft.objects.for_user(request.user), uid=uid)
    if not draft.is_open:
        return _render_draft(request, draft)

    chosen = request.POST.get("candidat", "")
    if chosen:
        kind, _, pk = chosen.partition(":")
        if kind and pk.isdigit() and model_for_kind(kind) is not None:
            result = services.result_from_draft(draft)
            services.update_draft(
                draft, result.model_copy(update={"target_kind": kind, "target_id": int(pk)})
            )
        return _render_draft(request, draft)

    answer = request.POST.get("raspuns", "").strip()
    if not answer:
        return _render_draft(request, draft)

    result = services.result_from_draft(draft)
    reason = services.pending_reason(draft)
    context = services.build_context(
        request.user,
        mode="edit" if draft.target_id else "create",
        target_kind=draft.target_kind or None,
        target_id=draft.target_id,
    )
    updated, outcome = clarify.apply_answer(result, answer, reason, context)

    if outcome == clarify.Outcome.MERGED:
        # Aceeasi schita, completata. Nimic din ce fusese deja extras nu se pierde,
        # iar raspunsul nu este citit ca o comanda noua.
        services.update_draft(draft, updated, answer=answer)
        return _render_draft(request, draft)

    if outcome == clarify.Outcome.NOT_UNDERSTOOD:
        # Intrebarea era despre un camp anume, iar raspunsul nu il contine. A
        # reinterpreta tot textul aici ar risca sa strice ce era deja bun.
        draft.clarification_question = f"Nu am înțeles. {draft.clarification_question}"[:300]
        draft.save(update_fields=["clarification_question", "updated_at"])
        return _render_draft(request, draft)

    # Reformulare: interpretarea veche este chiar cea pusa la indoiala.
    new_draft = services.interpret(
        request.user,
        answer,
        capture=draft.capture,
        mode="edit" if draft.target_id else "create",
        target_kind=draft.target_kind or None,
        target_id=draft.target_id,
    )
    draft.status = IntentDraft.Status.DISCARDED
    draft.save(update_fields=["status", "updated_at"])
    return _render_draft(request, new_draft)


@login_required
@require_POST
def draft_confirm(request, uid):
    """Salvarea efectiva. Actiunile distructive cer un al doilea pas explicit."""
    draft = get_object_or_404(IntentDraft.objects.for_user(request.user), uid=uid)
    result = IntentResult.model_validate(draft.payload)

    # Butonul dezactivat din interfata nu este o garantie: verificam si pe server.
    if draft.status == IntentDraft.Status.NEEDS_CLARIFICATION:
        return _render_draft(request, draft, status=409)

    if result.is_destructive and request.POST.get("confirmare") != "da":
        template = (
            "assistant/_confirm_destructive.html"
            if getattr(request, "htmx", False)
            else "assistant/confirm_destructive.html"
        )
        return render(request, template, {"draft": draft, "result": result, "page": "capture"})

    overrides = None
    if not result.is_destructive:
        form = DraftForm(request.POST, draft=draft)
        if not form.is_valid():
            return _render_draft(request, draft, form=form, status=400)
        overrides = form.to_overrides()

    try:
        kind, pk = drafts_module.apply(draft, overrides=overrides)
    except drafts_module.DraftError as exc:
        return render(
            request, "assistant/_error.html", {"draft": draft, "message": str(exc)}, status=409
        )

    messages.success(request, _success_message(draft.intent, kind))
    target = _redirect_url(kind, pk)
    if getattr(request, "htmx", False):
        response = HttpResponse(status=204)
        response["HX-Redirect"] = target
        return response
    return redirect(target)


def _success_message(intent: str, kind: str) -> str:
    return {
        Intent.CREATE_NOTE: "Notița a fost salvată.",
        Intent.CREATE_APPOINTMENT: "Programarea a fost creată.",
        Intent.CREATE_REMINDER: "Alarma a fost setată.",
        Intent.FOLLOW_UP_EMAIL: "Emailul a fost marcat pentru urmărire.",
        Intent.UPDATE_ITEM: "Modificarea a fost salvată.",
        Intent.DELETE_ITEM: "Elementul a fost mutat în coș.",
    }.get(intent, "Comanda a fost executată.")


def _redirect_url(kind: str, pk: int) -> str:
    routes = {
        ItemKind.NOTE: "notes:detail",
        ItemKind.APPOINTMENT: "scheduling:detail",
        ItemKind.REMINDER: "scheduling:reminder_detail",
        ItemKind.DOCUMENT: "documents:detail",
        ItemKind.EMAIL: "integrations:email_detail",
    }
    route = routes.get(kind)
    if route is None or pk is None:
        return reverse("core:home")
    model = model_for_kind(kind)
    if model is not None and not model.objects.filter(pk=pk).exists():
        # Obiectul a fost sters: nu are sens sa trimitem catre pagina lui.
        return reverse("core:trash")
    return reverse(route, args=[pk])


@login_required
@require_POST
def draft_discard(request, uid):
    draft = get_object_or_404(IntentDraft.objects.for_user(request.user), uid=uid)
    draft.status = IntentDraft.Status.DISCARDED
    draft.save(update_fields=["status", "updated_at"])
    return HttpResponse(status=204)


class EditByVoiceView(OwnerQuerysetMixin, TemplateView):
    """Ecranul „Modifică" pentru un obiect anume, cu zona vocală."""

    template_name = "assistant/edit.html"

    def get_queryset(self):
        return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        kind = self.kwargs["kind"]
        model = model_for_kind(kind)
        if model is None:
            from django.http import Http404

            raise Http404
        obj = get_object_or_404(model.objects.for_user(self.request.user), pk=self.kwargs["pk"])
        transcription = get_provider("transcription")
        context.update(
            {
                "page": "edit",
                "kind": kind,
                "object": obj,
                "examples": EDIT_EXAMPLES.get(kind, EDIT_EXAMPLES["default"]),
                "transcription_unavailable": not transcription.is_available(),
            }
        )
        return context


EDIT_EXAMPLES = {
    ItemKind.REMINDER: [
        "„Mută alarma cu două zile înainte”",
        "„Mută la ora 10:00”",
        "„Schimbă titlul în Plată factură”",
    ],
    ItemKind.APPOINTMENT: [
        "„Mută programarea mâine la 15”",
        "„Schimbă locația în Google Meet”",
        "„Adaugă notiță că trebuie să pregătesc raportul”",
    ],
    "default": [
        "„Schimbă titlul în ...”",
        "„Adaugă notiță că ...”",
        "„Mută la ora 10:00”",
    ],
}


@login_required
@require_POST
@limited("voice")
def edit_by_voice(request, kind: str, pk: int):
    """Comanda vocala aplicata unui obiect deja selectat."""
    model = model_for_kind(kind)
    if model is None:
        return JsonResponse({"eroare": "Tip necunoscut."}, status=400)
    obj = get_object_or_404(model.objects.for_user(request.user), pk=pk)

    audio_file = request.FILES.get("audio")
    if audio_file is not None:
        try:
            detected = validate_audio_upload(audio_file, max_bytes=settings.MAX_UPLOAD_AUDIO_BYTES)
        except ValidationError as exc:
            return JsonResponse({"eroare": exc.messages[0]}, status=400)
        audio_file.seek(0)
        payload = audio_file.read()
        capture = VoiceCapture(
            owner=request.user,
            content_type=detected.content_type,
            mode="edit",
            status=VoiceCapture.Status.PENDING,
        )
        capture.audio.save(f"comanda.{detected.extension}", ContentFile(payload), save=False)
        capture.save()
        capture = services.transcribe(capture, payload)
        if capture.status == VoiceCapture.Status.FAILED:
            return JsonResponse({"eroare": capture.error}, status=502)
        text = capture.transcript
    else:
        text = request.POST.get("text", "").strip()
        capture = None
        if not text:
            return JsonResponse({"eroare": "Nu am primit nicio comandă."}, status=400)

    draft = services.interpret(
        request.user, text, capture=capture, mode="edit", target_kind=kind, target_id=obj.pk
    )
    if audio_file is None and not request.headers.get("Accept", "").startswith("application/json"):
        return redirect("assistant:draft", uid=draft.uid)
    return JsonResponse(
        {"id": str(draft.uid), "url": reverse("assistant:draft", args=[draft.uid])}, status=201
    )
