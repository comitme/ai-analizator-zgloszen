"""Cross-platform launcher for the API and the operator panel.

Why this exists: the Makefile is convenient on Linux and macOS, but Windows has no
`make`, and `cmd.exe` rejects the POSIX `VAR=value command` form. Anyone reviewing
this repo on Windows would hit that wall in the first minute, so the documented way
to start things is a plain Python script that behaves the same everywhere.

    python scripts/dev.py api             # API with the real model (needs a key)
    python scripts/dev.py api --offline   # API with the stub model (no key, no cost)
    python scripts/dev.py ui              # Streamlit panel (needs the API running)
    python scripts/dev.py status          # what is running right now
    python scripts/dev.py stop            # stop the API and the panel
    python scripts/dev.py seed            # fill the database with sample orders

Two processes, two terminals: the panel talks to the API over HTTP and does not
start it. Ctrl+C in a terminal stops what runs there; `stop` is for processes whose
terminal is gone. `docker compose up` runs both at once.
"""

import argparse
import contextlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_PORT = 8000
UI_PORT = 8501
IS_WINDOWS = os.name == "nt"


def run(command: list[str], env: dict[str, str] | None = None) -> int:
    """Run a child process, forwarding Ctrl+C as a normal shutdown rather than a stack trace."""
    print(f"$ {' '.join(command)}\n", flush=True)
    try:
        return subprocess.call(command, cwd=ROOT, env={**os.environ, **(env or {})})
    except KeyboardInterrupt:
        return 0


# --- Starting ------------------------------------------------------------------


def api(args: argparse.Namespace) -> int:
    env = {"TRIAGE_FAKE_LLM": "1"} if args.offline else {}
    if args.offline:
        print("Tryb offline: atrapa modelu, bez klucza API i bez kosztów.\n")
    command = [sys.executable, "-m", "uvicorn", "ticket_triage.api.main:app"]
    # --reload is opt-in: it runs the server in a separate worker process, and on
    # Windows that worker can outlive its parent and keep the port. Only worth it
    # while editing the code.
    if args.reload:
        command.append("--reload")
    command += ["--app-dir", "src", "--port", str(args.port)]
    return run(command, env)


def ui(args: argparse.Namespace) -> int:
    return run(
        [sys.executable, "-m", "streamlit", "run", "ui/app.py", "--server.port", str(args.port)],
        {"TRIAGE_API_URL": args.api_url},
    )


def seed(_: argparse.Namespace) -> int:
    return run([sys.executable, "scripts/seed_db.py"])


# --- Deciding what to stop (pure, tested) -------------------------------------

_PARENT_PID = re.compile(r"parent_pid=(\d+)\b")


def _listening_rows(netstat_output: str):
    """Yield ``(port, pid)`` for every TCP socket in the *listening* state.

    Listening rows are recognised by their foreign address (``0.0.0.0:0``) as well as
    by the state column, because that column is localised - Polish Windows prints
    NASŁUCHIWANIE, not LISTENING.
    """
    for line in netstat_output.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        local, foreign, state, pid = parts[1], parts[2], parts[3], parts[-1]
        listening = state.upper() == "LISTENING" or foreign in {"0.0.0.0:0", "[::]:0"}
        port = local.rsplit(":", 1)[-1]
        if listening and port.isdigit() and pid.isdigit():
            yield int(port), int(pid)


def listening_pids(netstat_output: str, port: int) -> set[int]:
    """PIDs with a TCP socket listening on ``port``, from ``netstat -ano`` output."""
    return {pid for p, pid in _listening_rows(netstat_output) if p == port}


def ports_by_pid(netstat_output: str) -> dict[int, set[int]]:
    """Every listening port, grouped by the process that owns it."""
    grouped: dict[int, set[int]] = {}
    for port, pid in _listening_rows(netstat_output):
        grouped.setdefault(pid, set()).add(port)
    return grouped


def is_ours(cmdline: str) -> bool:
    """Only this project's servers get killed. Port 8000 is a popular default."""
    return "uvicorn" in cmdline or "streamlit" in cmdline


