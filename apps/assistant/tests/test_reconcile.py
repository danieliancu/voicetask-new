"""Reconcilierea rezultatului AI cu parserul determinist.

Fiecare test descrie o situatie in care modelul si `ro_time` nu spun acelasi lucru.
Regula verificata peste tot este aceeasi: informatia rostita ajunge in campul ei,
informatia nerostita nu ajunge nicaieri, iar ce nu se poate decide devine intrebare.
"""

from __future__ import annotations

from datetime import date, time

import pytest
import time_machine

from apps.accounts.models import UserPreference
from apps.assistant import services
from apps.assistant.models import IntentDraft
from apps.assistant.schemas import Intent
from apps.assistant.tests._stubs import ACUM, MAINE, POIMAINE, ModelSimulat
from apps.core.providers.registry import override_provider

pytestmark = pytest.mark.django_db


def interpreteaza(user, text: str, **raspuns_model) -> IntentDraft:
    """Interpreteaza `text` cu un model care raspunde exact `raspuns_model`."""
    model = ModelSimulat(intent=Intent.CREATE_APPOINTMENT, confidence=0.9, **raspuns_model)
    with time_machine.travel(ACUM, tick=False), override_provider("intent", model):
        return services.interpret(user, text)


# --------------------------------------------------------- data si ora din Python


VARIANTE_MAINE = [
    "Mă întâlnesc mâine cu Ion.",
    "Ma intalnesc MAINE cu Ion.",
    "Mă văd mâine cu Ion.",
    "Am întâlnire mâine cu Ion.",
    "Programează o întâlnire mâine cu Ion.",
    "ma intalnesc maine cu ion",
    "MĂ ÎNTÂLNESC MÂINE CU ION!",
]


@pytest.mark.parametrize("text", VARIANTE_MAINE)
def test_data_lipsa_din_raspunsul_modelului_este_completata_din_text(user, text):
    """Cazul raportat: modelul intoarce `date: null`, dar textul contine „mâine"."""
    draft = interpreteaza(user, text, date=None, start_time=None, title="Întâlnire cu Ion")

    assert draft.intent == Intent.CREATE_APPOINTMENT
    assert draft.payload["date"] == MAINE
    assert draft.payload["start_time"] is None


@pytest.mark.parametrize("text", VARIANTE_MAINE)
def test_diacriticele_si_majusculele_nu_schimba_rezultatul(user, text):
    draft = interpreteaza(user, text, date=MAINE, start_time=None, title="Întâlnire cu Ion")
    assert draft.payload["date"] == MAINE


def test_aceeasi_data_de_la_model_si_din_text_este_acceptata(user):
    draft = interpreteaza(
        user, "Mă întâlnesc mâine cu Ion.", date=MAINE, start_time=None, title="Întâlnire cu Ion"
    )

    assert draft.payload["date"] == MAINE
    assert "data_in_conflict" not in draft.payload["ambiguity"]


def test_data_diferita_de_cea_din_text_blocheaza_confirmarea(user):
    """Modelul spune altceva decat s-a rostit: se pastreaza textul si se intreaba."""
    draft = interpreteaza(
        user,
        "Mă întâlnesc mâine cu Ion.",
        date="2026-12-25",
        start_time="10:00",
        title="Întâlnire cu Ion",
    )

    assert draft.payload["date"] == MAINE
    assert "data_in_conflict" in draft.payload["ambiguity"]
    assert draft.status == IntentDraft.Status.NEEDS_CLARIFICATION


def test_data_inventata_fara_niciun_indiciu_in_text_este_scoasa(user):
    """Fraza nu contine nicio referinta la timp; data modelului nu are sustinere."""
    draft = interpreteaza(
        user,
        "Programează o întâlnire cu Ion.",
        date="2026-09-10",
        start_time="10:00",
        title="Întâlnire cu Ion",
    )

    assert draft.payload["date"] is None
    assert draft.payload["start_time"] is None
    assert draft.status == IntentDraft.Status.NEEDS_CLARIFICATION
    assert draft.clarification_question == "Pentru ce dată să o programez?"


def test_ora_inventata_este_scoasa_chiar_daca_data_este_rostita(user):
    """„Mâine" se aude, ora nu. Ora modelului nu are ce cauta in schita."""
    draft = interpreteaza(
        user, "Mă întâlnesc mâine cu Ion.", date=MAINE, start_time="10:00", title="Întâlnire cu Ion"
    )

    assert draft.payload["date"] == MAINE
    assert draft.payload["start_time"] is None
    assert draft.clarification_question == "La ce oră este întâlnirea?"


