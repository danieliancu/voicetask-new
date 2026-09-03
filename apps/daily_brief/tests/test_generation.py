"""Generarea rezumatului zilnic, cache-ul si invalidarea lui."""

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.daily_brief import render, services
from apps.daily_brief.models import DailyBrief
from apps.daily_brief.snapshot import build_snapshot, source_hash

pytestmark = pytest.mark.django_db


def test_rezumatul_se_construieste_din_datele_reale(user, appointment_factory):
    appointment_factory(user, title="Control medical", day_offset=0, hour=9)

    brief = services.get_or_create_brief(user)

    assert "Control medical" in brief.generated_text
    assert brief.status == DailyBrief.Status.READY


def test_rezumatul_gol_spune_ca_nu_e_nimic(user):
    brief = services.get_or_create_brief(user)
    assert "Nu ai nimic programat" in brief.generated_text


def test_rezumatul_nu_inventeaza_programari(user):
    brief = services.get_or_create_brief(user)
    assert brief.snapshot["appointments"] == []
    assert "Nu ai nicio programare" in brief.generated_text


def test_al_doilea_apel_refoloseste_rezumatul(user, appointment_factory):
    appointment_factory(user, day_offset=0, hour=9)

    primul = services.get_or_create_brief(user)
    generat_la = primul.generated_at
    al_doilea = services.get_or_create_brief(user)

    assert al_doilea.pk == primul.pk
    assert al_doilea.generated_at == generat_la


def test_schimbarea_datelor_invalideaza_rezumatul(user, appointment_factory):
    services.get_or_create_brief(user)
    hash_initial = DailyBrief.objects.get(owner=user).source_hash

    appointment_factory(user, title="Nou", day_offset=0, hour=11)
    reconstruit = services.get_or_create_brief(user)

    assert reconstruit.source_hash != hash_initial
    assert "Nou" in reconstruit.generated_text


def test_semnalul_marcheaza_rezumatul_ca_invalid(user, appointment_factory):
    services.get_or_create_brief(user)
    appointment_factory(user, day_offset=0, hour=11)

    assert DailyBrief.objects.get(owner=user).status == DailyBrief.Status.PENDING


def test_amprenta_este_stabila_pentru_aceleasi_date(user, appointment_factory):
    appointment_factory(user, day_offset=0, hour=9)

    primul = source_hash(build_snapshot(user, timezone.localdate()))
    al_doilea = source_hash(build_snapshot(user, timezone.localdate()))

    assert primul == al_doilea


def test_regenerarea_fortata_reconstruieste(user):
    primul = services.get_or_create_brief(user)
    # Falsificam textul salvat: `force=True` trebuie sa il rescrie din date,
    # chiar daca amprenta datelor nu s-a schimbat.
    DailyBrief.objects.filter(pk=primul.pk).update(generated_text="text invechit")

    al_doilea = services.get_or_create_brief(user, force=True)

    assert al_doilea.pk == primul.pk
    assert al_doilea.generated_text != "text invechit"
    assert "Nu ai nimic programat" in al_doilea.generated_text


def test_audio_generat_cu_providerul_demonstrativ(user, prefs, appointment_factory):
    appointment_factory(user, day_offset=0, hour=9)

    brief = services.get_or_create_brief(user)

    assert brief.audio_file
    assert brief.audio_duration_ms > 0


def test_audio_dezactivat_din_preferinte(user, prefs, appointment_factory):
    appointment_factory(user, day_offset=0, hour=9)
    prefs.brief_audio_enabled = False
    prefs.save()

    brief = services.get_or_create_brief(user)

    assert not brief.audio_file


def test_audio_nu_se_regenereaza_daca_textul_nu_s_a_schimbat(user, appointment_factory):
    appointment_factory(user, day_offset=0, hour=9)
    primul = services.get_or_create_brief(user)
    nume = primul.audio_file.name
    assert nume

    al_doilea = services.get_or_create_brief(user, force=True)

    assert al_doilea.audio_file.name == nume


def test_rezumatul_este_separat_pe_utilizatori(user, other_user, appointment_factory):
    appointment_factory(other_user, title="Al altcuiva", day_offset=0, hour=9)

    brief = services.get_or_create_brief(user)

    assert "Al altcuiva" not in brief.generated_text


# --------------------------------------------------------------------- acordul gramatical


@pytest.mark.parametrize(
    "count,asteptat",
    [
        (0, "nicio programare"),
        (1, "o programare"),
        (2, "2 programări"),
        (19, "19 programări"),
        (20, "20 de programări"),
        (21, "21 de programări"),
        (100, "100 de programări"),
        (101, "101 programări"),
    ],
)
def test_acordul_numeralului(count, asteptat):
    assert render.count_phrase(count, "programare", "programări") == asteptat


