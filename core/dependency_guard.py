"""Runtime dependency verification — the issue-#3 fail-fast guard.

Background
----------
Installing the UI requirements into the engine's environment can silently
upgrade Starlette past the range the installed FastAPI supports (pip only
resolves the packages named on the command line; an already-installed
FastAPI's constraint is reported as a warning, not an error). The engine
then crashes deep inside Starlette with a cryptic message such as::

    TypeError: Router.__init__() got an unexpected keyword argument 'on_startup'

This module proves the framework stack is coherent *before* any router is
constructed and raises an actionable error instead.

What is verified
----------------
1. The installed Starlette satisfies the installed FastAPI's declared
   ``starlette`` requirement (read from package metadata, never assumed).
2. When Streamlit is co-installed in the same environment (the documented
   single-venv development setup), the installed Starlette must also
   satisfy Streamlit's declared ``starlette`` requirement.

The check is deliberately conservative: it only fails when it can *prove*
an incompatibility from installed metadata. Missing packages (e.g. a pure
UI environment without FastAPI) or unparseable metadata never block
startup.

The verification is wired into ``api/__init__.py`` (before ``api.server``
constructs any router) and into ``cli.py serve``. Repeatable checks live in
``tests/test_dependency_hygiene.py``.
"""

from __future__ import annotations

import importlib.util
import logging
import re
from dataclasses import dataclass
from importlib import metadata as importlib_metadata
from typing import Optional, Protocol

logger = logging.getLogger("core.dependency_guard")


class RuntimeDependencyError(Exception):
    """The installed packages are provably incompatible.

    Raised instead of letting the app die later inside Starlette with an
    opaque ``TypeError``. The message always lists what is installed, what
    each side requires, and the documented remediation.
    """


@dataclass(frozen=True)
class Requirement:
    """One ``name + specifier`` clause pair from package metadata."""

    name: str
    specifier: str


class MetadataSource(Protocol):
    """Injectable view of the environment's package metadata (test seam)."""

    def version(self, name: str) -> Optional[str]: ...

    def requires(self, name: str) -> list[str]: ...


class InstalledMetadata:
    """Production metadata source backed by ``importlib.metadata``."""

    def version(self, name: str) -> Optional[str]:
        try:
            return importlib_metadata.version(name)
        except importlib_metadata.PackageNotFoundError:
            return None
        except Exception:  # pragma: no cover - defensive: odd environments
            return None

    def requires(self, name: str) -> list[str]:
        try:
            return list(importlib_metadata.requires(name) or [])
        except Exception:  # pragma: no cover - defensive
            return []


# ---------------------------------------------------------------------------
# Minimal PEP 440 subset parser (stdlib only — `packaging` is not an engine
# dependency, so we evaluate the operators we actually encounter in the
# fastapi/streamlit/starlette requirement strings).
# ---------------------------------------------------------------------------
_CLAUSE_RE = re.compile(r"^\s*(===|==|!=|<=|>=|~=|<|>)\s*([^\s,]+)\s*$")
_NUM_RE = re.compile(r"^(\d+)(.*)$")


def _version_key(version: str) -> tuple:
    """Map a dotted version to a comparable tuple of numbers/strings.

    ``0.46`` and ``0.46.0`` compare equal (PEP 440 zero-padding); trailing
    non-numeric fragments compare lexicographically after their numeric
    head (sufficient for ``0.46.2rc1``-style strings and strictly better
    than crashing). Unparseable input returns ``()`` which sorts first.
    """
    parts: list = []
    for segment in version.split("."):
        m = _NUM_RE.match(segment)
        if m:
            parts.append(int(m.group(1)))
            rest = m.group(2)
            if rest:
                parts.append(rest)
        else:
            parts.append(segment)
    return tuple(parts)


def _padded(a: tuple, b: tuple) -> tuple[tuple, tuple]:
    width = max(len(a), len(b))
    return (
        a + (0,) * (width - len(a)),
        b + (0,) * (width - len(b)),
    )


