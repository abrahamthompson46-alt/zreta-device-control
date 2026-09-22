#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    load_dotenv(root / ".env")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "zreta_control.settings.local")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Activate the virtualenv and install backend dependencies."
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