# --------------------------------------------------------------------- intrebari


def test_intrebarea_despre_prima_programare(user, appointment_factory):
    appointment_factory(user, title="Control medical", day_offset=0, hour=9)
    brief = services.get_or_create_brief(user)

    raspuns = render.answer_question(brief.snapshot, "Care e prima programare?")

    assert "Control medical" in raspuns


def test_intrebarea_fara_date_nu_inventeaza(user):
    brief = services.get_or_create_brief(user)
    raspuns = render.answer_question(brief.snapshot, "Care e prima programare?")
    assert "Nu ai nicio programare" in raspuns


def test_intrebarea_se_salveaza_cu_raspuns(auth_client, user):
    response = auth_client.post(
        reverse("daily_brief:ask"),
        {"intrebare": "Câte programări am?"},
        headers={"HX-Request": "true"},
    )

    assert response.status_code == 200
    from apps.daily_brief.models import BriefQuestion

    assert BriefQuestion.objects.for_user(user).count() == 1


def test_ecranul_rezumatului_se_randeaza(auth_client, user, appointment_factory):
    appointment_factory(user, title="Control medical", day_offset=0, hour=9)
    response = auth_client.get(reverse("daily_brief:today"))
    assert response.status_code == 200
    assert b"Control medical" in response.content


# --------------------------------------------------------------------- zi goala


def test_ziua_goala_nu_are_continut(user):
    brief = services.get_or_create_brief(user)
    assert brief.counts == {"appointments": 0, "todo": 0, "emails": 0}
    assert brief.has_content is False


def test_ziua_goala_nu_genereaza_audio(user):
    """Fara nimic de rezumat, nu exista ce sa fie ascultat."""
    brief = services.get_or_create_brief(user)
    assert not brief.audio_file


def test_o_singura_programare_face_ziua_cu_continut(user, appointment_factory):
    appointment_factory(user, day_offset=0, hour=9)
    brief = services.get_or_create_brief(user)
    assert brief.has_content is True
    assert brief.audio_file


def test_doar_un_email_de_urmarit_face_ziua_cu_continut(user, email_factory):
    from apps.integrations.models import EmailReference

    email_factory(user, status=EmailReference.Status.FOLLOW_UP)
    brief = services.get_or_create_brief(user)
    assert brief.counts["emails"] == 1
    assert brief.has_content is True


def test_audio_se_sterge_cand_ziua_se_goleste(user, appointment_factory):
    appointment = appointment_factory(user, day_offset=0, hour=9)
    brief = services.get_or_create_brief(user)
    assert brief.audio_file

    appointment.delete()
    brief = services.get_or_create_brief(user, force=True)

    assert brief.has_content is False
    assert not brief.audio_file


def test_acasa_ascunde_butonul_de_redare_pe_zi_goala(auth_client, user):
    services.get_or_create_brief(user)

    response = auth_client.get(reverse("core:home"))

    assert response.context["brief_has_content"] is False
    assert b"brief-card__play" not in response.content


def test_acasa_arata_butonul_de_redare_cand_exista_continut(
    auth_client, user, appointment_factory
):
    appointment_factory(user, day_offset=0, hour=9)
    services.get_or_create_brief(user, force=True)

    response = auth_client.get(reverse("core:home"))

    assert response.context["brief_has_content"] is True
    assert b"brief-card__play" in response.content


def test_acasa_reconstruieste_rezumatul_invalidat(
    auth_client, user, appointment_factory
):
    services.get_or_create_brief(user)
    appointment_factory(user, day_offset=0, hour=9)

    response = auth_client.get(reverse("core:home"))

    assert response.context["brief_counts"]["appointments"] == 1
    assert response.context["brief"].status == DailyBrief.Status.READY
    assert b"brief-card__play" in response.content


def test_ecranul_rezumat_anunta_ziua_goala(auth_client, user):
    response = auth_client.get(reverse("daily_brief:today"))
    content = response.content.decode()

    assert "Nimic de ascultat astăzi" in content
    assert "data-audio-toggle" not in content


def test_ecranul_rezumat_arata_playerul_cand_exista_continut(
    auth_client, user, appointment_factory
):
    appointment_factory(user, day_offset=0, hour=9)

    response = auth_client.get(reverse("daily_brief:today"))
    content = response.content.decode()

    assert "data-audio-toggle" in content
    assert "Nimic de ascultat astăzi" not in content