def _clause_holds(op: str, operand: str, installed: tuple) -> Optional[bool]:
    """Evaluate one specifier clause; ``None`` = cannot evaluate."""
    if operand == "*":
        return True
    ref = _version_key(operand)
    if not ref:
        return None
    a, b = _padded(installed, ref)
    if op in ("==", "==="):
        return a == b
    if op == "!=":
        return a != b
    if op == "<":
        return a < b
    if op == "<=":
        return a <= b
    if op == ">":
        return a > b
    if op == ">=":
        return a >= b
    if op == "~=":
        # Compatible release: ~=X.Y.Z means >=X.Y.Z, <X.(Y+1)
        if len(ref) < 2:
            return None
        upper = list(ref[:-1])
        upper[-1] = (upper[-1] if isinstance(upper[-1], int) else 0) + 1
        ua, _ = _padded(installed, tuple(upper))
        la, lb = _padded(installed, ref)
        return la >= lb and ua < tuple(upper)
    return None  # pragma: no cover - unknown operator


def specifier_holds(specifier: str, installed_version: str) -> bool:
    """True when ``installed_version`` satisfies every clause.

    A clause we cannot parse evaluates to True (fail-open): the guard must
    only fail on provable incompatibility.
    """
    installed = _version_key(installed_version)
    for clause in specifier.split(","):
        clause = clause.strip()
        if not clause:
            continue
        m = _CLAUSE_RE.match(clause)
        if not m:
            continue  # unparseable clause (e.g. environment markers) — skip
        held = _clause_holds(m.group(1), m.group(2), installed)
        if held is False:
            return False
    return True


def _starlette_requirement(requires: list[str]) -> Optional[Requirement]:
    """Extract the declared ``starlette`` constraint from a requirement list."""
    for req in requires:
        # Strip environment markers: "starlette<0.42.0,>=0.40.0; python_version >= '3.10'"
        base = req.split(";", 1)[0].strip()
        m = re.match(r"^([A-Za-z0-9_.\[\]-]+)\s*(.*)$", base)
        if m and m.group(1).split("[")[0].lower() == "starlette":
            return Requirement("starlette", m.group(2).strip() or "*")
    return None


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------
def verify_runtime_dependencies(
    metadata_source: Optional[MetadataSource] = None,
) -> None:
    """Verify the installed framework stack is coherent; raise otherwise.

    See the module docstring for scope. Pure-UI environments (FastAPI not
    installed) and engine-only environments (Streamlit not installed) are
    both valid and pass.
    """
    meta: MetadataSource = metadata_source or InstalledMetadata()

    fastapi_version = meta.version("fastapi")
    starlette_version = meta.version("starlette")
    streamlit_version = meta.version("streamlit")

    if fastapi_version is None:
        # No engine stack in this environment (e.g. the UI container's own
        # venv) — nothing to protect.
        return

    conflicts: list[str] = []

    if starlette_version is not None:
        fastapi_req = _starlette_requirement(meta.requires("fastapi"))
        if fastapi_req is not None and not specifier_holds(
            fastapi_req.specifier, starlette_version
        ):
            conflicts.append(
                f"  fastapi {fastapi_version} requires starlette{fastapi_req.specifier}\n"
                f"  installed: starlette {starlette_version}"
            )
    else:
        # fastapi without starlette cannot even import; let that fail with
        # its natural ImportError rather than a misleading message here.
        return

    # The shared single-venv development setup (docs/08-local-development.md)
    # co-installs streamlit; its starlette constraint must also hold.
    if streamlit_version is not None:
        streamlit_req = _starlette_requirement(meta.requires("streamlit"))
        if streamlit_req is not None and not specifier_holds(
            streamlit_req.specifier, starlette_version
        ):
            conflicts.append(
                f"  streamlit {streamlit_version} requires starlette{streamlit_req.specifier}\n"
                f"  installed: starlette {starlette_version}"
            )

    if not conflicts:
        return

    raise RuntimeDependencyError(
        "The installed web-framework stack is incompatible:\n\n"
        + "\n".join(conflicts)
        + "\n\nThe engine refuses to start in this environment. Installing\n"
        "UI requirements into the engine environment can silently upgrade\n"
        "starlette past the installed fastapi's supported range.\n"
        "\n"
        "Fix options:\n"
        "  1. Recreate the shared environment with the documented one-shot\n"
        "     install so pip resolves all manifests together:\n"
        "       pip install -r requirements.txt -r requirements-ui.txt -r requirements-dev.txt\n"
        "  2. Or keep the stacks isolated in separate virtual environments\n"
        "     (engine: requirements.txt + requirements-dev.txt; UI:\n"
        "     requirements-ui.txt) — see docs/08-local-development.md.\n"
        "  3. Or run the Docker deployment, where engine and UI live in\n"
        "     separate containers by construction: docker compose up.\n"
        "\n"
        "Verified by tests/test_dependency_hygiene.py (issue #3)."
    )


