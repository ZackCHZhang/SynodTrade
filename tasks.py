"""Cross-platform task runner (Windows has no `make`; the Makefile delegates here).

Usage:
    python tasks.py install          # poetry install + pre-commit hooks
    python tasks.py lint             # ruff check, ruff format --check, import-linter
    python tasks.py format           # ruff format + autofix
    python tasks.py typecheck        # mypy --strict on sources and tests
    python tasks.py test             # all unit tests
    python tasks.py test-<pkg>       # unit tests of one package, e.g. test-core
    python tasks.py cov              # all unit tests with coverage report
    python tasks.py integration      # tests marked @pytest.mark.integration (real services)
    python tasks.py check            # lint + typecheck + test
    python tasks.py web              # install and build the web console (web/ -> web/dist)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PACKAGES = sorted(p.name for p in (ROOT / "packages").iterdir() if (p / "pyproject.toml").exists())


def run(*args: str) -> None:
    cmd = ["poetry", "run", *args] if args[0] != "poetry" else list(args)
    print("$", " ".join(cmd), flush=True)
    result = subprocess.run(cmd, cwd=ROOT, check=False)
    if result.returncode != 0:
        sys.exit(result.returncode)


def install() -> None:
    run("poetry", "install")
    if (ROOT / ".git").exists():
        run("pre-commit", "install")


def lint() -> None:
    run("ruff", "check", ".")
    run("ruff", "format", "--check", ".")
    run("lint-imports")


def fmt() -> None:
    run("ruff", "check", "--fix", ".")
    run("ruff", "format", ".")


def typecheck() -> None:
    run("mypy", *(arg for pkg in PACKAGES for arg in ("-p", f"synodtrade_{pkg}")))
    # Each package's tests/ has its own conftest.py, so they are checked one package at a time.
    for pkg in PACKAGES:
        run("mypy", f"packages/{pkg}/tests")


def test() -> None:
    run("pytest")


def cov() -> None:
    run("pytest", "--cov", "--cov-report=term-missing")


def integration() -> None:
    run("pytest", "-m", "integration")


def web() -> None:
    npm = shutil.which("npm")
    if npm is None:
        sys.exit("npm not found: install Node.js (>= 20) to build the web console")
    for args in (["install"], ["run", "build"]):
        print("$ npm", " ".join(args), flush=True)
        if subprocess.run([npm, *args], cwd=ROOT / "web", check=False).returncode != 0:
            sys.exit(1)


def check() -> None:
    lint()
    typecheck()
    test()


TASKS: dict[str, Callable[[], None]] = {
    "install": install,
    "lint": lint,
    "format": fmt,
    "typecheck": typecheck,
    "test": test,
    "cov": cov,
    "integration": integration,
    "check": check,
    "web": web,
}


def main(argv: list[str]) -> None:
    if len(argv) != 1:
        print(__doc__)
        sys.exit(2)
    name = argv[0]
    if name.startswith("test-") and name[5:] in PACKAGES:
        pkg = name[5:]
        run(
            "pytest",
            f"packages/{pkg}/tests",
            f"--cov=synodtrade_{pkg}",
            "--cov-report=term-missing",
        )
        return
    task = TASKS.get(name)
    if task is None:
        print(f"unknown task {name!r}; packages: {', '.join(PACKAGES)}\n{__doc__}")
        sys.exit(2)
    task()


if __name__ == "__main__":
    main(sys.argv[1:])
