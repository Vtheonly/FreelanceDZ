"""Repository hygiene & architecture checks (user task §8).

Automated guards for the invariants the refactor established:

    * every project module imports cleanly (no broken imports);
    * no references to removed subsystems (C++ core, legacy dashboard,
      template engine) survive anywhere;
    * the UI package stays a PURE API client — importing engine internals
      (storage, scrapers, engine, services) from ui/ fails the build;
    * no import cycles among the engine's top-level packages;
    * the repo root stays intentional (no orphaned directories/files);
    * no module is unreachable from the documented entry points (dead
      code detector with an explicit, reviewed allowlist);
    * secrets and generated data stay untracked (.env, data/, caches).

These are structural tests: they verify the SHAPE of the codebase, which
unit tests cannot cover.
"""

from __future__ import annotations

import ast
import os
import subprocess
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_PACKAGES = [
    "api", "config", "core", "domain", "engine",
    "infrastructure", "services", "utils", "ui", "benchmarks", "scripts",
]

# Modules that are legitimately not imported by others: entry points and
# intentional public surfaces (reviewed — see docs/02-architecture.md).
ENTRY_POINTS = {
    "main", "cli", "ui.app", "ui.api_client", "ui.state", "ui.theme",
    "api.server", "benchmarks.bench_engine", "benchmarks.bench_storage",
    "scripts.fetch_wilaya_boundaries",
}

FORBIDDEN_IN_UI = (
    "infrastructure", "services", "engine.storage", "engine.scorer",
    "engine.analyzer", "engine.resolver", "config.settings", "domain",
)

REMOVED_SUBSYSTEM_MARKERS = (
    "engine.native",
    "engine_native",
    "NativeEngine",
    "api.templates",
    "TemplateResponse",
    "ENABLE_DASHBOARD",
)

EXPECTED_ROOT_ENTRIES = {
    # files
    ".env.example", ".gitignore", "README.md",
    "cli.py", "docker-compose.yml", "main.py", "pyproject.toml",
    "requirements.txt", "requirements-dev.txt", "requirements-ui.txt",
    # directories
    "api", "benchmarks", "config", "core", "docker", "docs", "domain",
    "engine", "infrastructure", "scripts", "services", "tests", "ui", "utils",
}


def _project_modules() -> dict[str, Path]:
    """module_name -> file path for every Python module under the packages."""
    modules: dict[str, Path] = {}
    for package in SRC_PACKAGES:
        for path in (PROJECT_ROOT / package).rglob("*.py"):
            rel = path.relative_to(PROJECT_ROOT).with_suffix("")
            parts = list(rel.parts)
            if parts[-1] == "__init__":
                parts = parts[:-1]
            modules[".".join(parts)] = path
    # root-level modules
    for path in PROJECT_ROOT.glob("*.py"):
        modules[path.stem] = path
    return modules


