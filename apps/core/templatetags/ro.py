"""Filtre de formatare in limba romana pentru sabloane."""

from __future__ import annotations

from django import template

from apps.core import dates_ro

register = template.Library()

register.filter("data_ro", dates_ro.format_date)
register.filter("data_zi_ro", dates_ro.format_weekday_date)
register.filter("ora_ro", dates_ro.format_time)
register.filter("zi_relativa", dates_ro.relative_day_label)
register.filter("eticheta_tab", dates_ro.short_tab_label)
register.filter("decalaj_alarma", dates_ro.humanize_offset)


@register.filter
def data_ora_ro(value) -> str:
    if value is None:
        return ""
    return f"{dates_ro.relative_day_label(value)} • {dates_ro.format_time(value)}"


@register.filter
def suma_ro(value, currency: str = "") -> str:
    """84.2 -> „84,20 lei"; separatorul zecimal romanesc este virgula."""
    if value in (None, ""):
        return ""
    text = f"{float(value):,.2f}".replace(",", " ").replace(".", ",")
    return f"{text} {currency}".strip()


@register.filter
def numar_ro(count, forms: str) -> str:
    """Acordul numeralului: `{{ n|numar_ro:"programare,programări" }}`.

    In romana, „de" apare cand ultimele doua cifre sunt 00 sau intre 20 si 99:
    1 programare · 3 programări · 21 de programări.
    """
    try:
        count = int(count)
    except (TypeError, ValueError):
        return ""
    singular, _, plural = forms.partition(",")
    plural = plural or singular
    if count == 1:
        return f"1 {singular}"
    last_two = count % 100
    if count >= 20 and (last_two == 0 or last_two >= 20):
        return f"{count} de {plural}"
    return f"{count} {plural}"


@register.filter
def procent(value) -> str:
    if value in (None, ""):
        return ""
    return f"{float(value) * 100:.0f}%"


@register.simple_tag(takes_context=True)
def query_string(context, **kwargs) -> str:
    """Reconstruieste query stringul curent cu parametrii modificati."""
    params = context["request"].GET.copy()
    for key, value in kwargs.items():
        if value in (None, ""):
            params.pop(key, None)
        else:
            params[key] = value
    encoded = params.urlencode()
    return f"?{encoded}" if encoded else ""