def is_project(cmdline: str) -> bool:
    """This project's API or panel, on whatever port it ended up on.

    Stricter than :func:`is_ours`: status lists these off the default ports, so a
    Streamlit dashboard from some other project must not be claimed as our panel.
    """
    normalised = cmdline.replace("\\", "/")
    return "ui/app.py" in normalised or "ticket_triage.api.main" in normalised


def orphaned_workers(processes: dict[int, str], parent_pids: set[int]) -> set[int]:
    """Worker processes spawned by any of ``parent_pids``.

    uvicorn --reload serves from a multiprocessing worker whose command line carries
    ``parent_pid=<reloader>``. On Windows the socket is attributed to the reloader,
    so once the reloader dies this is the only way to find what still holds the port.
    """
    found = set()
    for pid, cmdline in processes.items():
        match = _PARENT_PID.search(cmdline)
        if match and int(match.group(1)) in parent_pids:
            found.add(pid)
    return found


def plan_stop(port_pids: set[int], processes: dict[int, str]) -> tuple[set[int], set[int]]:
    """Return ``(kill, refused)`` for the processes holding a port."""
    kill, refused = set(), set()
    for pid in port_pids:
        cmdline = processes.get(pid)
        if cmdline is None:
            continue  # already gone - but its worker may still hold the port, below
        (kill if is_ours(cmdline) else refused).add(pid)
    kill |= orphaned_workers(processes, port_pids - refused)
    return kill, refused


# --- Talking to the OS -------------------------------------------------------------


def _all_listening() -> dict[int, set[int]]:
    """Listening ports grouped by PID, from the OS."""
    if IS_WINDOWS:
        output = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, errors="replace"
        ).stdout
        return ports_by_pid(output)
    output = subprocess.run(
        ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN"], capture_output=True, text=True
    ).stdout
    grouped: dict[int, set[int]] = {}
    for line in output.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 9 and parts[1].isdigit():
            port = parts[-2].rsplit(":", 1)[-1]
            if port.isdigit():
                grouped.setdefault(int(parts[1]), set()).add(int(port))
    return grouped


def _port_pids(port: int) -> set[int]:
    return {pid for pid, ports in _all_listening().items() if port in ports}


def _processes() -> dict[int, str]:
    if IS_WINDOWS:
        output = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process | Select-Object ProcessId,CommandLine "
                "| ConvertTo-Json -Compress",
            ],
            capture_output=True,
            text=True,
            errors="replace",
        ).stdout
        rows = json.loads(output or "[]")
        rows = rows if isinstance(rows, list) else [rows]
        return {int(r["ProcessId"]): r.get("CommandLine") or "" for r in rows}
    output = subprocess.run(["ps", "-eo", "pid=,args="], capture_output=True, text=True).stdout
    processes = {}
    for line in output.splitlines():
        pid, _, cmdline = line.strip().partition(" ")
        if pid.isdigit():
            processes[int(pid)] = cmdline
    return processes


def _kill(pid: int) -> None:
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
    else:
        with contextlib.suppress(ProcessLookupError):  # already exited
            os.kill(pid, signal.SIGTERM)


def _short(cmdline: str, width: int = 70) -> str:
    """The part of a command line worth reading: drop the interpreter path, keep the rest."""
    tokens = [t.strip('"') for t in cmdline.split()]
    if tokens and re.search(r"python[\d.]*(\.exe)?$", tokens[0], re.IGNORECASE):
        tokens = tokens[1:]
    # A full path to streamlit.exe says nothing a reader needs; the file name does.
    tokens = [
        Path(t).name if ("\\" in t or t.count("/") > 1) and "." in Path(t).name else t
        for t in tokens
    ]
    text = " ".join(tokens)
    return text if len(text) <= width else text[: width - 1] + "…"


# --- Commands ------------------------------------------------------------------------


def _ports(args: argparse.Namespace) -> list[int]:
    return args.ports or [API_PORT, UI_PORT]


def _other_instances(
    listening: dict[int, set[int]], processes: dict[int, str], exclude: set[int]
) -> list[tuple[int, int]]:
    """``(port, pid)`` of this project's servers listening outside ``exclude``."""
    return sorted(
        (port, pid)
        for pid, ports in listening.items()
        if is_project(processes.get(pid, ""))
        for port in ports
        if port not in exclude
    )