def test_expresie_temporala_neinteligibila_pastreaza_valoarea_dar_intreaba(user):
    """S-a rostit ceva despre timp, dar `ro_time` nu il citeste: nu tacem, intrebam."""
    draft = interpreteaza(
        user,
        "Mă întâlnesc în a treia zi lucrătoare cu Ion.",
        date="2026-09-04",
        start_time=None,
        title="Întâlnire cu Ion",
    )

    assert draft.payload["date"] == "2026-09-04"
    assert "data_neclara" in draft.payload["ambiguity"]
    assert draft.status == IntentDraft.Status.NEEDS_CLARIFICATION


@pytest.mark.parametrize(
    "text,zi,ora",
    [
        ("Mă întâlnesc poimâine la 14 cu Ana.", POIMAINE, "14:00:00"),
        ("Mă văd vineri la 10 cu Maria.", "2026-09-04", "10:00:00"),
        ("Mă întâlnesc pe 5 septembrie la 14:30 cu Ion.", "2026-09-05", "14:30:00"),
        ("Peste două săptămâni mă întâlnesc cu medicul.", "2026-09-15", None),
        ("Mă întâlnesc mâine dimineață.", MAINE, "09:00:00"),
    ],
)
def test_formele_rostite_ajung_in_campurile_lor(user, text, zi, ora):
    draft = interpreteaza(user, text, date=None, start_time=None, title=None)

    assert draft.payload["date"] == zi
    assert draft.payload["start_time"] == ora


@pytest.mark.parametrize("text", ["Mă întâlnesc vineri la 3.", "Mă văd vineri la trei."])
def test_ora_ambigua_produce_o_intrebare(user, text):
    """„La trei" poate fi 03:00 sau 15:00. Nu alegem in locul utilizatorului."""
    draft = interpreteaza(user, text, date=None, start_time=None, title=None)

    assert draft.payload["date"] == "2026-09-04"
    assert "ora_ambigua" in draft.payload["ambiguity"]
    assert draft.status == IntentDraft.Status.NEEDS_CLARIFICATION


def test_comanda_fara_data_cere_data(user):
    draft = interpreteaza(
        user,
        "Programează o întâlnire cu Ion.",
        date=None,
        start_time=None,
        title="Întâlnire cu Ion",
    )

    assert draft.status == IntentDraft.Status.NEEDS_CLARIFICATION
    assert draft.clarification_question == "Pentru ce dată să o programez?"


# ------------------------------------------------------------------ fusuri orare


@pytest.mark.parametrize(
    "fus,zi_asteptata",
    [("Europe/Bucharest", date(2026, 9, 3)), ("Europe/London", date(2026, 9, 2))],
)
def test_maine_se_calculeaza_in_fusul_utilizatorului(user, fus, zi_asteptata):
    """La 00:30 in Bucuresti este inca 22:30 la Londra — „mâine" nu e aceeasi zi.

    Fara fusul utilizatorului, comanda rostita dupa miezul noptii ar cadea pe ziua
    gresita pentru oricine nu locuieste in fusul serverului.
    """
    prefs = UserPreference.for_user(user)
    prefs.timezone = fus
    prefs.save(update_fields=["timezone"])

    model = ModelSimulat(intent=Intent.CREATE_APPOINTMENT, confidence=0.9, date=None)
    dupa_miezul_noptii = ACUM.replace(day=2, hour=0, minute=30)
    with (
        time_machine.travel(dupa_miezul_noptii, tick=False),
        override_provider("intent", model),
    ):
        draft = services.interpret(user, "Mă întâlnesc mâine la 10 cu Ion.")

    assert draft.payload["date"] == zi_asteptata.isoformat()


# ---------------------------------------------- informatii fara acoperire in text


def test_persoana_absenta_din_transcriere_este_scoasa(user):
    draft = interpreteaza(
        user, "Mă întâlnesc mâine cu Ion.", date=None, start_time=None, person="Gheorghe Popa"
    )

    assert draft.payload["person"] == "Ion"
    assert "informatie_nesustinuta" in draft.payload["ambiguity"]


def test_locatia_absenta_din_transcriere_este_scoasa(user):
    draft = interpreteaza(
        user,
        "Mă întâlnesc mâine cu Ion.",
        date=None,
        start_time=None,
        location="Cabinet stomatologic",
    )

    assert draft.payload["location"] is None
    assert "informatie_nesustinuta" in draft.payload["ambiguity"]


def test_persoana_rostita_este_pastrata_indiferent_de_diacritice(user):
    draft = interpreteaza(
        user, "Mă întâlnesc mâine cu Ștefan.", date=None, start_time=None, person="Stefan"
    )

    assert draft.payload["person"] == "Stefan"
    assert "informatie_nesustinuta" not in draft.payload["ambiguity"]


