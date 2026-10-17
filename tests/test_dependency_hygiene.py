"""Issue #3 regression checks — dependency resolution is verified, not assumed.

The historical failure: installing ``requirements-ui.txt`` into the engine
environment resolved streamlit 1.66 (``starlette>=0.46,<2``) which replaced
starlette 0.41.3; fastapi 0.115.6 needs ``starlette<0.42``. pip reported the
conflict but still completed, leaving a superficially installed yet unusable
environment whose only symptom was a cryptic ``TypeError`` at import time.

These tests run against the *actual* environment pytest executes in, so a
developer or CI who reproduces that mistake fails here with an actionable
message — before any server startup attempt.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from core.dependency_guard import (
    RuntimeDependencyError,
    specifier_holds,
    verify_runtime_dependencies,
)


# ---------------------------------------------------------------------------
# The repeatable clean-environment checks (run against the live environment)
# ---------------------------------------------------------------------------
def _installed_version(name: str) -> str | None:
    from importlib import metadata

    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _declared_starlette_spec(name: str) -> str | None:
    """Extract the declared `starlette<...>` specifier from installed metadata."""
    from importlib import metadata

    try:
        requires = metadata.requires(name) or []
    except metadata.PackageNotFoundError:
        return None
    for req in requires:
        base = req.split(";", 1)[0].strip()
        if base.lower().startswith("starlette"):
            spec = base[len("starlette"):].strip()
            return spec or "*"
    return None


def test_installed_starlette_satisfies_installed_fastapi():
    """A clean backend install has a compatible FastAPI/Starlette pair.

    This is the exact pair that broke historically (fastapi 0.115.6 +
    starlette 1.8.0 -> engine crash). Fail-open only if metadata is absent.
    """
    fastapi_v = _installed_version("fastapi")
    starlette_v = _installed_version("starlette")
    if fastapi_v is None or starlette_v is None:  # pragma: no cover
        pytest.skip("fastapi/starlette not installed in this environment")

    spec = _declared_starlette_spec("fastapi")
    assert spec is not None, "fastapi metadata must declare a starlette requirement"
    assert specifier_holds(spec, starlette_v), (
        f"Installed starlette {starlette_v} violates fastapi {fastapi_v}'s "
        f"declared requirement 'starlette{spec}'. Reinstall the environment "
        "with: pip install -r requirements.txt -r requirements-ui.txt "
        "-r requirements-dev.txt (see requirements-ui.txt, issue #3)."
    )


def test_installed_starlette_satisfies_coinstalled_streamlit():
    """UI dependencies must not leave an environment streamlit cannot run in.

    Skipped in engine-only environments (the UI venv / engine container),
    where streamlit is legitimately absent.
    """
    streamlit_v = _installed_version("streamlit")
    if streamlit_v is None:
        pytest.skip("streamlit not installed in this environment (engine-only)")
    starlette_v = _installed_version("starlette")
    if starlette_v is None:  # pragma: no cover
        pytest.skip("starlette not installed in this environment")

    spec = _declared_starlette_spec("streamlit")
    if spec is None:
        pytest.skip("this streamlit version declares no starlette requirement")
    assert specifier_holds(spec, starlette_v), (
        f"Installed starlette {starlette_v} violates streamlit {streamlit_v}'s "
        f"declared requirement 'starlette{spec}' (issue #3: the shared dev "
        "environment must satisfy both sides of the intersection)."
    )


def test_pip_check_is_clean():
    """The environment as a whole must be dependency-consistent.

    ``pip check`` is the repeatable whole-environment gate: the historical
    failure mode ("installer reported a conflict but still completed") is
    exactly what this command surfaces.
    """
    result = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        "pip check reported broken requirements:\n"
        f"{result.stdout.strip()}\n{result.stderr.strip()}\n"
        "Recreate the environment with the documented one-shot install: "
        "pip install -r requirements.txt -r requirements-ui.txt "
        "-r requirements-dev.txt (docs/08-local-development.md)."
    )


def test_engine_app_imports_and_health_gate():
    """``from api.server import app`` succeeds and /health returns 200.

    This also exercises the ``api/__init__.py`` guard wiring: importing the
    package runs ``verify_runtime_dependencies()`` before any router is
    constructed, so an incompatible environment fails HERE with the
    actionable RuntimeDependencyError instead of a cryptic TypeError.
    """
    from fastapi.testclient import TestClient

    from api.server import create_app

    with TestClient(create_app()) as client:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.json()
        # Documented contract (api/routes/misc.py): "ok" on the default
        # metadata-only probe, "degraded" only on a failed full check.
        assert body["status"] == "ok"


# ---------------------------------------------------------------------------
# The guard itself — unit-tested with injected metadata (no environment
# mutation needed). These encode both historical failure shapes.
# ---------------------------------------------------------------------------
class FakeMetadata:
    def __init__(self, versions: dict[str, str], requirements: dict[str, list[str]]):
        self._versions = versions
        self._requirements = requirements

    def version(self, name: str):
        return self._versions.get(name)

    def requires(self, name: str):
        return self._requirements.get(name, [])


def test_guard_accepts_historical_working_pair():
    """Engine-only venv: fastapi 0.115.6 + starlette 0.41.3, no streamlit."""
    meta = FakeMetadata(
        versions={"fastapi": "0.115.6", "starlette": "0.41.3"},
        requirements={"fastapi": ["starlette<0.42.0,>=0.40.0", "pydantic>=1.7.4"]},
    )
    verify_runtime_dependencies(metadata_source=meta)  # must not raise


def test_guard_rejects_historical_broken_pair():
    """The exact issue-#3 crash: streamlit 1.66 dragged starlette 1.8.0 in."""
    meta = FakeMetadata(
        versions={"fastapi": "0.115.6", "starlette": "1.8.0", "streamlit": "1.66.0"},
        requirements={
            "fastapi": ["starlette<0.42.0,>=0.40.0"],
            "streamlit": ["starlette<2,>=0.46.0", "pandas>=2.2.0"],
        },
    )
    with pytest.raises(RuntimeDependencyError) as excinfo:
        verify_runtime_dependencies(metadata_source=meta)
    message = str(excinfo.value)
    # Starlette 1.8.0 *satisfies* streamlit 1.66's requirement (that is
    # exactly why pip picked it) — the violated side is fastapi's cap.
    assert "fastapi 0.115.6 requires starlette<0.42.0,>=0.40.0" in message
    assert "starlette 1.8.0" in message
    assert "requirements-ui.txt" in message


