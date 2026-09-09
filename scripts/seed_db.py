"""Seed the database with synthetic orders.

Dates are relative to *today* so the fixtures stay meaningful whenever you run this -
an order seeded as "20 days ago" is always outside the 14-day window, no matter when
you clone the repo.

Usage:  python scripts/seed_db.py [--reset]
"""

import argparse
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv  # noqa: E402

from ticket_triage.config import get_app_config  # noqa: E402
from ticket_triage.db.schema import OrderRow  # noqa: E402
from ticket_triage.db.session import init_engine, session_scope  # noqa: E402

# (ref, days_ago, category, amount, what this case is for)
SEED_ORDERS: list[tuple[str, int, str, str, str]] = [
    ("10432", 3, "obuwie", "249.00", "typowy zwrot w terminie"),
    ("10433", 20, "obuwie", "199.00", "po terminie 14 dni"),
    ("10434", 2, "bielizna", "89.00", "kategoria wyłączona ze zwrotu"),
    ("10435", 5, "kosmetyki", "159.00", "kategoria wyłączona, ale reklamacja możliwa"),
    ("10436", 1, "elektronika", "3499.00", "wysoka wartość -> twarda eskalacja"),
    ("10437", 400, "elektronika", "899.00", "w rękojmi, po terminie zwrotu"),
    ("10438", 800, "agd", "1299.00", "po rękojmi (ponad 24 mies.)"),
    ("10439", 14, "odziez", "129.00", "dokładnie ostatni dzień terminu"),
    ("10440", 15, "odziez", "139.00", "dzień po terminie"),
    ("10441", 7, "produkty-spersonalizowane", "249.00", "personalizacja - bez zwrotu"),
    ("10442", 30, "ksiazki", "59.00", "po terminie, niska wartość"),
    ("10443", 0, "zabawki", "79.00", "zakup dzisiaj"),
]


def seed(*, reset: bool) -> None:
    load_dotenv()
    config = get_app_config()
    init_engine(config.database_url)
    today = date.today()

    with session_scope() as session:
        if reset:
            deleted = session.query(OrderRow).delete()
            print(f"Usunięto {deleted} istniejących zamówień.")

        added = skipped = 0
        for ref, days_ago, category, amount, note in SEED_ORDERS:
            if session.get(OrderRow, ref) is not None:
                skipped += 1
                continue
            session.add(
                OrderRow(
                    order_ref=ref,
                    purchase_date=today - timedelta(days=days_ago),
                    category=category,
                    amount_pln=Decimal(amount),
                    customer_email=f"klient{ref}@example.com",
                )
            )
            added += 1
            print(f"  + {ref:<7} {category:<26} {amount:>8} PLN   {days_ago:>3}d temu  ({note})")

    print(f"\nBaza: {config.database_url}")
    print(f"Dodano {added}, pominięto {skipped} (już istniały).")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="Usuń istniejące zamówienia najpierw.")
    seed(reset=parser.parse_args().reset)