def test_locatia_rostita_este_pastrata(user):
    draft = interpreteaza(
        user,
        "Programare mâine la 12 la clinica Regina Maria.",
        date=None,
        start_time=None,
        location="Clinica Regina Maria",
    )

    assert draft.payload["location"] == "Clinica Regina Maria"
    assert "informatie_nesustinuta" not in draft.payload["ambiguity"]


# -------------------------------------------------------------------- intentie


def test_notita_devine_programare_cand_textul_contine_verbul_intalnirii(user):
    """Fara verb de comanda, modelul cade pe notita; verbul rostit spune altceva."""
    model = ModelSimulat(intent=Intent.CREATE_NOTE, confidence=0.9, title="Ion")
    with time_machine.travel(ACUM, tick=False), override_provider("intent", model):
        draft = services.interpret(user, "Mă întâlnesc mâine cu Ion.")

    assert draft.intent == Intent.CREATE_APPOINTMENT
    assert draft.payload["date"] == MAINE


def test_verbul_de_notare_impiedica_promovarea(user):
    """„Notează că mă întâlnesc mâine" ramane notita: verbul de comanda decide."""
    model = ModelSimulat(intent=Intent.CREATE_NOTE, confidence=0.9, title="Întâlnire cu Ion")
    with time_machine.travel(ACUM, tick=False), override_provider("intent", model):
        draft = services.interpret(user, "Notează că mă întâlnesc mâine cu Ion.")

    assert draft.intent == Intent.CREATE_NOTE


def test_stergerea_ceruta_de_model_pe_o_comanda_de_creare_blocheaza_confirmarea(user):
    model = ModelSimulat(
        intent=Intent.DELETE_ITEM, confidence=0.9, title="Întâlnire", clarification_required=False
    )
    with time_machine.travel(ACUM, tick=False), override_provider("intent", model):
        draft = services.interpret(user, "Programează o întâlnire mâine la 10 cu Ion.")

    assert "intentie_in_conflict" in draft.payload["ambiguity"]
    assert draft.status == IntentDraft.Status.NEEDS_CLARIFICATION


# ------------------------------------------------------------------------ titlu


def test_titlul_lipsa_este_construit_din_persoana(user):
    draft = interpreteaza(
        user, "Mă întâlnesc mâine cu Ion.", date=None, start_time=None, title=None
    )

    assert draft.payload["title"] == "Întâlnire cu Ion"


def test_titlul_dat_de_model_nu_este_inlocuit(user):
    draft = interpreteaza(
        user, "Mă întâlnesc mâine cu Ion.", date=None, start_time=None, title="Cafea cu Ion"
    )

    assert draft.payload["title"] == "Cafea cu Ion"


def test_ora_de_final_dinaintea_orei_de_inceput_nu_blocheaza_schita(user):
    """Ora de inceput corectata din text nu are voie sa faca schema sa refuze tot."""
    draft = interpreteaza(
        user,
        "Mă întâlnesc mâine la 18 cu Ion.",
        date=None,
        start_time="09:00",
        end_time="10:00",
        title="Întâlnire cu Ion",
    )

    assert draft.payload["start_time"] == "18:00:00"
    assert draft.payload["end_time"] is None


def test_nimic_nu_se_salveaza_la_interpretare(user):
    from apps.notes.models import Note
    from apps.scheduling.models import Appointment

    interpreteaza(user, "Mă întâlnesc mâine la 10 cu Ion.", date=None, start_time=None)

    assert Appointment.objects.count() == 0
    assert Note.objects.count() == 0


def test_timpul_este_citit_din_context_nu_din_ceasul_serverului(user):
    """`ro_time` primeste momentul din context; `now` explicit ramane singura sursa."""
    model = ModelSimulat(intent=Intent.CREATE_APPOINTMENT, confidence=0.9, date=None)
    with time_machine.travel(ACUM.replace(day=30, month=9), tick=False), override_provider(
        "intent", model
    ):
        draft = services.interpret(user, "Mă întâlnesc mâine la 10 cu Ion.")

    assert draft.payload["date"] == "2026-10-01"
    assert draft.payload["start_time"] == time(10, 0).isoformat()


def test_motivele_nu_se_repeta_in_ambiguitate(user):
    """Parserul si reconcilierea pot semnala acelasi lucru; intrebarea este una."""
    draft = interpreteaza(user, "Mă întâlnesc vineri la 3.", date=None, start_time=None)

    ambiguity = draft.payload["ambiguity"]
    assert ambiguity.count("ora_ambigua") == 1


def test_titlul_care_repeta_doar_numele_persoanei_este_inlocuit(user):
    """Un titlu „Ion" nu adauga nimic peste campul „persoană"."""
    draft = interpreteaza(
        user, "Mă întâlnesc mâine cu Ion.", date=None, start_time=None, title="Ion"
    )

    assert draft.payload["title"] == "Întâlnire cu Ion"
