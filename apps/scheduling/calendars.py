"""Construirea modelelor de vizualizare pentru calendar: zi, saptamana, luna.

Doar date — niciun HTML. Sabloanele primesc structuri gata calculate.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from django.utils import timezone

from apps.core import dates_ro


@dataclass
class DayCell:
    day: date
    is_today: bool
    is_selected: bool
    in_month: bool
    count: int = 0
    weekday_short: str = ""


@dataclass
class AgendaEntry:
    """O intrare din agenda: fie o programare, fie o alarma de sine statatoare."""

    appointment: object = None
    reminder: object | None = None

    @property
    def starts_at(self):
        return self.appointment.starts_at if self.appointment else self.reminder.remind_at

    @property
    def is_standalone_reminder(self) -> bool:
        return self.appointment is None


@dataclass
class CalendarContext:
    view: str
    day: date
    week: list[DayCell] = field(default_factory=list)
    month: list[list[DayCell]] = field(default_factory=list)
    entries: list = field(default_factory=list)
    prev_url_date: date | None = None
    next_url_date: date | None = None
    title: str = ""


VIEWS = (("zi", "Zi"), ("saptamana", "Săptămână"), ("luna", "Lună"))


def day_bounds(day: date) -> tuple[datetime, datetime]:
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(day, time.min), tz)
    return start, start + timedelta(days=1)


def range_bounds(start_day: date, end_day: date) -> tuple[datetime, datetime]:
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(start_day, time.min), tz)
    end = timezone.make_aware(datetime.combine(end_day + timedelta(days=1), time.min), tz)
    return start, end


def build(user, *, view: str, day: date) -> CalendarContext:
    from apps.scheduling.models import Appointment, Reminder

    today = timezone.localdate()
    week_start, week_end = dates_ro.week_bounds(day)

    if view == "zi":
        start, end = day_bounds(day)
        prev_date, next_date = day - timedelta(days=1), day + timedelta(days=1)
        title = dates_ro.format_weekday_date(day)
    elif view == "saptamana":
        start, end = range_bounds(week_start, week_end)
        prev_date, next_date = day - timedelta(days=7), day + timedelta(days=7)
        title = f"{dates_ro.format_date(week_start)} – {dates_ro.format_date(week_end)}"
    else:
        first = day.replace(day=1)
        last = day.replace(day=calendar.monthrange(day.year, day.month)[1])
        start, end = range_bounds(first, last)
        prev_date = (first - timedelta(days=1)).replace(day=1)
        next_date = last + timedelta(days=1)
        title = f"{dates_ro.MONTHS[day.month - 1].capitalize()} {day.year}"

    appointments = list(
        Appointment.objects.for_user(user)
        .filter(starts_at__gte=start, starts_at__lt=end)
        .prefetch_related("reminders")
        .order_by("starts_at")
    )

    standalone_reminders = list(
        Reminder.objects.for_user(user)
        .filter(remind_at__gte=start, remind_at__lt=end, appointment__isnull=True)
        .exclude(status=Reminder.Status.DONE)
        .order_by("remind_at")
    )

    entries = [
        AgendaEntry(
            appointment=appointment,
            reminder=appointment.reminders.filter(status=Reminder.Status.SCHEDULED)
            .order_by("remind_at")
            .first(),
        )
        for appointment in appointments
    ]
    # Alarmele care nu apartin unei programari sunt tot parte din agenda zilei.
    entries += [AgendaEntry(reminder=reminder) for reminder in standalone_reminders]
    entries.sort(key=lambda entry: entry.starts_at)

    week_counts = _counts_by_day(user, week_start, week_end)
    week = [
        DayCell(
            day=week_start + timedelta(days=index),
            is_today=(week_start + timedelta(days=index)) == today,
            is_selected=(week_start + timedelta(days=index)) == day,
            in_month=True,
            count=week_counts.get(week_start + timedelta(days=index), 0),
            weekday_short=dates_ro.WEEKDAYS_SHORT[index],
        )
        for index in range(7)
    ]

    month_grid: list[list[DayCell]] = []
    if view == "luna":
        month_grid = _month_grid(user, day, today)

    return CalendarContext(
        view=view,
        day=day,
        week=week,
        month=month_grid,
        entries=entries,
        prev_url_date=prev_date,
        next_url_date=next_date,
        title=title,
    )


def _counts_by_day(user, start_day: date, end_day: date) -> dict[date, int]:
    from apps.scheduling.models import Appointment

    start, end = range_bounds(start_day, end_day)
    counts: dict[date, int] = {}
    for appointment in Appointment.objects.for_user(user).filter(
        starts_at__gte=start, starts_at__lt=end
    ):
        key = timezone.localtime(appointment.starts_at).date()
        counts[key] = counts.get(key, 0) + 1
    return counts


def _month_grid(user, day: date, today: date) -> list[list[DayCell]]:
    first = day.replace(day=1)
    last = day.replace(day=calendar.monthrange(day.year, day.month)[1])
    grid_start = first - timedelta(days=first.weekday())
    grid_end = last + timedelta(days=6 - last.weekday())
    counts = _counts_by_day(user, grid_start, grid_end)

    weeks: list[list[DayCell]] = []
    current = grid_start
    while current <= grid_end:
        row = []
        for _ in range(7):
            row.append(
                DayCell(
                    day=current,
                    is_today=current == today,
                    is_selected=current == day,
                    in_month=current.month == day.month,
                    count=counts.get(current, 0),
                    weekday_short=dates_ro.WEEKDAYS_SHORT[current.weekday()],
                )
            )
            current += timedelta(days=1)
        weeks.append(row)
    return weeks
