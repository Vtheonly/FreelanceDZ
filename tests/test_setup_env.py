"""Issue #24 — resilient UI dependency installation.

The two historical failure modes (docs/refactor/error.log.md) must stay
explicit and distinguishable:

1. pip dies mid-download (ReadTimeoutError) -> exit 1, retry hint, no
   "success" wording, follow-up commands impossible (non-zero exit).
2. pip exits 0 after printing the resolver-conflict banner -> exit 2 with
   the issue-#3 remediation, NOT a success.

Plus: bounded timeouts/retries on the pip command, streamed output (never
hidden), post-install verification naming the missing component, and the
``cli.py ui`` preflight turning a partial install into an actionable error.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from click.testing import CliRunner

from core import dependency_guard

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Load scripts/setup_env.py as a module (scripts/ is not a package).
_setup_spec = importlib.util.spec_from_file_location(
    "setup_env", PROJECT_ROOT / "scripts" / "setup_env.py"
)
setup_env = importlib.util.module_from_spec(_setup_spec)
_setup_spec.loader.exec_module(setup_env)


# The exact banner pip printed while still exiting 0 (error.log.md lines
# 101-103) — the historical trap this script must catch.
HISTORICAL_CONFLICT_OUTPUT = """\
ERROR: pip's dependency resolver does not currently take into account all the packages that are installed. This behaviour is the source of dependency conflicts.
fastapi 0.115.6 requires starlette<0.42.0,>=0.40.0, but you have starlette 1.8.0 which is incompatible.
Successfully installed altair-6.3.0 ... streamlit-1.66.0 streamlit-folium-0.27.4
"""


# ---------------------------------------------------------------------------
# Command construction: bounded, configurable timeout/retries
# ---------------------------------------------------------------------------
class TestPipCommand:
    def test_timeout_and_retries_are_explicit_and_bounded(self):
        cmd = setup_env.pip_install_command(["requirements-ui.txt"], 120, 3)
        assert "--default-timeout" in cmd and "120" in cmd
        assert "--retries" in cmd and "3" in cmd
        # manifests resolved relative to the repo, not the CWD
        assert str(PROJECT_ROOT / "requirements-ui.txt") in cmd

    def test_effective_timeout_cli_overrides_env(self, monkeypatch):
        monkeypatch.setenv("PIP_DEFAULT_TIMEOUT", "45")
        assert setup_env.effective_timeout(None) == 45
        assert setup_env.effective_timeout(300) == 300
        monkeypatch.setenv("PIP_DEFAULT_TIMEOUT", "not-a-number")
        assert setup_env.effective_timeout(None) == setup_env.DEFAULT_TIMEOUT

    def test_default_timeout_is_sensible(self, monkeypatch):
        monkeypatch.delenv("PIP_DEFAULT_TIMEOUT", raising=False)
        assert setup_env.effective_timeout(None) == 120


# ---------------------------------------------------------------------------
# Failure mode 1: interrupted install (pip non-zero)
# ---------------------------------------------------------------------------
class TestPipFailure:
    def test_interrupted_install_fails_explicitly(self, monkeypatch, capsys):
        monkeypatch.setattr(sys, "stderr", capsys.stderr)
        calls = []

        def fake_pip(cmd):
            calls.append(cmd)
            return 1, "Collecting streamlit>=1.41.0\n" \
                      "WARNING: Retrying … Read timed out.\n"

        rc = setup_env.main(["--timeout", "60"], run_pip=fake_pip,
                            run_check=lambda: 0,
                            run_verify=lambda: (True, [], True))
        assert rc == setup_env.EXIT_PIP_FAILED
        # exactly ONE bounded invocation — never an unlimited retry loop
        assert len(calls) == 1
        assert "--default-timeout" in calls[0] and "60" in calls[0]
        err = capsys.readouterr().err
        assert "FAILED" in err
        assert "Re-run" in err                # retry guidance
        assert "deleted" in err               # explicitly: no user data deleted
        assert "success" not in err.lower()   # never reported as successful

    def test_followup_commands_are_stopped_by_nonzero_exit(self):
        # A shell `&&` chain stops on exit 1 — the contract tests rely on.
        assert setup_env.EXIT_PIP_FAILED != 0
        assert setup_env.EXIT_DEPENDENCY_CONFLICT != 0
        assert setup_env.EXIT_IMPORT_FAILED != 0


# ---------------------------------------------------------------------------
# Failure mode 2: dependency conflict reported while pip exits 0
# ---------------------------------------------------------------------------
class TestConflictDetection:
    def test_detects_historical_banner(self):
        assert setup_env.detect_conflict(HISTORICAL_CONFLICT_OUTPUT) is True

    def test_ignores_normal_output(self):
        assert setup_env.detect_conflict("Successfully installed streamlit-1.66.0\n") is False
        assert setup_env.detect_conflict("") is False

    def test_conflict_with_pip_rc_zero_still_fails(self, capsys):
        rc = setup_env.main([], run_pip=lambda cmd: (0, HISTORICAL_CONFLICT_OUTPUT),
                            run_check=lambda: 0,
                            run_verify=lambda: (True, [], True))
        assert rc == setup_env.EXIT_DEPENDENCY_CONFLICT
        err = capsys.readouterr().err
        assert "issue #3" in err or "issue-#3" in err  # points at the separate resolution
        assert "isolation" in err or "ONE-SHOT" in err


# ---------------------------------------------------------------------------
# Post-install verification: name the missing component
# ---------------------------------------------------------------------------
class TestVerification:
    def test_missing_ui_module_is_named(self, capsys):
        rc = setup_env.main(
            [], run_pip=lambda cmd: (0, "Successfully installed …"),
            run_check=lambda: 0,
            run_verify=lambda: (False, ["streamlit", "folium"], True),
        )
        assert rc == setup_env.EXIT_IMPORT_FAILED
        err = capsys.readouterr().err
        assert "streamlit" in err and "folium" in err
        assert "missing UI modules" in err
        assert "pandas" not in err  # present modules are NOT reported missing

    def test_broken_engine_import_points_at_issue3(self, capsys):
        rc = setup_env.main(
            [], run_pip=lambda cmd: (0, "Successfully installed …"),
            run_check=lambda: 0,
            run_verify=lambda: (True, [], False),
        )
        assert rc == setup_env.EXIT_IMPORT_FAILED
        err = capsys.readouterr().err
        assert "ENGINE" in err and "#3" in err

    def test_ui_installed_but_not_importable_points_at_conflict(self, capsys):
        rc = setup_env.main(
            [], run_pip=lambda cmd: (0, "Successfully installed …"),
            run_check=lambda: 0,
            run_verify=lambda: (False, [], True),
        )
        assert rc == setup_env.EXIT_IMPORT_FAILED
        assert "dependency conflict" in capsys.readouterr().err

    def test_pip_check_failure_is_distinct(self, capsys):
        rc = setup_env.main(
            [], run_pip=lambda cmd: (0, "Successfully installed …"),
            run_check=lambda: 1,
            run_verify=lambda: (True, [], True),
        )
        assert rc == setup_env.EXIT_PIP_CHECK_FAILED
        assert "pip check FAILED" in capsys.readouterr().err

    def test_check_only_never_installs(self):
        def boom(cmd):  # pragma: no cover - fails the test if called
            raise AssertionError("pip must not run in --check-only mode")
        rc = setup_env.main(["--check-only"], run_pip=boom,
                            run_check=lambda: 0,
                            run_verify=lambda: (True, [], True))
        assert rc == setup_env.EXIT_OK

    def test_ui_only_mode_ignores_missing_engine_stack(self):
        # strict isolation: no fastapi in the UI venv — that is healthy, not a failure
        rc = setup_env.main(["--ui-only"], run_pip=lambda cmd: (0, "ok"),
                            run_check=lambda: 0,
                            run_verify=lambda: (True, [], False))
        assert rc == setup_env.EXIT_OK

    def test_engine_only_mode_ignores_missing_ui_stack(self):
        rc = setup_env.main(["--engine-only"], run_pip=lambda cmd: (0, "ok"),
                            run_check=lambda: 0,
                            run_verify=lambda: (False, list(setup_env.UI_IMPORT_MODULES), True))
        assert rc == setup_env.EXIT_OK

    def test_happy_path_reports_success_and_next_steps(self, capsys):
        rc = setup_env.main(["--check-only"], run_pip=lambda cmd: (0, "ok"),
                            run_check=lambda: 0,
                            run_verify=lambda: (True, [], True))
        assert rc == setup_env.EXIT_OK
        out = capsys.readouterr().out
        assert "verified" in out
        assert "cli.py serve" in out and "cli.py ui" in out


# ---------------------------------------------------------------------------
# cli.py ui preflight
# ---------------------------------------------------------------------------
class TestUiCommandPreflight:
    def test_partial_install_stops_with_actionable_message(self, monkeypatch):
        import cli

        # cli.py imports late, so patching the module attribute is enough —
        # verify_ui_dependencies() resolves missing_ui_modules via globals.
        monkeypatch.setattr(
            "core.dependency_guard.missing_ui_modules",
            lambda: ["streamlit", "streamlit_folium"],
        )
        runner = CliRunner()
        result = runner.invoke(cli.ui, ["--port", "8501"])
        assert result.exit_code != 0
        assert "Missing" in result.output or "missing" in result.output.lower()
        assert "setup_env.py" in result.output          # remediation named
        assert "ModuleNotFoundError" not in result.output
        assert "Re-run" in result.output or "retry" in result.output.lower()

    def test_ui_help_still_works(self):
        import cli
        runner = CliRunner()
        result = runner.invoke(cli.ui, ["--help"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# core.dependency_guard UI probe
# ---------------------------------------------------------------------------
class TestGuardUiProbe:
    def test_missing_ui_modules_uses_find_spec(self, monkeypatch):
        seen = []

        class FakeSpec:
            def __init__(self, name):
                self.name = name

        def fake_find_spec(name, *a, **k):
            seen.append(name)
            return None if name == "pandas" else FakeSpec(name)

        monkeypatch.setattr(dependency_guard.importlib.util, "find_spec", fake_find_spec)
        assert dependency_guard.missing_ui_modules() == ["pandas"]
        assert seen == list(dependency_guard.UI_IMPORT_PROBES)

    def test_verify_ui_dependencies_raises_with_remediation(self, monkeypatch):
        monkeypatch.setattr(
            dependency_guard, "missing_ui_modules", lambda: ["folium"]
        )
        with pytest.raises(dependency_guard.MissingUIDependencyError) as exc:
            dependency_guard.verify_ui_dependencies()
        msg = str(exc.value)
        assert "folium" in msg
        assert "setup_env.py" in msg
        assert "requirements-ui.txt" in msg

    def test_verify_ui_dependencies_passes_when_complete(self, monkeypatch):
        monkeypatch.setattr(dependency_guard, "missing_ui_modules", lambda: [])
        dependency_guard.verify_ui_dependencies()  # must not raise

    def test_is_subclass_of_runtime_error(self):
        assert issubclass(
            dependency_guard.MissingUIDependencyError,
            dependency_guard.RuntimeDependencyError,
        )
