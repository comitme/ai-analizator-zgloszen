# Two images from one file: `api` and `ui`. They share a base layer and nothing else -
# the panel talks to the API over HTTP, so its image carries none of the API's packages
# (tests/unit/test_image_requirements.py holds that line).
#
#   docker build --target api -t ticket-triage-api .
#   docker build --target ui  -t ticket-triage-ui  .
#
# Normally built and run through docker-compose.yml.

FROM python:3.11-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Nothing here needs root at runtime.
RUN useradd --create-home --uid 10001 app

# Dependency lists are read from pyproject.toml, so versions live in one place. Copied
# before the source, so the slow install layer is rebuilt only when dependencies change.
COPY pyproject.toml ./
COPY scripts/print_requirements.py scripts/


# --- API ---------------------------------------------------------------------------
FROM base AS api

RUN python scripts/print_requirements.py api > /tmp/requirements.txt \
 && pip install -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt

# Run from source rather than pip-installed: config.py finds config/ relative to src/,
# so this layout has to mirror the repository.
COPY src/ src/
COPY config/ config/
COPY scripts/seed_db.py scripts/

# SQLite lives in a volume at /app/data. The directory must exist and belong to `app`
# before a volume is mounted over it, or Docker creates it owned by root.
RUN mkdir -p data && chown -R app:app /app
USER app

ENV DATABASE_URL=sqlite:////app/data/triage.db

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=2)"]

# Exec form: uvicorn runs as PID 1 and receives SIGTERM on `docker stop`.
CMD ["uvicorn", "ticket_triage.api.main:app", "--app-dir", "src", "--host", "0.0.0.0", "--port", "8000"]


# --- UI ----------------------------------------------------------------------------
FROM base AS ui

RUN python scripts/print_requirements.py ui > /tmp/requirements.txt \
 && pip install -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt

COPY ui/ ui/

RUN chown -R app:app /app
USER app

EXPOSE 8501

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=2)"]

CMD ["streamlit", "run", "ui/app.py", \
     "--server.address", "0.0.0.0", "--server.port", "8501", \
     "--server.headless", "true", "--browser.gatherUsageStats", "false"]
