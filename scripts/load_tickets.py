"""Push a file of customer messages through a running API.

This is the first-real-data step: take a shop's exported inbox and find out what the
pipeline does with traffic nobody wrote for it. Everything before this point is
measured on messages we invented ourselves.

    python scripts/load_tickets.py maile.txt --dry-run   # policz koszt, nic nie wysyłaj
    python scripts/load_tickets.py maile.jsonl           # wyślij (zapyta o potwierdzenie)
    python scripts/load_tickets.py maile.csv --limit 20  # pilotaż na 20 pierwszych

Formats: .txt (one per line), .jsonl ({"text": ...}), .csv (column `text`/`tresc`).

The API must already be running. This spends real money when the API is not in
offline mode, so it prints an estimate and asks before starting.
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ticket_triage.evaluation.batch import BatchFormatError, parse_tickets  # noqa: E402

# Measured on a 15-ticket run against claude-sonnet-5 on 2026-09-11: auto-answered
# tickets cost about twice the escalated ones, which only pay for classification.
# Only used for the up-front estimate; the run reports what was actually spent.
SZACOWANY_KOSZT_USD = Decimal("0.009")


def request(url: str, payload: dict | None = None, timeout: float = 120.0) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("plik", type=Path, help="Plik ze zgłoszeniami (.txt/.jsonl/.csv).")
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--limit", type=int, default=None, help="Tylko N pierwszych zgłoszeń.")
    parser.add_argument(
        "--dry-run", action="store_true", help="Policz i pokaż koszt, nie wysyłaj niczego."
    )
    parser.add_argument("--yes", action="store_true", help="Nie pytaj o potwierdzenie.")
    args = parser.parse_args()

    try:
        zgloszenia = parse_tickets(args.plik)
    except BatchFormatError as exc:
        print(f"Błąd: {exc}", file=sys.stderr)
        return 2

    if args.limit:
        zgloszenia = zgloszenia[: args.limit]

    # --- Czy API żyje i w jakim trybie ---------------------------------------
    try:
        health = request(f"{args.api_url}/health", timeout=10)
    except (urllib.error.URLError, OSError) as exc:
        print(
            f"Nie można połączyć się z API ({args.api_url}): {exc}\n"
            "Uruchom je najpierw: python scripts/dev.py api",
            file=sys.stderr,
        )
        return 2

    atrapa = bool(health.get("fake_llm"))
    koszt = Decimal("0") if atrapa else SZACOWANY_KOSZT_USD * len(zgloszenia)

    print(f"Plik:       {args.plik} ({len(zgloszenia)} zgłoszeń)")
    print(f"API:        {args.api_url}  ·  model: {health.get('classification_model')}")
    print(f"Tryb:       {'ATRAPA (bez kosztów)' if atrapa else 'PRAWDZIWY MODEL'}")
    print(f"Szacunek:   ${koszt:.2f}" + ("" if atrapa else f" (~{koszt * 4:.2f} zł)"))

    if atrapa:
        print(
            "\nUWAGA: API działa w trybie offline. Wyniki nie powiedzą nic o prawdziwym\n"
            "modelu - posłużą tylko do sprawdzenia, czy pipeline przetworzy te dane."
        )

    if args.dry_run:
        print("\n--dry-run: nic nie wysłano.")
        return 0

    if not args.yes and not atrapa:
        odpowiedz = input(f"\nWysłać {len(zgloszenia)} zgłoszeń za ok. ${koszt:.2f}? [t/N] ")
        if odpowiedz.strip().lower() not in {"t", "tak", "y", "yes"}:
            print("Przerwano.")
            return 1

    # --- Wysyłka --------------------------------------------------------------
    print(f"\n{'#':>5}  {'INTENCJA':20} {'PEWN.':>6}  {'DECYZJA':11} {'KOSZT':>9}  POWODY")
    print("-" * 88)

    wydano, udane, bledy = Decimal("0"), 0, []
    start = time.time()

    for numer, tekst in enumerate(zgloszenia, start=1):
        try:
            r = request(f"{args.api_url}/tickets", {"text": tekst})
        except Exception as exc:  # noqa: BLE001 - jedno złe zgłoszenie nie przerywa partii
            bledy.append((numer, f"{type(exc).__name__}: {exc}"))
            print(f"{numer:>5}  BŁĄD: {type(exc).__name__}")
            continue

        c, d, u = r["classification"], r["decision"], r["usage"]
        wydano += Decimal(str(u["cost_usd"]))
        udane += 1
        powody = ", ".join(d["reasons_pl"]) if d["reasons_pl"] else "—"
        print(
            f"{r['ticket_id']:>5}  {c['intent']:20} {c['confidence']:>5.0%}  "
            f"{d['decision']:11} ${float(u['cost_usd']):>7.4f}  {powody}"
        )

    # --- Podsumowanie ---------------------------------------------------------
    czas = time.time() - start
    print(f"\nPrzetworzono {udane}/{len(zgloszenia)} w {czas:.0f}s")
    print(f"Wydano: ${wydano:.4f} ({wydano * 4:.2f} zł)")
    if udane:
        print(f"Koszt na zgłoszenie: ${wydano / udane:.6f}")
    if bledy:
        print(f"\nBłędy ({len(bledy)}):", file=sys.stderr)
        for numer, powod in bledy[:10]:
            print(f"  zgłoszenie {numer}: {powod}", file=sys.stderr)

    print("\nMetryki zbiorcze: panel (zakładka Metryki) albo GET /metrics")
    return 1 if bledy and not udane else 0


if __name__ == "__main__":
    raise SystemExit(main())
