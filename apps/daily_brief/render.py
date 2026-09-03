"""Textul determinist al rezumatului zilei.

Aceasta este varianta care se livreaza. AI-ul poate doar reformula, si numai daca
utilizatorul cere asta explicit; nu poate adauga nimic.
"""

from __future__ import annotations

from datetime import date, datetime

from apps.core import dates_ro


def needs_de(count: int) -> bool:
    """In romana, „de" apare cand ultimele doua cifre sunt 00 sau intre 20 si 99."""
    last_two = count % 100
    return count >= 20 and (last_two == 0 or last_two >= 20)


def count_phrase(count: int, singular: str, plural: str, *, feminine: bool = True) -> str:
    """„nicio programare" · „3 programări" · „21 de programări"."""
    if count == 0:
        return f"nicio {singular}" if feminine else f"niciun {singular}"
    if count == 1:
        return f"o {singular}" if feminine else f"un {singular}"
    return f"{count} de {plural}" if needs_de(count) else f"{count} {plural}"


def render_text(snapshot: dict, *, moment: datetime | None = None) -> str:
    """Construieste rezumatul in fraze scurte, potrivite si pentru citire cu voce tare."""
    day = date.fromisoformat(snapshot["date"])
    greeting = dates_ro.greeting_for(moment)
    lines: list[str] = [f"{greeting}, {snapshot['name']}."]
    lines.append(f"Astăzi este {dates_ro.format_weekday_date(day).lower()}.")

    appointments = snapshot.get("appointments", [])
    if appointments:
        lines.append(
            f"Ai {count_phrase(len(appointments), 'programare', 'programări')} "
            f"astăzi. Prima este la {appointments[0]['time']}: {appointments[0]['title']}."
        )
        for item in appointments[1:]:
            place = f", la {item['location']}" if item.get("location") else ""
            lines.append(f"La {item['time']}: {item['title']}{place}.")
    else:
        lines.append("Nu ai nicio programare astăzi.")

    reminders = snapshot.get("reminders", [])
    if reminders:
        lines.append(
            f"Ai {count_phrase(len(reminders), 'alarmă', 'alarme')}: "
            + "; ".join(f"{item['title']} la {item['time']}" for item in reminders)
            + "."
        )

    documents = snapshot.get("documents", [])
    for item in documents:
        due = date.fromisoformat(item["due_date"])
        amount = ""
        if item.get("amount"):
            amount = f", {_format_amount(item['amount'])} {item.get('currency', '')}".rstrip()
        lines.append(
            f"{item['title']} are termen {dates_ro.format_date(due)}{amount}."
        )

    emails = snapshot.get("emails", [])
    if emails:
        senders = ", ".join(item["sender"] for item in emails)
        lines.append(
            f"Ai {count_phrase(len(emails), 'email', 'emailuri', feminine=False)} "
            f"de urmărit, de la {senders}."
        )

    if not appointments and not reminders and not documents and not emails:
        lines.append("Nu ai nimic programat. Poți folosi ziua cum vrei.")

    return "\n".join(lines)


def _format_amount(value) -> str:
    try:
        return f"{float(value):.2f}".replace(".", ",")
    except (TypeError, ValueError):
        return str(value)


def _describe_document(item: dict) -> str:
    """„Factura energie: termen 6 septembrie, 84,20 lei." """
    due = dates_ro.format_date(date.fromisoformat(item["due_date"]))
    text = f"{item['title']}: termen {due}"
    if item.get("amount"):
        text += f", {_format_amount(item['amount'])} {item.get('currency', '')}".rstrip()
    return text + "."


def answer_question(snapshot: dict, question: str) -> str:
    """Raspuns determinist la „Întreabă despre ziua mea", exclusiv din instantaneu."""
    from apps.search.normalize import normalize

    needle = normalize(question)
    appointments = snapshot.get("appointments", [])
    reminders = snapshot.get("reminders", [])
    documents = snapshot.get("documents", [])
    emails = snapshot.get("emails", [])

    if any(word in needle for word in ("prima", "primul", "urmator", "urmatoarea", "incepe")):
        if appointments:
            first = appointments[0]
            place = f", la {first['location']}" if first.get("location") else ""
            return f"Prima programare este la {first['time']}: {first['title']}{place}."
        return "Nu ai nicio programare astăzi."

    if any(word in needle for word in ("cate", "cat", "numar")):
        parts = [
            f"{count_phrase(len(appointments), 'programare', 'programări')}",
            f"{count_phrase(len(reminders), 'alarmă', 'alarme')}",
            f"{count_phrase(len(emails), 'email', 'emailuri', feminine=False)} de urmărit",
        ]
        # „nicio programare" cere negatie la verb: „nu ai", nu „ai".
        verb = "Astăzi nu ai" if all(p.startswith("nici") for p in parts) else "Astăzi ai"
        return f"{verb} {parts[0]}, {parts[1]} și {parts[2]}."

    if any(word in needle for word in ("email", "mesaj", "mail", "raspuns")):
        if emails:
            return "De urmărit: " + "; ".join(
                f"{item['sender']} — {item['subject']}" for item in emails
            ) + "."
        return "Nu ai emailuri de urmărit."

    if any(word in needle for word in ("plat", "factur", "suma", "bani", "termen", "scadent")):
        if documents:
            return " ".join(_describe_document(item) for item in documents)
        return "Nu ai documente cu termen apropiat."

    if any(word in needle for word in ("alarm", "memento", "aminti")):
        if reminders:
            return "Alarme: " + "; ".join(
                f"{item['title']} la {item['time']}" for item in reminders
            ) + "."
        return "Nu ai alarme astăzi."

    if any(word in needle for word in ("liber", "gol", "ocupat", "cum arata")):
        if not appointments:
            return "Ziua ta este liberă de programări."
        return (
            f"Ai {count_phrase(len(appointments), 'programare', 'programări')}, "
            f"între {appointments[0]['time']} și {appointments[-1]['time']}."
        )

    return render_text(snapshot)
