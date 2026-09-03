import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.views.generic import DetailView, ListView, TemplateView

from apps.core.files import validate_image_upload
from apps.core.mixins import OwnerQuerysetMixin
from apps.core.models import AuditLog
from apps.core.ratelimit import limited
from apps.documents.forms import ExtractionConfirmForm
from apps.documents.models import ScannedDocument
from apps.documents.pipeline import preprocess
from apps.documents.tasks import process_document

logger = logging.getLogger("voicetask.documents")


class DocumentListView(OwnerQuerysetMixin, ListView):
    model = ScannedDocument
    template_name = "documents/document_list.html"
    context_object_name = "documents"
    paginate_by = 20

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page"] = "documents"
        return context


class ScanView(OwnerQuerysetMixin, TemplateView):
    """Ecranul de cameră. Ascunde navigatia inferioara pentru a ramane imersiv."""

    template_name = "documents/scan.html"

    def get_queryset(self):
        return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page": "scan",
                "hide_nav": True,
                "max_bytes": settings.MAX_UPLOAD_IMAGE_BYTES,
            }
        )
        return context


class DocumentDetailView(OwnerQuerysetMixin, DetailView):
    model = ScannedDocument
    template_name = "documents/document_detail.html"
    context_object_name = "document"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update(
            {
                "page": "documents",
                "form": ExtractionConfirmForm(document=self.object, user=self.request.user),
                "warn_threshold": settings.OCR_FIELD_CONFIDENCE_WARN,
            }
        )
        return context


@login_required
@require_POST
@limited("ocr")
def upload(request):
    """Primeste fotografia, o valideaza si porneste procesarea."""
    upload_file = request.FILES.get("imagine")
    try:
        detected = validate_image_upload(
            upload_file, max_bytes=settings.MAX_UPLOAD_IMAGE_BYTES
        )
    except ValidationError as exc:
        return JsonResponse({"eroare": exc.messages[0]}, status=400)

    existing = ScannedDocument.objects.for_user(request.user).filter(
        image_sha256=detected.sha256
    ).first()
    if existing is not None:
        return JsonResponse(
            {
                "id": existing.pk,
                "duplicat": True,
                "url_stare": reverse("documents:status", args=[existing.pk]),
                "url_detaliu": existing.get_absolute_url(),
            }
        )

    document = ScannedDocument(
        owner=request.user,
        image_sha256=detected.sha256,
        processing_status=ScannedDocument.Status.PENDING,
    )
    document.original_image.save(
        f"scan.{detected.extension}", upload_file, save=False
    )
    document.save()

    process_document.delay(document.pk)
    return JsonResponse(
        {
            "id": document.pk,
            "duplicat": False,
            "url_stare": reverse("documents:status", args=[document.pk]),
            "url_detaliu": document.get_absolute_url(),
        },
        status=201,
    )


@login_required
@require_POST
@limited("ocr")
def detect(request):
    """Spune daca in cadru se vede un document. Decizia se ia pe server, nu in JS."""
    frame = request.FILES.get("cadru")
    try:
        validate_image_upload(frame, max_bytes=4 * 1024 * 1024)
    except ValidationError as exc:
        return JsonResponse({"detectat": False, "eroare": exc.messages[0]}, status=400)
    frame.seek(0)
    try:
        result = preprocess.detect_only(frame.read())
    except (ValueError, OSError) as exc:
        logger.warning("detectie esuata: %s", type(exc).__name__)
        return JsonResponse({"detectat": False})
    return JsonResponse({"detectat": result["detected"], "colturi": result["quad"]})


@login_required
def status(request, pk: int):
    document = get_object_or_404(ScannedDocument.objects.for_user(request.user), pk=pk)
    if document.is_processing:
        return render(request, "documents/_status.html", {"document": document})
    return render(
        request,
        "documents/_extraction_form.html",
        {
            "document": document,
            "form": ExtractionConfirmForm(document=document, user=request.user),
            "warn_threshold": settings.OCR_FIELD_CONFIDENCE_WARN,
        },
    )


@login_required
@require_POST
def reprocess(request, pk: int):
    document = get_object_or_404(ScannedDocument.objects.for_user(request.user), pk=pk)
    ScannedDocument.all_objects.filter(pk=pk).update(
        processing_status=ScannedDocument.Status.PENDING, processing_error=""
    )
    document.refresh_from_db()
    process_document.delay(document.pk)
    return render(request, "documents/_status.html", {"document": document})


@login_required
@require_POST
def confirm(request, pk: int):
    """Singurul loc in care un document devine notita, alarma sau programare."""
    document = get_object_or_404(ScannedDocument.objects.for_user(request.user), pk=pk)
    form = ExtractionConfirmForm(request.POST, document=document, user=request.user)
    if not form.is_valid():
        return render(
            request,
            "documents/_extraction_form.html",
            {
                "document": document,
                "form": form,
                "warn_threshold": settings.OCR_FIELD_CONFIDENCE_WARN,
            },
            status=400,
        )
    created = form.save()
    document.processing_status = ScannedDocument.Status.CONFIRMED
    document.confirmed_at = timezone.now()
    document.save(update_fields=["processing_status", "confirmed_at", "title", "updated_at"])
    labels = ", ".join(created.keys()) or "nimic"
    messages.success(request, f"Document confirmat. Am creat: {labels}.")
    return redirect(document.get_absolute_url())


@login_required
def original_image(request, pk: int):
    """Fotografia se serveste doar prin acest view, cu verificarea proprietarului."""
    document = get_object_or_404(ScannedDocument.all_objects.for_user(request.user), pk=pk)
    if not document.original_image:
        raise Http404
    return FileResponse(document.original_image.open("rb"), content_type="image/jpeg")


@login_required
def delete_document(request, pk: int):
    document = get_object_or_404(ScannedDocument.objects.for_user(request.user), pk=pk)
    if request.method != "POST":
        return render(
            request,
            "core/_confirm_delete.html",
            {
                "objects": [{"kind": "document", "pk": pk, "title": str(document)}],
                "retention_days": settings.TRASH_RETENTION_DAYS,
                "action_url": reverse("documents:delete", args=[pk]),
            },
        )
    document.delete()
    AuditLog.objects.create(
        user=request.user,
        action=AuditLog.Action.DELETE,
        object_label=ScannedDocument._meta.label,
        object_id=str(pk),
    )
    messages.success(
        request,
        "Documentul a fost mutat în coș. Îl poți recupera timp de "
        f"{settings.TRASH_RETENTION_DAYS} de zile.",
    )
    if getattr(request, "htmx", False):
        response = HttpResponse(status=204)
        response["HX-Redirect"] = reverse("documents:list")
        return response
    return redirect("documents:list")
