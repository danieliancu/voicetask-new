"""Formatare si vocabular de date in limba romana."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from django.utils import timezone

MONTHS = (
    "ianuarie",
    "februarie",
    "martie",
    "aprilie",
    "mai",
    "iunie",
    "iulie",
    "august",
    "septembrie",
    "octombrie",
    "noiembrie",
    "decembrie",
)

MONTHS_SHORT = ("IAN", "FEB", "MAR", "APR", "MAI", "IUN", "IUL", "AUG", "SEP", "OCT", "NOI", "DEC")

WEEKDAYS = ("luni", "marți", "miercuri", "joi", "vineri", "sâmbătă", "duminică")

WEEKDAYS_SHORT = ("LUN", "MAR", "MIE", "JOI", "VIN", "SÂM", "DUM")


def local_date(value: datetime | date | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return timezone.localtime(value).date() if timezone.is_aware(value) else value.date()
    return value


def format_date(value: datetime | date | None, *, with_year: bool = False) -> str:
    day = local_date(value)
    if day is None:
        return ""
    text = f"{day.day} {MONTHS[day.month - 1]}"
    return f"{text} {day.year}" if with_year else text


def format_weekday_date(value: datetime | date | None) -> str:
    day = local_date(value)
    if day is None:
        return ""
    return f"{WEEKDAYS[day.weekday()].capitalize()}, {format_date(day)}"


def format_time(value: datetime | None) -> str:
    if value is None:
        return ""
    local = timezone.localtime(value) if timezone.is_aware(value) else value
    return f"{local.hour:02d}:{local.minute:02d}"


def relative_day_label(value: datetime | date | None, *, today: date | None = None) -> str:
    """„Astăzi", „Mâine", „Poimâine", „Ieri" sau data scurtă."""
    day = local_date(value)
    if day is None:
        return ""
    today = today or timezone.localdate()
    delta = (day - today).days
    if delta == 0:
        return "Astăzi"
    if delta == 1:
        return "Mâine"
    if delta == 2:
        return "Poimâine"
    if delta == -1:
        return "Ieri"
    return format_date(day, with_year=day.year != today.year)


def short_tab_label(value: datetime | date | None, *, today: date | None = None) -> str:
    """Eticheta de pe tabul lateral al cardului: „MÂINE" sau „6 SEP"."""
    day = local_date(value)
    if day is None:
        return ""
    today = today or timezone.localdate()
    delta = (day - today).days
    if delta == 0:
        return "AZI"
    if delta == 1:
        return "MÂINE"
    return f"{day.day} {MONTHS_SHORT[day.month - 1]}"


def greeting_for(moment: datetime | None = None) -> str:
    moment = moment or timezone.localtime()
    hour = moment.hour
    if hour < 11:
        return "Bună dimineața"
    if hour < 18:
        return "Bună ziua"
    return "Bună seara"


def week_bounds(day: date) -> tuple[date, date]:
    """Luni -> duminică pentru saptamana care contine `day`."""
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


def humanize_offset(minutes: int) -> str:
    """Transforma un decalaj de alarmă în text: 1440 -> „Cu o zi înainte"."""
    if minutes <= 0:
        return "La momentul evenimentului"
    if minutes % 1440 == 0:
        days = minutes // 1440
        return "Cu o zi înainte" if days == 1 else f"Cu {days} zile înainte"
    if minutes % 60 == 0:
        hours = minutes // 60
        return "Cu o oră înainte" if hours == 1 else f"Cu {hours} ore înainte"
    return f"Cu {minutes} de minute înainte" if minutes >= 20 else f"Cu {minutes} minute înainte"
