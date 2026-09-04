"""O notiță aleasă explicit nu este o comandă.

„Mâine la ora 3 mă întâlnesc cu Ion" dictat ca notita este continutul notitei, nu o
programare. Testele de aici dovedesc ca pe calea notitei niciun provider de intentii
nu este chemat: providerul simulat ridica exceptie daca cineva il atinge.
"""

from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.assistant import drafts as drafts_module
from apps.assistant import services
from apps.assistant.forms import NoteDraftForm
from apps.assistant.models import IntentDraft
from apps.assistant.schemas import Intent
from apps.assistant.tests._stubs import TranscriereSimulata
from apps.core.providers.base import IntentParserProvider
from apps.core.providers.registry import override_provider
from apps.notes.models import Note, NoteCategory
from apps.scheduling.models import Appointment

pytestmark = pytest.mark.django_db

COMANDA_APARENTA = "Mâine la ora 3 mă întâlnesc cu Ion"


class ProviderInterzis(IntentParserProvider):
    """Daca este chemat, testul cade. Asta este toata dovada."""

    name = "nu-trebuie-chemat"

    def parse(self, text: str, *, context):
        raise AssertionError("providerul de intenții nu are ce căuta pe calea notiței")


def capture_url(tip: str = Intent.CREATE_NOTE) -> str:
    return f"{reverse('assistant:text_command')}?tip={tip}"


# ------------------------------------------------- niciun provider de intentii


def test_notita_scrisa_nu_cheama_niciun_provider(auth_client):
    with override_provider("intent", ProviderInterzis()):
        response = auth_client.post(capture_url(), {"text": COMANDA_APARENTA})

    assert response.status_code == 200
    draft = IntentDraft.objects.get()
    assert draft.intent == Intent.CREATE_NOTE


def test_notita_vocala_foloseste_doar_transcrierea(auth_client, sample_audio):
    audio = SimpleUploadedFile("nota.wav", sample_audio(), content_type="audio/wav")

    with (
        override_provider("transcription", TranscriereSimulata(COMANDA_APARENTA)),
        override_provider("intent", ProviderInterzis()),
    ):
        response = auth_client.post(
            f"{reverse('assistant:voice_upload')}?tip={Intent.CREATE_NOTE}", {"audio": audio}
        )

    assert response.status_code == 201
    draft = IntentDraft.objects.get()
    assert draft.intent == Intent.CREATE_NOTE
    assert draft.payload["description"] == COMANDA_APARENTA


def test_parserul_local_nu_este_chemat_nici_ca_rezerva(auth_client, monkeypatch):
    """Nici providerul configurat, nici rezerva locala nu văd textul notiței.

    `_interpret_text` este poarta prin care trec amandoua; daca nu se deschide, nu a
    intrat nimeni.
    """

    def interzis(*args, **kwargs):
        raise AssertionError("interpretarea nu are ce căuta pe calea notiței")

    monkeypatch.setattr(services, "_interpret_text", interzis)
    auth_client.post(capture_url(), {"text": COMANDA_APARENTA})

    draft = IntentDraft.objects.get()
    assert draft.payload["verbatim"] is True


# ------------------------------------------------------- textul ramane intreg


def test_o_data_si_o_ora_raman_in_notita(auth_client):
    with override_provider("intent", ProviderInterzis()):
        auth_client.post(capture_url(), {"text": COMANDA_APARENTA})

    draft = IntentDraft.objects.get()
    assert draft.payload["description"] == COMANDA_APARENTA
    assert draft.payload["date"] is None
    assert draft.payload["start_time"] is None
    assert draft.payload["person"] is None
    assert draft.payload["ambiguity"] == []


def test_notita_nu_devine_programare_la_salvare(auth_client, user):
    with override_provider("intent", ProviderInterzis()):
        auth_client.post(capture_url(), {"text": COMANDA_APARENTA})
    draft = IntentDraft.objects.get()

    form = NoteDraftForm(
        {"title": draft.payload["title"], "description": draft.payload["description"]},
        draft=draft,
    )
    assert form.is_valid(), form.errors
    drafts_module.apply(draft, overrides=form.to_overrides())

    assert Appointment.objects.count() == 0
    assert Note.objects.get().content == COMANDA_APARENTA


@pytest.mark.parametrize(
    "text,titlu",
    [
        ("De cumpărat lapte", "De cumpărat lapte"),
        ("\n\nPrimul rând\nAl doilea rând", "Primul rând"),
        ("   ", ""),
    ],
)
def test_titlul_este_primul_rand_nevid(text, titlu):
    assert services.note_title(text) == titlu


