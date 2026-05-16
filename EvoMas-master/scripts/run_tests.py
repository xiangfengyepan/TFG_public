"""Cross-platform runner for the EvoMas test suites.

Wires up the two test runners we already use ad-hoc into one entry point so
`evomas test` (from `evomas/cli.py`) and direct invocations both work the same:

    python scripts/run_tests.py                            # both halves, no extras
    python scripts/run_tests.py --backend-only             # pytest only
    python scripts/run_tests.py --frontend-only            # ng test only
    python scripts/run_tests.py --integration              # EVOMAS_RUN_INTEGRATION=1
    python scripts/run_tests.py --backend-only -- -k name  # forward -k to pytest
    python scripts/run_tests.py --frontend-only -- --include "src/integration/**"

Extras after `--` are forwarded VERBATIM to the inner runner. Mixing
`--backend-only` and `--frontend-only` with extras when BOTH halves run is
rejected — the extra would go to the wrong runner and confuse the dev loop.

Exit code: `max(backend_rc, frontend_rc)` so CI / `evomas test` propagates failure.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _venv_python() -> Path:
    """Cross-platform venv-python locator. Windows venv puts the executable in
    `Scripts\\`; POSIX uses `bin/`."""
    if os.name == "nt":
        return REPO_ROOT / "evomas" / "venv" / "Scripts" / "python.exe"
    return REPO_ROOT / "evomas" / "venv" / "bin" / "python"


def _banner(title: str) -> None:
    # Plain ASCII so Windows' default cp1252 console doesn't choke on
    # unicode box-drawing chars.
    print(f"\n>>> {title}\n" + "-" * (len(title) + 4), flush=True)


def _run_backend(extra: list[str], integration: bool) -> int:
    """Spawn pytest from the evomas venv. Extras are forwarded verbatim."""
    venv_py = _venv_python()
    if not venv_py.is_file():
        print(
            f"venv python not found at {venv_py}.\n"
            f"  Set it up with: cd evomas && python -m venv venv && "
            f"./venv/{'Scripts' if os.name == 'nt' else 'bin'}/pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1
    cmd = [str(venv_py), "-m", "pytest", "evomas/tests", "-q", *extra]
    env = os.environ.copy()
    if integration:
        env["EVOMAS_RUN_INTEGRATION"] = "1"
    _banner("Backend (pytest)")
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(cmd, cwd=str(REPO_ROOT), env=env).returncode


def _run_frontend(extra: list[str], integration: bool) -> int:
    """Spawn `ng test` from the `app/` directory. On Windows we need
    `shell=True` because `npx` is a `.cmd` shim — without it, Python's
    subprocess can't locate the executable. POSIX runs `npx` directly."""
    app_dir = REPO_ROOT / "app"
    if not app_dir.is_dir():
        print(f"frontend directory not found: {app_dir}", file=sys.stderr)
        return 1
    cmd = ["npx", "ng", "test", "--watch=false", *extra]
    env = os.environ.copy()
    if integration:
        env["EVOMAS_RUN_INTEGRATION"] = "1"
    _banner("Frontend (ng test)")
    print("$", " ".join(cmd), flush=True)
    return subprocess.run(
        cmd,
        cwd=str(app_dir),
        env=env,
        shell=(os.name == "nt"),
    ).returncode


def main() -> int:
    # Manual `--` split first (when invoked directly): any args after `--`
    # are protected even if they collide with our own flag names. When the
    # caller is Typer (`evomas test`), Typer strips `--` before forwarding
    # to us — but `parse_known_args` below handles that case naturally by
    # absorbing unknown flags into `extras` regardless of `--`.
    argv = list(sys.argv[1:])
    explicit_extras: list[str] = []
    if "--" in argv:
        idx = argv.index("--")
        explicit_extras = argv[idx + 1 :]
        argv = argv[:idx]

    parser = argparse.ArgumentParser(
        description="Run the EvoMas backend (pytest) and/or frontend (ng test) suites.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Pass --backend-only or --frontend-only to scope; "
            "any unknown args (or args after `--`) are forwarded verbatim "
            "to the inner runner."
        ),
    )
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--backend-only", action="store_true",
                       help="skip ng test; extra args go to pytest.")
    scope.add_argument("--frontend-only", action="store_true",
                       help="skip pytest; extra args go to ng test.")
    parser.add_argument("--integration", action="store_true",
                        help="set EVOMAS_RUN_INTEGRATION=1 before running.")
    # parse_known_args lets us absorb arbitrary pytest / ng-test flags
    # without enumerating them — anything we don't recognise flows through.
    args, unknown = parser.parse_known_args(argv)
    extras = unknown + explicit_extras

    if extras and not (args.backend_only or args.frontend_only):
        parser.error(
            "extra args are only forwarded when --backend-only or "
            "--frontend-only is set — otherwise pytest flags would leak "
            "into ng test and vice versa. "
            f"unrecognised: {extras}"
        )

    rcs: list[int] = []
    if not args.frontend_only:
        rcs.append(_run_backend(extras if args.backend_only else [], args.integration))
    if not args.backend_only:
        rcs.append(_run_frontend(extras if args.frontend_only else [], args.integration))
    return max(rcs) if rcs else 0


if __name__ == "__main__":
    raise SystemExit(main())
