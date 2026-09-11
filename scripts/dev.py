"""Cross-platform launcher for the API and the operator panel.

Why this exists: the Makefile is convenient on Linux and macOS, but Windows has no
`make`, and `cmd.exe` rejects the POSIX `VAR=value command` form. Anyone reviewing
this repo on Windows would hit that wall in the first minute, so the documented way
to start things is a plain Python script that behaves the same everywhere.

    python scripts/dev.py api             # API with the real model (needs a key)
    python scripts/dev.py api --offline   # API with the stub model (no key, no cost)
    python scripts/dev.py ui              # Streamlit panel (needs the API running)
    python scripts/dev.py seed            # fill the database with sample orders

Two processes, two terminals: the panel talks to the API over HTTP and does not
start it. `docker compose up` runs both at once.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], env: dict[str, str] | None = None) -> int:
    """Run a child process, forwarding Ctrl+C as a normal shutdown rather than a stack trace."""
    print(f"$ {' '.join(command)}\n", flush=True)
    try:
        return subprocess.call(command, cwd=ROOT, env={**os.environ, **(env or {})})
    except KeyboardInterrupt:
        return 0


def api(args: argparse.Namespace) -> int:
    env = {"TRIAGE_FAKE_LLM": "1"} if args.offline else {}
    if args.offline:
        print("Tryb offline: atrapa modelu, bez klucza API i bez kosztów.\n")
    return run(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "ticket_triage.api.main:app",
            "--reload",
            "--app-dir",
            "src",
            "--port",
            str(args.port),
        ],
        env,
    )


def ui(args: argparse.Namespace) -> int:
    return run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "ui/app.py",
            "--server.port",
            str(args.port),
        ],
        {"TRIAGE_API_URL": args.api_url},
    )


def seed(_: argparse.Namespace) -> int:
    return run([sys.executable, "scripts/seed_db.py"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_api = sub.add_parser("api", help="Uruchom API.")
    p_api.add_argument(
        "--offline", action="store_true", help="Atrapa modelu: bez klucza, bez kosztów."
    )
    p_api.add_argument("--port", type=int, default=8000)
    p_api.set_defaults(func=api)

    p_ui = sub.add_parser("ui", help="Uruchom panel operatora.")
    p_ui.add_argument("--port", type=int, default=8501)
    p_ui.add_argument("--api-url", default="http://localhost:8000")
    p_ui.set_defaults(func=ui)

    p_seed = sub.add_parser("seed", help="Wypełnij bazę przykładowymi zamówieniami.")
    p_seed.set_defaults(func=seed)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
