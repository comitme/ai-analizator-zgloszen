"""The launcher's `stop` command: deciding which processes to kill.

Killing the wrong process is worse than killing none, so the decision is separated
from the OS calls and tested on captured output. Two traps drove this:

* uvicorn --reload runs the server in a multiprocessing worker. On Windows the
  listening socket is attributed to the reloader, so when the reloader dies the
  worker keeps the port while netstat points at a PID that no longer exists.
* port 8000 is a popular default; whatever listens there might not be ours.
"""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def dev():
    spec = importlib.util.spec_from_file_location("dev", ROOT / "scripts" / "dev.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


NETSTAT = """
Active Connections

  Proto  Local Address          Foreign Address        State           PID
  TCP    0.0.0.0:8000           0.0.0.0:0              LISTENING       24456
  TCP    [::]:8000              [::]:0                 LISTENING       24456
  TCP    0.0.0.0:80000          0.0.0.0:0              LISTENING       11111
  TCP    127.0.0.1:8501         0.0.0.0:0              LISTENING       43916
  TCP    127.0.0.1:52011        127.0.0.1:8000         ESTABLISHED     43916
  UDP    0.0.0.0:8000           *:*                                    22222
"""


class TestListeningPids:
    def test_finds_the_process_listening_on_the_port(self, dev):
        assert dev.listening_pids(NETSTAT, 8000) == {24456}

    def test_does_not_match_a_longer_port_number(self, dev):
        """:80000 must not count as :8000."""
        assert 11111 not in dev.listening_pids(NETSTAT, 8000)

    def test_ignores_clients_connected_to_the_port(self, dev):
        """The panel connecting *to* 8000 must not be killed as if it were the API."""
        assert 43916 not in dev.listening_pids(NETSTAT, 8000)

    def test_ignores_udp(self, dev):
        assert 22222 not in dev.listening_pids(NETSTAT, 8000)

    def test_nothing_listening_is_an_empty_set(self, dev):
        assert dev.listening_pids(NETSTAT, 9999) == set()

    def test_polish_windows_is_understood(self, dev):
        """netstat localises the state column; matching only 'LISTENING' would find
        nothing on a Polish system and report a running API as stopped."""
        polish = "  TCP    0.0.0.0:8000           0.0.0.0:0              NASŁUCHIWANIE   24456\n"

        assert dev.listening_pids(polish, 8000) == {24456}


class TestWhatIsOurs:
    @pytest.mark.parametrize(
        "cmdline",
        [
            "python.exe -m uvicorn ticket_triage.api.main:app --app-dir src --port 8000",
            "python.exe -m streamlit run ui/app.py --server.port 8501",
        ],
    )
    def test_our_servers_are_recognised(self, dev, cmdline):
        assert dev.is_ours(cmdline)

    def test_an_unrelated_program_on_the_same_port_is_left_alone(self, dev):
        assert not dev.is_ours("node.exe server.js --port 8000")


class TestOrphanedWorkers:
    def _processes(self):
        return {
            44720: '"python.exe" "-c" "from multiprocessing.spawn import spawn_main; '
            'spawn_main(parent_pid=24456, pipe_handle=680)" --multiprocessing-fork',
            55555: '"python.exe" "-c" "from multiprocessing.spawn import spawn_main; '
            'spawn_main(parent_pid=244, pipe_handle=12)" --multiprocessing-fork',
            66666: "python.exe some_other_script.py",
        }

    def test_worker_of_a_listening_reloader_is_found(self, dev):
        assert dev.orphaned_workers(self._processes(), {24456}) == {44720}

    def test_parent_pid_match_is_exact_not_a_prefix(self, dev):
        """parent_pid=244 must not be taken for a child of 24456."""
        assert 55555 not in dev.orphaned_workers(self._processes(), {24456})


class TestKillPlan:
    def test_kills_our_server_and_its_worker(self, dev):
        processes = {
            24456: "python.exe -m uvicorn ticket_triage.api.main:app --reload",
            44720: "python.exe -c spawn_main(parent_pid=24456, pipe_handle=1)",
        }

        kill, refused = dev.plan_stop({24456}, processes)

        assert kill == {24456, 44720}
        assert refused == set()

    def test_dead_reloader_still_releases_its_worker(self, dev):
        """netstat names a PID that no longer exists; the worker holding the port must go."""
        processes = {44720: "python.exe -c spawn_main(parent_pid=24456, pipe_handle=1)"}

        kill, refused = dev.plan_stop({24456}, processes)

        assert kill == {44720}

    def test_refuses_a_foreign_process_and_its_workers(self, dev):
        processes = {
            31337: "node.exe server.js --port 8000",
            31338: "python.exe -c spawn_main(parent_pid=31337, pipe_handle=1)",
        }

        kill, refused = dev.plan_stop({31337}, processes)

        assert kill == set()
        assert refused == {31337}


class TestInstancesOnOtherPorts:
    """Streamlit silently moves to the next free port when its default is taken.

    A second panel on 8502, talking to an API someone else left running, is exactly
    the situation that makes "why is my API already detected?" confusing - so status
    has to see instances off the default ports, not just the defaults.
    """

    def test_ports_are_grouped_by_process(self, dev):
        netstat = (
            "  TCP    0.0.0.0:8502    0.0.0.0:0    LISTENING    54992\n"
            "  TCP    [::]:8502       [::]:0       LISTENING    54992\n"
            "  TCP    0.0.0.0:9000    0.0.0.0:0    LISTENING    54992\n"
            "  TCP    127.0.0.1:5000  127.0.0.1:8502  ESTABLISHED  777\n"
        )

        assert dev.ports_by_pid(netstat) == {54992: {8502, 9000}}

    @pytest.mark.parametrize(
        "cmdline",
        [
            '"python.exe" "streamlit.exe" run ui/app.py',
            r"python.exe -m streamlit run ui\app.py --server.port 8502",
            "python.exe -m uvicorn ticket_triage.api.main:app --port 8010",
        ],
    )
    def test_this_projects_servers_are_recognised_on_any_port(self, dev, cmdline):
        assert dev.is_project(cmdline)

    def test_a_streamlit_app_from_another_project_is_not_ours(self, dev):
        """Status must not claim someone else's dashboard as this project's panel."""
        assert not dev.is_project("python.exe -m streamlit run dashboard.py")