def _print_other_instances(others: list[tuple[int, int]], processes: dict[int, str]) -> None:
    if not others:
        return
    print()
    print("Inne instancje tego projektu (Streamlit przeskakuje na wolny port, gdy 8501 zajęty):")
    for port, pid in others:
        print(f"      :{port}  PID {pid}: {_short(processes[pid])}")
    flags = " ".join(f"--port {port}" for port in sorted({port for port, _ in others}))
    print(f"  zatrzymasz je: python scripts/dev.py stop {flags}")


def status(args: argparse.Namespace) -> int:
    processes = _processes()
    listening = _all_listening()
    for port in _ports(args):
        pids = {pid for pid, ports in listening.items() if port in ports}
        name = {API_PORT: "API", UI_PORT: "panel"}.get(port, "port")
        if not pids:
            print(f"{name:5} :{port}  zatrzymane")
            continue
        for pid in sorted(pids):
            cmdline = processes.get(pid)
            if cmdline is None:
                holders = orphaned_workers(processes, {pid})
                note = f"osierocony proces roboczy {sorted(holders)}" if holders else "?"
                print(f"{name:5} :{port}  DZIAŁA  ({note})")
            else:
                owner = "" if is_ours(cmdline) else "  ← NIE nasz proces"
                print(f"{name:5} :{port}  DZIAŁA  PID {pid}: {_short(cmdline)}{owner}")

    if args.ports is None:  # default view: also surface instances that drifted to other ports
        _print_other_instances(_other_instances(listening, processes, set(_ports(args))), processes)
    return 0


def stop(args: argparse.Namespace) -> int:
    failed = False
    for port in _ports(args):
        pids = _port_pids(port)
        if not pids:
            print(f":{port}  nic nie działa")
            continue

        processes = _processes()
        kill, refused = plan_stop(pids, processes)
        for pid in sorted(refused):
            print(f":{port}  pomijam PID {pid} - to nie nasz proces: {_short(processes[pid])}")
            failed = True
        if not kill:
            continue

        for pid in sorted(kill):
            _kill(pid)

        deadline = time.monotonic() + 8
        while _port_pids(port) and time.monotonic() < deadline:
            time.sleep(0.5)

        if _port_pids(port):
            print(f":{port}  NADAL zajęty po zatrzymaniu PID {sorted(kill)}")
            failed = True
        else:
            print(f":{port}  zatrzymano (PID {', '.join(map(str, sorted(kill)))})")

    if args.ports is None:
        # Not stopped automatically: a panel on another port may be one someone is
        # using right now. Naming the exact command is enough.
        processes = _processes()
        others = _other_instances(_all_listening(), processes, set(_ports(args)))
        _print_other_instances(others, processes)
    return 1 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_api = sub.add_parser("api", help="Uruchom API.")
    p_api.add_argument(
        "--offline", action="store_true", help="Atrapa modelu: bez klucza, bez kosztów."
    )
    p_api.add_argument(
        "--reload", action="store_true", help="Przeładowuj po zmianie kodu (do programowania)."
    )
    p_api.add_argument("--port", type=int, default=API_PORT)
    p_api.set_defaults(func=api)

    p_ui = sub.add_parser("ui", help="Uruchom panel operatora.")
    p_ui.add_argument("--port", type=int, default=UI_PORT)
    p_ui.add_argument("--api-url", default=f"http://localhost:{API_PORT}")
    p_ui.set_defaults(func=ui)

    for name, func, help_text in (
        ("status", status, "Pokaż, co działa na portach API i panelu."),
        ("stop", stop, "Zatrzymaj API i panel (także procesy bez okna terminala)."),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument(
            "--port",
            type=int,
            action="append",
            dest="ports",
            help=f"Konkretny port (można powtórzyć). Domyślnie {API_PORT} i {UI_PORT}.",
        )
        p.set_defaults(func=func)

    p_seed = sub.add_parser("seed", help="Wypełnij bazę przykładowymi zamówieniami.")
    p_seed.set_defaults(func=seed)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