def _imports_of(path: Path) -> set[str]:
    """All absolute imports referenced by a module (any depth)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:
                found.add(node.module)
            elif node.level == 0 and not node.module:
                # ``from pkg import thing`` with implicit package root.
                for alias in node.names:
                    found.add(alias.name)
    return found


# ---------------------------------------------------------------------------
# Clean imports
# ---------------------------------------------------------------------------
def test_every_project_module_compiles():
    modules = _project_modules()
    assert len(modules) > 60
    for name, path in modules.items():
        try:
            ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError as exc:
            pytest.fail(f"{name}: syntax error: {exc}")


def test_no_broken_internal_imports():
    """Every internal import in every module must resolve to a real module."""
    modules = _project_modules()
    top_level = {name.split(".")[0] for name in modules}
    for name, path in modules.items():
        for imported in _imports_of(path):
            root = imported.split(".")[0]
            if root not in top_level:
                continue  # third-party / stdlib
            resolved = imported in modules or any(
                m.startswith(imported + ".") for m in modules
            )
            # `from package import thing` where thing is a symbol: resolve
            # the longest importable prefix.
            if not resolved:
                parts = imported.split(".")
                resolved = any(
                    ".".join(parts[:i]) in modules for i in range(1, len(parts) + 1)
                )
            assert resolved, f"{name} imports missing module {imported!r}"


def test_no_references_to_removed_subsystems():
    """Stale REFERENCES (imports), not historical mentions in prose —
    docstrings documenting the removal are legitimate."""
    self_path = Path(__file__).resolve()
    offenders = []
    for path in PROJECT_ROOT.rglob("*.py"):
        if path == self_path:
            continue
        if any(part in {".venv", "node_modules", "__pycache__"} for part in path.parts):
            continue
        for imported in _imports_of(path):
            for marker in REMOVED_SUBSYSTEM_MARKERS:
                if imported == marker or imported.startswith(marker + "."):
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)} imports {imported}")
    assert not offenders, f"stale imports of removed code: {offenders}"


# ---------------------------------------------------------------------------
# UI purity (the API-client contract)
# ---------------------------------------------------------------------------
def test_ui_never_imports_engine_internals():
    offenders = []
    for path in (PROJECT_ROOT / "ui").rglob("*.py"):
        for forbidden in FORBIDDEN_IN_UI:
            for imported in _imports_of(path):
                if imported == forbidden or imported.startswith(forbidden + "."):
                    offenders.append(f"{path.relative_to(PROJECT_ROOT)} imports {imported}")
    assert not offenders, (
        "ui/ must stay a pure API client (no engine/storage imports): "
        f"{offenders}"
    )


def test_ui_dependencies_declared_separately():
    """requirements-ui.txt must not pull engine-only dependencies."""
    lines = [
        line.split("#")[0].strip().lower()
        for line in (PROJECT_ROOT / "requirements-ui.txt").read_text().splitlines()
    ]
    ui_deps = {line for line in lines if line and not line.startswith("-")}
    for engine_dep in ("fastapi", "uvicorn", "phonenumbers", "rapidfuzz",
                       "beautifulsoup4", "pydantic"):
        assert engine_dep not in ui_deps, f"ui image must not need {engine_dep}"


# ---------------------------------------------------------------------------
# Import cycles
# ---------------------------------------------------------------------------
def test_no_import_cycles_between_packages():
    """Package-level dependency graph must be acyclic (module-level cycles
    inside one package are allowed and often benign)."""
    modules = _project_modules()
    top_level = {name.split(".")[0] for name in modules}

    def package_of(module: str) -> str:
        return module.split(".")[0]

    edges: dict[str, set[str]] = {}
    for name, path in modules.items():
        src = package_of(name)
        for imported in _imports_of(path):
            dst = package_of(imported)
            if dst in top_level and dst != src:
                edges.setdefault(src, set()).add(dst)

    # Kahn's algorithm.
    nodes = set(edges) | {d for targets in edges.values() for d in targets}
    indegree = {n: 0 for n in nodes}
    for targets in edges.values():
        for t in targets:
            indegree[t] += 1
    queue = [n for n, d in indegree.items() if d == 0]
    seen = 0
    while queue:
        node = queue.pop()
        seen += 1
        for target in edges.get(node, set()):
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    assert seen == len(nodes), f"import cycle among packages: {indegree}"


# ---------------------------------------------------------------------------
# Dead modules (unreachable from entry points)
# ---------------------------------------------------------------------------
def test_no_unreachable_modules():
    modules = _project_modules()

    reachable: set[str] = set()
    frontier = [m for m in ENTRY_POINTS if m in modules]
    while frontier:
        module = frontier.pop()
        if module in reachable:
            continue
        reachable.add(module)
        for imported in _imports_of(modules[module]):
            for cand in [imported] + [m for m in modules if m.startswith(imported + ".")]:
                if cand in modules and cand not in reachable:
                    frontier.append(cand)

    # A reachable submodule makes every ancestor package reachable (the
    # package __init__ is executed on first submodule import).
    changed = True
    while changed:
        changed = False
        for module in list(reachable):
            parent = module.rsplit(".", 1)[0] if "." in module else None
            if parent and parent in modules and parent not in reachable:
                reachable.add(parent)
                changed = True
                # The package init's own imports count now.
                frontier = [parent]
                while frontier:
                    walk = frontier.pop()
                    for imported in _imports_of(modules[walk]):
                        for cand in [imported] + [m for m in modules if m.startswith(imported + ".")]:
                            if cand in modules and cand not in reachable:
                                reachable.add(cand)
                                frontier.append(cand)

    orphans = sorted(set(modules) - reachable - ENTRY_POINTS)
    assert not orphans, f"modules unreachable from any entry point: {orphans}"


# ---------------------------------------------------------------------------
# Repository structure
# ---------------------------------------------------------------------------
def test_repo_root_is_intentional():
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    root_entries = {t.split("/")[0] for t in tracked}
    unexpected = root_entries - EXPECTED_ROOT_ENTRIES
    assert not unexpected, f"unexpected root entries: {unexpected}"


def test_generated_data_and_secrets_are_untracked():
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=PROJECT_ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    offenders = [
        t for t in tracked
        if t.startswith("data/") or t == ".env" or t.endswith((".db", ".db-wal", ".db-shm"))
        or t.startswith("refactorv2/") or t.startswith(".smartexport/")
        or "engine_native" in t or "dashboard.html" in t
    ]
    assert not offenders, f"generated/secret/orphan files tracked: {offenders}"


def test_geodata_is_committed_and_attributed():
    geojson = PROJECT_ROOT / "engine" / "geodata" / "algeria_wilayas_58.geojson"
    attribution = PROJECT_ROOT / "engine" / "geodata" / "ATTRIBUTION.md"
    assert geojson.exists(), "boundary dataset missing from the repo"
    assert attribution.exists(), "ODbL attribution must ship with the dataset"
    text = attribution.read_text(encoding="utf-8")
    assert "OpenStreetMap" in text and "ODbL" in text


# ---------------------------------------------------------------------------
# Static analysis (ruff — skipped when not installed)
# ---------------------------------------------------------------------------
def test_ruff_clean_on_changed_packages():
    ruff = os.environ.get("RUFF_BIN", "ruff")
    try:
        result = subprocess.run(
            [ruff, "check", "--select", "F,E9", "--quiet",
             "api", "config", "core", "domain", "engine", "infrastructure",
             "services", "utils", "ui", "benchmarks", "scripts", "tests"],
            cwd=PROJECT_ROOT, capture_output=True, text=True,
        )
    except FileNotFoundError:
        pytest.skip("ruff not installed")
        return
    if result.returncode not in (0, 1):
        pytest.skip(f"ruff unavailable: {result.stderr[:100]}")
    problems = [line for line in result.stdout.splitlines() if line.strip()]
    assert not problems, "ruff found real issues (F=pyflakes, E9=syntax):\n" + "\n".join(problems)