def test_titlul_lung_se_taie_la_limita_unui_cuvant():
    text = "Trebuie neapărat să cumpăr lapte pâine ouă unt brânză telemea cașcaval și niște roșii"
    titlu = services.note_title(text)

    assert len(titlu) <= services.NOTE_TITLE_LIMIT + 1
    assert titlu.endswith("…")
    # Taietura cade intre cuvinte, nu prin mijlocul unuia.
    assert titlu.rstrip("…") in text
    assert text.startswith(titlu.rstrip("…"))


def test_textul_folosit_pentru_titlu_ramane_in_continut(auth_client):
    lung = "Prima frază lungă despre ce am de făcut mâine dimineață la birou cu toată echipa."
    with override_provider("intent", ProviderInterzis()):
        auth_client.post(capture_url(), {"text": lung})

    draft = IntentDraft.objects.get()
    assert draft.payload["description"] == lung


# ------------------------------------------------------------ tipul se verifica


@pytest.mark.parametrize("tip", ["stergeti_tot", "delete_item", "", "create_note "])
def test_un_tip_necunoscut_nu_este_luat_de_bun(tip, rf, user):
    """Selectia venita din cerere se verifica; un `tip` inventat nu decide nimic."""
    from apps.assistant.views import _requested_intent

    cerere = rf.post(f"/asistent/text/?tip={tip}", {"text": "Notează ceva"})
    cerere.user = user

    assert _requested_intent(cerere) is None


def test_un_tip_necunoscut_cade_pe_interpretarea_obisnuita(auth_client):
    from apps.assistant.tests._stubs import ModelSimulat

    with override_provider("intent", ModelSimulat(intent=Intent.CREATE_NOTE, confidence=0.9)):
        response = auth_client.post(
            f"{reverse('assistant:text_command')}?tip=stergeti_tot", {"text": "Notează ceva"}
        )

    assert response.status_code == 200
    assert IntentDraft.objects.get().payload["verbatim"] is False


def test_fara_tip_notita_trece_prin_interpretare(auth_client):
    """Comportamentul vechi ramane neatins cand tipul nu este trimis."""
    from apps.assistant.tests._stubs import ModelSimulat

    with override_provider("intent", ModelSimulat(intent=Intent.CREATE_NOTE, confidence=0.9)):
        auth_client.post(reverse("assistant:text_command"), {"text": "Notează că am plătit"})

    assert IntentDraft.objects.get().payload["verbatim"] is False


# --------------------------------------------------------- categoria si fixarea


def test_categoria_si_fixarea_se_salveaza(auth_client, user):
    categorie = NoteCategory.objects.create(owner=user, name="Cumpărături", slug="cumparaturi")
    with override_provider("intent", ProviderInterzis()):
        auth_client.post(capture_url(), {"text": "Lapte și pâine"})
    draft = IntentDraft.objects.get()

    form = NoteDraftForm(
        {
            "title": "Lapte și pâine",
            "description": "Lapte și pâine",
            "category_id": str(categorie.pk),
            "is_pinned": "on",
        },
        draft=draft,
    )
    assert form.is_valid(), form.errors
    drafts_module.apply(draft, overrides=form.to_overrides())

    note = Note.objects.get()
    assert note.category_id == categorie.pk
    assert note.is_pinned is True


# ----------------------------------------------------------------- interfata


def test_ecranul_spune_ca_dicteaza_o_notita(auth_client):
    html = auth_client.get(
        reverse("assistant:capture"), {"tip": Intent.CREATE_NOTE}
    ).content.decode()

    assert "Dictează notița" in html
    assert "Scrie notița" in html
    assert "Scrie comanda" not in html
    assert "Spune ce vrei să creezi" not in html


def test_ecranul_pentru_programare_ramane_neschimbat(auth_client):
    html = auth_client.get(
        reverse("assistant:capture"), {"tip": Intent.CREATE_APPOINTMENT}
    ).content.decode()

    assert "Spune ce vrei să creezi" in html
    assert "Scrie comanda" in html
    assert "Dictează notița" not in html


def test_tipul_ales_ajunge_in_adresa_de_incarcare(auth_client):
    html = auth_client.get(
        reverse("assistant:capture"), {"tip": Intent.CREATE_NOTE}
    ).content.decode()

    asteptat = f"data-upload-url=\"{reverse('assistant:voice_upload')}?tip={Intent.CREATE_NOTE}\""
    assert asteptat in html


def test_schita_unei_notite_nu_arata_procent_de_incredere(auth_client):
    with override_provider("intent", ProviderInterzis()):
        auth_client.post(capture_url(), {"text": "Lapte și pâine"})
    draft = IntentDraft.objects.get()

    html = auth_client.get(reverse("assistant:draft", args=[draft.uid])).content.decode()

    assert "Încredere" not in html