# ---------------------------------------------------------------------------
# UI runtime availability (issue #24)
# ---------------------------------------------------------------------------
# A partially-installed environment (e.g. pip died mid-way through the
# Streamlit wheel on a flaky link) used to surface as a raw
# ``ModuleNotFoundError`` traceback deep inside Streamlit launch. The
# ``cli.py ui`` preflight instead names exactly what is missing and how to
# finish the installation. Probing uses ``find_spec`` — no UI module is ever
# imported here, so the check stays instant and side-effect free.

UI_IMPORT_PROBES: tuple[str, ...] = ("streamlit", "streamlit_folium", "folium", "pandas")


class MissingUIDependencyError(RuntimeDependencyError):
    """UI runtime modules are not installed (partial install — issue #24)."""


def missing_ui_modules() -> list[str]:
    """Return the UI runtime modules missing from this environment.

    ``[]`` means the UI stack is importable-ready. Used by ``cli.py ui``
    before spawning Streamlit and by ``scripts/setup_env.py``'s
    post-install verification.
    """
    missing: list[str] = []
    for module in UI_IMPORT_PROBES:
        try:
            if importlib.util.find_spec(module) is None:
                missing.append(module)
        except (ImportError, ValueError):  # pragma: no cover - malformed path entries
            missing.append(module)
    return missing


def verify_ui_dependencies() -> None:
    """Raise :class:`MissingUIDependencyError` if the UI stack is incomplete.

    Never imports any UI package; safe to call from any environment (a
    pure-engine environment will simply report the UI modules missing,
    which is exactly the actionable message a ``cli.py ui`` user needs).
    """
    missing = missing_ui_modules()
    if not missing:
        return
    raise MissingUIDependencyError(
        "The Streamlit UI stack is not fully installed in this environment.\n"
        f"Missing: {', '.join(missing)}\n"
        "\n"
        "This usually means the UI dependency install was interrupted\n"
        "(e.g. a network timeout while downloading the Streamlit wheel).\n"
        "Re-running the install is safe and loses nothing: your venv, .env\n"
        "and database are untouched. Finish the installation with either:\n"
        "  python scripts/setup_env.py            # resilient installer + verification\n"
        "  pip install -r requirements-ui.txt     # plain pip (retry on timeout)\n"
        "\n"
        "If pip reports a *dependency conflict* instead (fastapi/starlette),\n"
        "that is the separate issue-#3 environment-isolation problem — see\n"
        "docs/08-local-development.md and core/dependency_guard.py."
    )


__all__ = [
    "InstalledMetadata",
    "MetadataSource",
    "MissingUIDependencyError",
    "Requirement",
    "RuntimeDependencyError",
    "UI_IMPORT_PROBES",
    "missing_ui_modules",
    "specifier_holds",
    "verify_runtime_dependencies",
    "verify_ui_dependencies",
]
