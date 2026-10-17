#!/usr/bin/env python3
"""Resilient environment setup for FreelanceDZ (issue #24).

Why this exists
---------------
The blueprint's clean-machine transcript (docs/refactor/error.log.md)
records two distinct install-time failure modes that ``pip install -r …``
on its own handles badly:

1. **Transient network failure** — a ``ReadTimeoutError`` while fetching
   the ~10.4 MB Streamlit wheel aborts the install midway, leaving the
   environment without Streamlit/Folium/Pandas. Follow-up startup
   commands then fail with raw tracebacks.
2. **Dependency conflict (issue #3)** — pip exits **0** after printing
   ``ERROR: pip's dependency resolver … which is incompatible`` when a
   later manifest upgrades Starlette past the installed FastAPI's range.
   "Successfully installed" then misleads the user straight into the
   historical ``Router.__init__()`` crash.

This script makes both failures explicit and distinguishable:

* bounded, configurable pip timeout/retries (never unlimited, output
  never hidden — every pip line is streamed live);
* pip's conflict banner is scanned even on exit code 0 and reported as a
  distinct failure pointing at the issue-#3 remediation;
* a post-install verification imports the engine *and* UI stacks in a
  fresh subprocess, names exactly which component is missing when it
  fails, and runs ``pip check`` for whole-environment consistency.

Retry behaviour: a failed download is retried by **re-running the same
command**. pip's HTTP cache keeps already-downloaded wheels, and nothing
in this script deletes the venv, ``.env`` or the database.

Exit codes
----------
0  success (install or check-only verified)
1  pip install failed (transient network error → retry the command)
2  dependency conflict detected (issue #3 → see remediation printed)
3  ``pip check`` reported a broken environment
4  post-install import verification failed (names the component)

Stdlib only — must run before any third-party package is installed.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent

EXIT_OK = 0
EXIT_PIP_FAILED = 1
EXIT_DEPENDENCY_CONFLICT = 2
EXIT_PIP_CHECK_FAILED = 3
EXIT_IMPORT_FAILED = 4

DEFAULT_TIMEOUT = 120  # seconds per connection; the transcript used --default-timeout=120
DEFAULT_RETRIES = 3  # bounded network retries per package (never unlimited)

ALL_MANIFESTS = ("requirements.txt", "requirements-ui.txt", "requirements-dev.txt")
UI_MANIFESTS = ("requirements-ui.txt",)

# What "installed and importable" means for each stack. The engine import
# also runs core.dependency_guard at import time (issue #3 belt & braces).
UI_IMPORT_MODULES = ("streamlit", "streamlit_folium", "folium", "pandas")
ENGINE_IMPORT_STATEMENT = "from api.server import app; print('engine ok')"

# The conflict banner pip prints while still exiting 0 (error.log.md lines
# 101-103). Both fragments are needed: the first line alone also appears in
# benign ``pip check`` prose.
CONFLICT_MARKER = "pip's dependency resolver does not currently take into account"
CONFLICT_MARKER_2 = "which is incompatible"

RETRY_HINT = (
    "A transient network failure (download timeout) is the usual cause.\n"
    "Re-run the SAME command — pip's cache keeps completed downloads and\n"
    "nothing here deleted your venv, .env or data/ directory."
)

CONFLICT_HINT = (
    "This is the dependency-conflict failure mode (issue #3), NOT a network\n"
    "problem: pip resolved the manifests into an incompatible framework set.\n"
    "Remediation options (docs/08-local-development.md):\n"
    "  1. Recreate the shared venv with the documented ONE-SHOT joint install\n"
    "     (this script's default mode does exactly that when run in a fresh venv).\n"
    "  2. Or keep engine and UI in separate virtual environments (strict isolation)."
)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def effective_timeout(cli_value: Optional[int]) -> int:
    """Resolve the pip connection timeout: --timeout > $PIP_DEFAULT_TIMEOUT > default."""
    if cli_value is not None:
        return cli_value
    env = os.environ.get("PIP_DEFAULT_TIMEOUT", "").strip()
    if env:
        try:
            return int(env)
        except ValueError:
            print(f"setup_env: ignoring non-numeric PIP_DEFAULT_TIMEOUT={env!r}",
                  file=sys.stderr)
    return DEFAULT_TIMEOUT


def inside_virtualenv() -> bool:
    """True when running inside a venv/virtualenv (never install to system Python accidentally)."""
    if sys.prefix != sys.base_prefix:
        return True
    return bool(os.environ.get("VIRTUAL_ENV"))


# ---------------------------------------------------------------------------
# pip plumbing (all output streamed — never hidden)
# ---------------------------------------------------------------------------
def pip_install_command(manifests: list[str], timeout: int, retries: int) -> list[str]:
    """Build the pip install command with explicit bounded timeout/retries."""
    cmd = [
        sys.executable, "-m", "pip", "install",
        "--progress-bar", "off",  # line-oriented output that streams through pipes
        "--default-timeout", str(timeout),
        "--retries", str(retries),  # bounded: never retry forever
    ]
    for manifest in manifests:
        cmd += ["-r", str(REPO_ROOT / manifest)]
    return cmd


def stream_process(cmd: list[str]) -> tuple[int, str]:
    """Run ``cmd`` streaming every output line live; return (exit code, full text).

    Output is never suppressed or buffered behind the process: the user sees
    exactly what pip printed, as it prints it, and we keep a copy to scan for
    the conflict banner afterwards.
    """
    lines: list[str] = []
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        sys.stdout.write(line)
        sys.stdout.flush()
        lines.append(line)
    returncode = proc.wait()
    return returncode, "".join(lines)


def detect_conflict(pip_output: str) -> bool:
    """True when pip printed its resolver-conflict banner (which exits 0!)."""
    return CONFLICT_MARKER in pip_output and CONFLICT_MARKER_2 in pip_output


def pip_check() -> int:
    """Run ``python -m pip check``; its own output goes straight through."""
    return subprocess.call([sys.executable, "-m", "pip", "check"])


def verify_imports() -> tuple[bool, list[str], bool]:
    """Import-verify both stacks in FRESH subprocesses (no shared state).

    Returns ``(ui_ok, missing_ui_modules, engine_ok)``. ``missing`` names
    exactly which UI component is absent (via find_spec — no UI package is
    imported) so the failure message is actionable; ``engine_ok``
    distinguishes an engine-side import failure (historically the issue-#3
    Starlette crash — ``api.server`` import also runs the runtime guard).
    """
    ui_ok = subprocess.run(
        [sys.executable, "-c", "import " + ", ".join(UI_IMPORT_MODULES)],
        capture_output=True,
    ).returncode == 0
    probe = subprocess.run(
        [sys.executable, "-c",
         "import importlib.util as u\n"
         "print(','.join(m for m in " + repr(list(UI_IMPORT_MODULES)) +
         " if u.find_spec(m) is None))"],
        capture_output=True, text=True,
    )
    missing = [m for m in probe.stdout.strip().split(",") if m]
    engine_ok = subprocess.run(
        [sys.executable, "-c", ENGINE_IMPORT_STATEMENT],
        cwd=str(REPO_ROOT), capture_output=True,
    ).returncode == 0
    return ui_ok, missing, engine_ok


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(
    argv: Optional[list[str]] = None,
    *,
    run_pip: Optional[Callable[[list[str]], tuple[int, str]]] = None,
    run_check: Optional[Callable[[], int]] = None,
    run_verify: Optional[Callable[[], tuple[bool, list[str], bool]]] = None,  # (ui_ok, missing, engine_ok)
) -> int:
    """Entry point. ``run_pip``/``run_check``/``run_verify`` are test seams."""
    parser = argparse.ArgumentParser(
        prog="setup_env.py",
        description="Resilient one-shot dependency install + verification (issue #24).",
    )
    parser.add_argument(
        "--timeout", type=int, default=None,
        help=f"pip connection timeout in seconds "
             f"(default {DEFAULT_TIMEOUT}; env PIP_DEFAULT_TIMEOUT honoured)",
    )
    parser.add_argument(
        "--retries", type=int, default=DEFAULT_RETRIES,
        help=f"bounded per-package network retries (default {DEFAULT_RETRIES})",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--ui-only", action="store_true",
        help="install only requirements-ui.txt (the strict-isolation alternative)",
    )
    mode.add_argument(
        "--engine-only", action="store_true",
        help="install only requirements.txt + requirements-dev.txt (engine venv)",
    )
    mode.add_argument(
        "--check-only", action="store_true",
        help="skip installing; only verify imports + pip check (exit 0 = healthy)",
    )
    args = parser.parse_args(argv)

    timeout = effective_timeout(args.timeout)
    if not inside_virtualenv():
        print(
            "setup_env: WARNING — not inside a virtualenv; packages will install "
            "into this Python's site-packages. Consider: python -m venv .venv && "
            "source .venv/bin/activate",
            file=sys.stderr,
        )

    manifests = list(ALL_MANIFESTS)
    if args.ui_only:
        manifests = list(UI_MANIFESTS)
    elif args.engine_only:
        manifests = ["requirements.txt", "requirements-dev.txt"]

    if not args.check_only:
        print(f"setup_env: installing {', '.join(manifests)} "
              f"(timeout={timeout}s, retries={args.retries})")
        pip_cmd = pip_install_command(manifests, timeout, args.retries)
        # Single bounded invocation by design: "retry" = re-run this script
        # (documented); we never loop the install forever or swallow output.
        rc, output = (run_pip or stream_process)(pip_cmd)
        if rc != 0:
            print(f"setup_env: pip install FAILED (exit {rc}).\n{RETRY_HINT}",
                  file=sys.stderr)
            return EXIT_PIP_FAILED
        if detect_conflict(output):
            print(
                f"setup_env: DEPENDENCY CONFLICT detected even though pip "
                f"reported success.\n{CONFLICT_HINT}",
                file=sys.stderr,
            )
            return EXIT_DEPENDENCY_CONFLICT
    else:
        print("setup_env: check-only mode — no installation will be attempted.")

    print("setup_env: running pip check …")
    check_rc = (run_check or pip_check)()
    if check_rc != 0:
        print(
            "setup_env: pip check FAILED — the environment has broken package "
            "requirements. This is the dependency-conflict failure mode "
            "(issue #3); see the remediation printed by pip above and "
            "docs/08-local-development.md.",
            file=sys.stderr,
        )
        return EXIT_PIP_CHECK_FAILED

    print("setup_env: verifying imports in a fresh interpreter …")
    ui_ok, missing, engine_ok = (run_verify or verify_imports)()
    if args.ui_only:
        ok = ui_ok           # engine stack intentionally absent in isolation mode
    elif args.engine_only:
        ok = engine_ok       # UI stack intentionally absent in isolation mode
    else:
        ok = ui_ok and engine_ok
    if not ok:
        if not ui_ok:
            if missing:
                print(
                    f"setup_env: import verification FAILED — missing UI modules: "
                    f"{', '.join(missing)}. The install did not complete.\n{RETRY_HINT}",
                    file=sys.stderr,
                )
            else:
                print(
                    "setup_env: UI import failed although all modules are "
                    "installed — broken install or dependency conflict "
                    "(issue #3). Re-run the install; if it persists see "
                    "docs/08-local-development.md.",
                    file=sys.stderr,
                )
        else:
            print(
                "setup_env: ENGINE import failed (api.server). If the traceback "
                "mentions Starlette/Router, that is the issue-#3 dependency "
                "conflict — see core/dependency_guard.py and "
                "docs/08-local-development.md.",
                file=sys.stderr,
            )
        return EXIT_IMPORT_FAILED

    print("setup_env: environment verified — engine imports OK, "
          "UI stack (streamlit, streamlit-folium, folium, pandas) OK, "
          "pip check clean.")
    print("setup_env: next steps — 'python cli.py serve' (engine :8080) "
          "and 'python cli.py ui' (workspace :8501).")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
