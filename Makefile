.PHONY: help install seed run test test-all lint fmt clean

help:
	@echo "install   - zainstaluj zależności (edytowalnie, z dev i ui)"
	@echo "seed      - wypełnij bazę syntetycznymi zamówieniami"
	@echo "run       - uruchom API na http://localhost:8000 (dokumentacja: /docs)"
	@echo "test      - testy bez wywołań API (nic nie kosztuje)"
	@echo "test-all  - wszystkie testy, w tym te wołające prawdziwy model (KOSZTUJE)"
	@echo "lint      - ruff check"
	@echo "fmt       - ruff format + autofix"
	@echo "clean     - usuń cache i lokalną bazę"

install:
	pip install -e ".[dev,ui]"

seed:
	python scripts/seed_db.py

run:
	uvicorn ticket_triage.api.main:app --reload --app-dir src --port 8000

# Domyślny przebieg NIE woła API i nie wymaga klucza — dzięki temu faktycznie
# uruchamiasz testy zamiast ich unikać.
test:
	pytest -m "not llm" -q

test-all:
	pytest -q

lint:
	ruff check src tests scripts

fmt:
	ruff format src tests scripts
	ruff check --fix src tests scripts

clean:
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} +
	rm -f data/*.db
