#!/usr/bin/env python
"""Utilitar de linie de comanda Django."""

import os
import sys

from config.env import default_settings_module


def main():
    # Consola Windows este implicit cp1252 si nu poate afisa diacritice romanesti.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", default_settings_module())
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django nu a putut fi importat. Este mediul virtual activat?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
