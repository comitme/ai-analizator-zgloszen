"""Reading a batch of customer messages from a file.

Separated from the CLI so the parsing rules are testable without a running API.
The point of this module is the first real-data step: taking a shop's exported
messages and pushing them through the pipeline to find out what it actually does
with traffic nobody wrote for it.
"""

import csv
import json
from pathlib import Path


class BatchFormatError(ValueError):
    """The input file could not be read as tickets. Message is Polish, for the CLI."""


def parse_tickets(path: Path) -> list[str]:
    """Read customer messages from ``.txt``, ``.jsonl`` or ``.csv``.

    * ``.txt``   - one message per line; blank lines and ``#`` comments are skipped.
    * ``.jsonl`` - one JSON object per line, message under ``text`` (or ``tresc``).
    * ``.csv``   - a column named ``text``, ``tresc`` or ``message``.

    Multi-line emails do not survive the ``.txt`` form, which is why the other two
    exist: a real inbox export has paragraphs in it.
    """
    if not path.exists():
        raise BatchFormatError(f"Plik nie istnieje: {path}")

    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        tickets = _from_jsonl(path)
    elif suffix == ".csv":
        tickets = _from_csv(path)
    else:
        tickets = _from_text(path)

    tickets = [t.strip() for t in tickets if t and t.strip()]
    if not tickets:
        raise BatchFormatError(f"Brak zgłoszeń w pliku {path.name}.")
    return tickets


def _from_text(path: Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [line for line in lines if line.strip() and not line.lstrip().startswith("#")]


def _from_jsonl(path: Path) -> list[str]:
    tickets = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BatchFormatError(f"{path.name}, linia {number}: nieprawidłowy JSON.") from exc
        text = _pick(row)
        if text is None:
            raise BatchFormatError(f"{path.name}, linia {number}: brak pola 'text' ani 'tresc'.")
        tickets.append(text)
    return tickets


def _from_csv(path: Path) -> list[str]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return []
    if _pick(rows[0]) is None:
        columns = ", ".join(rows[0].keys())
        raise BatchFormatError(
            f"{path.name}: brak kolumny 'text', 'tresc' ani 'message'. Znalezione: {columns}"
        )
    return [_pick(row) or "" for row in rows]


def _pick(row: dict) -> str | None:
    """Accept the obvious column names, English and Polish, rather than dictating one."""
    for key in ("text", "tresc", "treść", "message", "wiadomosc", "wiadomość"):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None
