"""Cautarea unificata: surse multiple, filtre, sortare, cautari recente."""

import pytest
from django.urls import reverse

from apps.search import service
from apps.search.models import RecentSearch
from apps.search.normalize import cut_spans, fold, normalize, tokens

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------- normalizare


@pytest.mark.parametrize(
    "text,asteptat",
    [
        ("Ședință", "sedinta"),
        ("Ședință", "sedinta"),  # ş cu sedila, varianta veche Unicode
        ("PĂRINȚII", "parintii"),
        ("Cluj-Napoca", "cluj-napoca"),
        ("  spatii   multiple  ", "spatii multiple"),
        ("Întâlnire", "intalnire"),
    ],
)
def test_normalizarea_scoate_diacriticele(text, asteptat):
    assert normalize(text) == asteptat


def test_fold_pastreaza_pozitiile():
    text = "Ședință cu părinții"
    assert len(fold(text)) == len(text)
    assert fold(text) == "sedinta cu parintii"


def test_cut_spans_taie_exact_intervalele():
    text = "Întâlnire mâine la 10"
    assert cut_spans(text, [(10, 21)]) == "Întâlnire"


def test_tokens_ignora_semnele():
    assert tokens("Factura, energie!") == ["factura", "energie"]


# --------------------------------------------------------------------- cautare


def test_cautarea_gaseste_in_toate_sursele(user, note_factory, appointment_factory, email_factory):
    note_factory(user, title="Factura energie", content="Plată prin debit direct")
    appointment_factory(user, title="Factura la contabil")
    email_factory(user, subject="Factura ta este disponibilă")

    results = service.search(user, "factura")
    surse = {hit.kind for hit in results.hits}

    assert {"notita", "programare", "email"} <= surse


def test_cautarea_ignora_diacriticele(user, note_factory):
    note_factory(user, title="Ședință cu părinții")

    assert service.search(user, "sedinta").total == 1
    assert service.search(user, "Ședință").total == 1
    assert service.search(user, "PARINTII").total == 1


def test_titlul_are_prioritate_fata_de_continut(user, note_factory):
    in_titlu = note_factory(user, title="Energie verde", content="altceva")
    note_factory(user, title="Altceva", content="energie undeva în text")

    results = service.search(user, "energie")

    assert results.hits[0].pk == in_titlu.pk


def test_filtrarea_pe_o_singura_sursa(user, note_factory, appointment_factory):
    note_factory(user, title="Factura energie")
    appointment_factory(user, title="Factura la contabil")

    results = service.search(user, "factura", sources=["notite"])

    assert {hit.kind for hit in results.hits} == {"notita"}


def test_rezultatele_poarta_eticheta_sursei(user, note_factory):
    note_factory(user, title="Factura energie")
    hit = service.search(user, "factura").hits[0]
    assert hit.source_label
    assert hit.url


def test_cautarea_nu_vede_datele_altui_utilizator(user, other_user, note_factory):
    note_factory(other_user, title="Secret")
    assert service.search(user, "secret").total == 0


def test_obiectele_din_cos_nu_apar_in_rezultate(user, note_factory):
    note = note_factory(user, title="Factura energie")
    note.delete()
    assert service.search(user, "factura").total == 0


def test_sortarea_dupa_data(user, appointment_factory):
    tarziu = appointment_factory(user, title="Factura târziu", day_offset=10)
    devreme = appointment_factory(user, title="Factura devreme", day_offset=1)

    results = service.search(user, "factura", sort="data")

    assert [hit.pk for hit in results.hits] == [devreme.pk, tarziu.pk]


# --------------------------------------------------------------------- view-uri


def test_endpointul_de_rezultate(auth_client, user, note_factory):
    note_factory(user, title="Factura energie")

    response = auth_client.get(
        reverse("search:results"), {"q": "factura"}, headers={"HX-Request": "true"}
    )

    assert b"Factura energie" in response.content


def test_interogarile_prea_scurte_nu_se_executa(auth_client, user):
    response = auth_client.get(reverse("search:results"), {"q": "a"})
    assert "cel puțin două litere" in response.content.decode()


def test_cautarile_recente_se_salveaza_o_singura_data(auth_client, user):
    for _ in range(3):
        auth_client.get(reverse("search:results"), {"q": "factura"})

    recente = RecentSearch.objects.for_user(user)
    assert recente.count() == 1
    assert recente.get().hit_count == 3


def test_cautarile_recente_se_pot_sterge(auth_client, user):
    auth_client.get(reverse("search:results"), {"q": "factura"})
    auth_client.post(reverse("search:clear_recent"))
    assert RecentSearch.objects.for_user(user).count() == 0


def test_cautarile_recente_sunt_separate_pe_utilizatori(auth_client, user, other_user):
    auth_client.get(reverse("search:results"), {"q": "factura"})
    assert RecentSearch.objects.for_user(other_user).count() == 0


@pytest.mark.pg_only
def test_backendul_postgres_este_selectat_pe_postgres():
    from django.db import connection

    from apps.search.backends.base import get_backend

    if connection.vendor != "postgresql":
        pytest.skip("Necesită PostgreSQL.")
    assert get_backend().name == "postgresql"
