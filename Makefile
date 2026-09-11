.PHONY: help install seed run run-offline ui test test-all lint fmt clean eval-check eval-pilot eval sweep

# Wygodne skróty dla Linuksa i macOS. Na Windowsie nie ma `make` ani składni
# VAR=wartość polecenie - tam działa: python scripts/dev.py api|ui|seed
help:
	@echo "install   - zainstaluj zależności (edytowalnie, z dev i ui)"
	@echo "seed      - wypełnij bazę syntetycznymi zamówieniami"
	@echo "run       - uruchom API na http://localhost:8000 (dokumentacja: /docs)"
	@echo "run-offline - API bez klucza i bez kosztów (atrapa modelu)"
	@echo "ui        - panel operatora na http://localhost:8501 (API musi już działać)"
	@echo "test      - testy bez wywołań API (nic nie kosztuje)"
	@echo "test-all  - wszystkie testy, w tym te wołające prawdziwy model (KOSZTUJE)"
	@echo "eval-check - sprawdzenie pipeline'u ewaluacji bez API (oracle + offline, 0 zł)"
	@echo "eval-pilot - 5 zgłoszeń na prawdziwym modelu: zmierz koszt przed pełnym przebiegiem"
	@echo "eval      - pełna ewaluacja Sonnet 5 vs Haiku 4.5 (KOSZTUJE, ~kilkadziesiąt groszy)"
	@echo "sweep     - próg pewności vs błędy automatyzacji z zapisanych predykcji (0 zł)"
	@echo "lint      - ruff check"
	@echo "fmt       - ruff format + autofix"
	@echo "clean     - usuń cache i lokalną bazę"
	@echo ""
	@echo "Windows (bez make): python scripts/dev.py api --offline | ui | seed"

install:
	pip install -e ".[dev,ui]"

seed:
	python scripts/seed_db.py

run:
	uvicorn ticket_triage.api.main:app --reload --app-dir src --port 8000

# Atrapa modelu zamiast prawdziwych wywołań: pełny przepływ bez klucza i bez kosztów.
run-offline:
	TRIAGE_FAKE_LLM=1 uvicorn ticket_triage.api.main:app --reload --app-dir src --port 8000

# Wymaga działającego API. Adres można nadpisać: TRIAGE_API_URL=http://host:port make ui
ui:
	streamlit run ui/app.py

# Domyślny przebieg NIE woła API i nie wymaga klucza — dzięki temu faktycznie
# uruchamiasz testy zamiast ich unikać.
test:
	pytest -m "not llm" -q

test-all:
	pytest -q

# Harness check: oracle must score 100%, offline stub proves the wiring. No API key.
eval-check:
	python eval/run_eval.py --mode oracle --refresh
	python eval/threshold_sweep.py --mode oracle
	python eval/run_eval.py --mode offline --refresh
	python eval/threshold_sweep.py --mode offline

eval-pilot:
	python eval/run_eval.py --models claude-sonnet-5 claude-haiku-4-5 --limit 5

eval:
	python eval/run_eval.py --models claude-sonnet-5 claude-haiku-4-5

sweep:
	python eval/threshold_sweep.py --model claude-sonnet-5
	python eval/threshold_sweep.py --model claude-haiku-4-5

lint:
	ruff check src tests scripts

fmt:
	ruff format src tests scripts
	ruff check --fix src tests scripts

clean:
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov
	find . -type d -name __pycache__ -exec rm -rf {} +
	rm -f data/*.db
