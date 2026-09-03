"""Extragerea datelor din documente romanesti."""

from datetime import date, time

import pytest

from apps.documents.pipeline.extract import extract

FACTURA = """energio energie pentru tine
FACTURA ENERGIE ELECTRICA
Seria EL 12345678
Popescu Andrei
Str. Exemplului nr. 10, bl. B1, ap. 12
400123 Cluj-Napoca, Cluj
CUI: RO12345678
Data emiterii 01.09.2026
DATA LIMITA DE PLATA
06.09.2026
TOTAL DE PLATA
84,20 lei
"""

INVITATIE = """INVITATIE
Va invitam la serbarea scolara de sfarsit de an
Scoala Nr. 12, Sala festiva
Sambata, 14 septembrie 2026, ora 10:00
"""

BON = """BON FISCAL
Casa de marcat nr. 3
TOTAL 37,50 lei
"""


def test_data_limita_de_plata():
    result = extract(FACTURA)
    assert result.fields["due_date"].value == date(2026, 9, 6)
    assert result.fields["due_date"].confidence > 0.7


def test_data_emiterii_este_separata_de_data_limita():
    result = extract(FACTURA)
    assert result.fields["document_date"].value == date(2026, 9, 1)


def test_suma_cu_virgula_zecimala():
    result = extract(FACTURA)
    assert result.fields["amount"].value == 84.20
    assert result.fields["currency"].value == "lei"


def test_tipul_documentului_este_recunoscut():
    assert extract(FACTURA).document_type == "invoice"
    assert extract(INVITATIE).document_type == "invitation"
    assert extract(BON).document_type == "receipt"


def test_codul_fiscal():
    assert extract(FACTURA).fields["tax_id"].value == "RO12345678"


def test_adresa_si_orasul():
    result = extract(FACTURA)
    assert "Exemplului" in result.fields["address"].value
    assert result.fields["city"].value == "Cluj-Napoca"


def test_data_scrisa_in_litere():
    result = extract(INVITATIE)
    assert result.fields["event_date"].value == date(2026, 9, 14)


def test_ora_evenimentului():
    assert extract(INVITATIE).fields["time"].value == time(10, 0)


def test_actiunea_propusa_urmeaza_datele_gasite():
    assert extract(FACTURA).fields["suggested_action"].value == "reminder"
    assert extract(INVITATIE).fields["suggested_action"].value == "appointment"
    assert extract("Text fara nimic util").fields["suggested_action"].value == "note"


def test_suma_etichetata_bate_un_numar_oarecare():
    text = "Cod client 12345\nTOTAL DE PLATA 84,20 lei"
    result = extract(text)
    assert result.fields["amount"].value == 84.20


def test_textul_gol_nu_produce_campuri():
    assert extract("").fields == {}


def test_titlul_este_derivat_din_prima_linie_utila():
    assert "energie" in extract(FACTURA).title.lower()


@pytest.mark.parametrize(
    "text,asteptat",
    [
        ("Scadenta 06.09.2026", date(2026, 9, 6)),
        ("Termen de plata 6 septembrie 2026", date(2026, 9, 6)),
        ("DATA LIMITA 06/09/2026", date(2026, 9, 6)),
        ("Plata pana la 06-09-2026", date(2026, 9, 6)),
    ],
)
def test_variantele_de_eticheta_pentru_scadenta(text, asteptat):
    assert extract(text).fields["due_date"].value == asteptat


@pytest.mark.parametrize(
    "text,valoare,moneda",
    [
        ("TOTAL DE PLATA 84,20 lei", 84.20, "lei"),
        ("TOTAL DE PLATA 1.234,56 lei", 1234.56, "lei"),
        ("TOTAL DE PLATA 84.20 EUR", 84.20, "EUR"),
        ("TOTAL DE PLATA 37 RON", 37.0, "lei"),
    ],
)
def test_formatele_de_suma(text, valoare, moneda):
    result = extract(text)
    assert result.fields["amount"].value == valoare
    assert result.fields["currency"].value == moneda


def test_increderea_scade_pentru_randuri_slab_recunoscute():
    from apps.core.providers.base import OCRLine

    linii_bune = [
        OCRLine("DATA LIMITA DE PLATA", 0.95),
        OCRLine("06.09.2026", 0.95),
    ]
    linii_slabe = [
        OCRLine("DATA LIMITA DE PLATA", 0.35),
        OCRLine("06.09.2026", 0.35),
    ]

    bun = extract("", linii_bune).fields["due_date"].confidence
    slab = extract("", linii_slabe).fields["due_date"].confidence

    assert bun > slab


# --------------------------------------------------------------------- OCR lipit

#: Asa arata iesirea unui motor OCR antrenat pe alta limba: fara spatii.
FACTURA_LIPITA = """FACTURAENERGIEELECTRICA
SeriaEL12345678
PopescuAndrei
Str.Exempluluinr.10,bl.B1,ap.12
400123Cluj-Napoca,Cluj
CUI:RO12345678
Dataemiteri01.09.2026
DATALIMITADEPLATA
06.09.2026
TOTALDEPLATA
84,20 lei
"""


def test_eticheta_lipita_este_recunoscuta():
    result = extract(FACTURA_LIPITA)
    assert result.fields["due_date"].value == date(2026, 9, 6)


def test_suma_din_document_lipit():
    result = extract(FACTURA_LIPITA)
    assert result.fields["amount"].value == 84.20
    assert result.fields["currency"].value == "lei"


def test_tipul_documentului_din_text_lipit():
    assert extract(FACTURA_LIPITA).document_type == "invoice"


def test_data_nu_este_confundata_cu_ora():
    """„06.09.2026" nu trebuie citit ca ora 06:09."""
    assert "time" not in extract(FACTURA_LIPITA).fields


def test_codul_fiscal_nu_devine_suma():
    """Fara eticheta si fara moneda, un cod fiscal nu este o suma."""
    result = extract("CUI: RO12345678\nAlt text fara suma")
    assert "amount" not in result.fields


def test_suma_fara_eticheta_are_nevoie_de_moneda():
    assert "amount" not in extract("Numar contract 987654").fields
    assert extract("Am plătit 45,00 lei").fields["amount"].value == 45.0


@pytest.mark.parametrize(
    "text,asteptat",
    [
        ("ora 10:00", time(10, 0)),
        ("Sambata, 14 septembrie 2026, ora 10:00", time(10, 0)),
        ("Incepe la 17:30", time(17, 30)),
        ("ora 9.15", time(9, 15)),
    ],
)
def test_orele_valide_sunt_recunoscute(text, asteptat):
    assert extract(text).fields["time"].value == asteptat


@pytest.mark.parametrize("text", ["06.09.2026", "Data 01.09.2026", "1.234,56 lei"])
def test_datele_si_sumele_nu_devin_ore(text):
    assert "time" not in extract(text).fields