def test_guard_reports_both_sides_when_starlette_too_old_for_both():
    """A starlette older than both ranges violates fastapi AND streamlit."""
    meta = FakeMetadata(
        versions={"fastapi": "0.115.14", "starlette": "0.39.0", "streamlit": "1.66.0"},
        requirements={
            "fastapi": ["starlette<0.47.0,>=0.40.0"],
            "streamlit": ["starlette<2,>=0.46.0"],
        },
    )
    with pytest.raises(RuntimeDependencyError) as excinfo:
        verify_runtime_dependencies(metadata_source=meta)
    message = str(excinfo.value)
    assert "fastapi 0.115.14 requires starlette<0.47.0,>=0.40.0" in message
    assert "streamlit 1.66.0 requires starlette<2,>=0.46.0" in message
    assert "starlette 0.39.0" in message


def test_guard_rejects_starlette_too_old_for_fastapi():
    """fastapi 0.115.14 with an ancient starlette is equally broken."""
    meta = FakeMetadata(
        versions={"fastapi": "0.115.14", "starlette": "0.20.0"},
        requirements={"fastapi": ["starlette<0.47.0,>=0.40.0"]},
    )
    with pytest.raises(RuntimeDependencyError):
        verify_runtime_dependencies(metadata_source=meta)


def test_guard_accepts_resolved_joint_stack():
    """The documented joint install: fastapi 0.115.14 + streamlit 1.66 +
    starlette 0.46.2 (the intersection of both ranges)."""
    meta = FakeMetadata(
        versions={"fastapi": "0.115.14", "starlette": "0.46.2", "streamlit": "1.66.0"},
        requirements={
            "fastapi": ["starlette<0.47.0,>=0.40.0"],
            "streamlit": ["starlette<2,>=0.46.0"],
        },
    )
    verify_runtime_dependencies(metadata_source=meta)  # must not raise


def test_guard_skips_pure_ui_environment():
    """No fastapi installed (the UI container's venv): nothing to protect."""
    meta = FakeMetadata(
        versions={"streamlit": "1.66.0", "starlette": "1.8.0"},
        requirements={"streamlit": ["starlette<2,>=0.46.0"]},
    )
    verify_runtime_dependencies(metadata_source=meta)  # must not raise


def test_guard_handles_streamlit_without_starlette_dep():
    """streamlit <= 1.45 declares no starlette requirement at all."""
    meta = FakeMetadata(
        versions={"fastapi": "0.115.14", "starlette": "0.41.3", "streamlit": "1.45.1"},
        requirements={
            "fastapi": ["starlette<0.47.0,>=0.40.0"],
            "streamlit": ["pandas>=2.2.0", "tornado>=6.1"],
        },
    )
    verify_runtime_dependencies(metadata_source=meta)  # must not raise


# ---------------------------------------------------------------------------
# Specifier evaluator (stdlib-only PEP 440 subset)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("spec", "version", "expected"),
    [
        ("<0.42.0,>=0.40.0", "0.41.3", True),
        ("<0.42.0,>=0.40.0", "0.42.0", False),
        ("<0.42.0,>=0.40.0", "1.8.0", False),
        ("<0.42.0,>=0.40.0", "0.39.9", False),
        ("<0.47.0,>=0.40.0", "0.46.2", True),
        ("<0.47.0,>=0.40.0", "0.46.10", True),   # 0.46.10 > 0.46.2 numerically
        ("<0.47.0,>=0.40.0", "0.47.0", False),
        ("<2,>=0.46.0", "1.8.0", True),
        ("<2,>=0.46.0", "0.46.0", True),
        ("<2,>=0.46.0", "0.45.9", False),
        ("==0.46.2", "0.46.2", True),
        ("==0.46.2", "0.46.02", True),           # zero-padded equality
        ("!=1.8.0", "0.46.2", True),
        ("!=1.8.0", "1.8.0", False),
        ("~=0.46", "0.46.9", True),
        # PEP 440 compatible release: ~=0.46 means >=0.46, ==0.*  (so 0.47
        # still holds; 1.0 does not).
        ("~=0.46", "0.47.0", True),
        ("~=0.46", "1.0.0", False),
        ("~=0.46.0", "0.46.5", True),
        ("~=0.46.0", "0.47.0", False),
        ("*", "1.8.0", True),
        ("", "1.8.0", True),
        (">=0.40.0; python_version >= '3.10'", "0.41.0", True),  # marker ignored
    ],
)
def test_specifier_holds(spec: str, version: str, expected: bool):
    assert specifier_holds(spec, version) is expected
