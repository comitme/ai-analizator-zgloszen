"""Print the pip requirements for one Docker image, read from pyproject.toml.

    python scripts/print_requirements.py api   # runtime dependencies of the API
    python scripts/print_requirements.py ui    # the panel's own dependencies

The Dockerfile pipes this into `pip install -r`, so package versions live in
pyproject.toml only. Installing the dependencies rather than the package itself also
keeps the source where config.py expects it (config/ sits next to src/), and lets
Docker cache the dependency layer separately from code changes.
"""

import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def requirements(pyproject: Path, image: str) -> list[str]:
    project = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]
    if image == "api":
        return list(project["dependencies"])
    if image == "ui":
        # Deliberately not the base dependencies: the panel talks to the API over HTTP
        # and must not need FastAPI, SQLAlchemy or the Anthropic SDK to run.
        return list(project["optional-dependencies"]["ui"])
    raise SystemExit(f"Nieznany obraz: {image!r} (dostępne: api, ui)")


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("Użycie: python scripts/print_requirements.py api|ui")
    print("\n".join(requirements(ROOT / "pyproject.toml", sys.argv[1])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
