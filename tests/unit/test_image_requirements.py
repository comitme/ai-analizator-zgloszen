"""Which packages each Docker image installs.

Both images read their dependencies from pyproject.toml, so versions live in one
place. These tests pin the architectural claim the two images make: the panel is a
separate service that only speaks HTTP, so its image must not carry the API's
stack - and must carry everything its HTTP client needs.
"""

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def reqs():
    spec = importlib.util.spec_from_file_location(
        "print_requirements", ROOT / "scripts" / "print_requirements.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _names(requirements: list[str]) -> set[str]:
    return {re.split(r"[\[<>=!~ ]", r, maxsplit=1)[0].lower() for r in requirements}


class TestApiImage:
    def test_installs_the_runtime_dependencies(self, reqs):
        names = _names(reqs.requirements(ROOT / "pyproject.toml", "api"))

        assert {"fastapi", "anthropic", "sqlalchemy", "uvicorn"} <= names

    def test_does_not_install_test_tooling(self, reqs):
        names = _names(reqs.requirements(ROOT / "pyproject.toml", "api"))

        assert names.isdisjoint({"pytest", "ruff", "streamlit"})


class TestUiImage:
    def test_installs_what_the_panel_imports(self, reqs):
        """ui/api_client.py imports httpx. Locally it arrives with the API's packages,
        which hides its absence from the ui extra until the panel runs alone."""
        names = _names(reqs.requirements(ROOT / "pyproject.toml", "ui"))

        assert {"streamlit", "pandas", "httpx"} <= names

    def test_carries_none_of_the_api_stack(self, reqs):
        """If this fails, the 'two separate services' claim in the README is false."""
        names = _names(reqs.requirements(ROOT / "pyproject.toml", "ui"))

        assert names.isdisjoint({"fastapi", "anthropic", "sqlalchemy", "uvicorn"})


def test_unknown_image_is_rejected(reqs):
    with pytest.raises(SystemExit):
        reqs.requirements(ROOT / "pyproject.toml", "frontend")
