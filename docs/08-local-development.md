# 08 · Local Development

## Prerequisites

- Python 3.10+ (3.12 recommended)
- pip

## Setup (five commands)

```bash
git clone https://github.com/Vtheonly/FreelanceDZ.git
cd FreelanceDZ
python -m venv .venv && source .venv/bin/activate
python scripts/setup_env.py     # resilient install + verification (issue #24)
cp .env.example .env            # optional: adjust to taste
```

`scripts/setup_env.py` is a stdlib-only installer wrapper that makes the
two historical clean-machine failure modes explicit and distinguishable
(the plain-pip alternative is documented below):

* **Transient download timeouts** — pip runs with a bounded, configurable
  connection timeout (`--timeout`, default 120 s, `$PIP_DEFAULT_TIMEOUT`
  honoured) and bounded network retries (`--retries`, default 3). Output
  is streamed live, never hidden. On failure the script exits non-zero
  and prints the retry guidance: **just re-run the same command** —
  pip's HTTP cache keeps completed downloads and nothing deletes your
  venv, `.env` or `data/` directory.
* **Dependency conflicts (issue #3)** — pip famously exits **0** after
  printing `ERROR: pip's dependency resolver … which is incompatible`
  (see `docs/refactor/error.log.md`). The script scans for that banner
  and fails with the issue-#3 remediation instead of letting you walk
  into the Starlette crash.
* **Post-install verification** — after installing, it runs
  `pip check` and import-verifies both stacks in a fresh interpreter:
  `api.server` (engine) and `streamlit`, `streamlit_folium`, `folium`,
  `pandas` (UI). A missing component is named explicitly, so a partial
  install can never be reported as successful.

Exit codes: `0` verified · `1` pip failed (retry) · `2` dependency
conflict (issue #3) · `3` `pip check` failed · `4` import verification
failed. `python scripts/setup_env.py --check-only` verifies an existing
environment without installing; `--ui-only` / `--engine-only` support the
strict-isolation layout below.

### Plain-pip alternative

```bash
pip install -r requirements.txt -r requirements-ui.txt -r requirements-dev.txt
```

Install all requirement files **in one command** so pip resolves the
shared pins together. The manifests are kept mutually compatible on
purpose: the engine pins `fastapi==0.115.14` (supports
`starlette<0.47`), which intersects modern Streamlit's
`starlette>=0.46` at exactly Starlette 0.46.x — so the joint install
resolves cleanly. Never install `requirements-ui.txt` *after* the
engine set in the same venv on an older fastapi: pip can then upgrade
Starlette past fastapi's supported range with only a warning (the
historical issue-#3 crash; see `core/dependency_guard.py`).
If a download times out, simply re-run the same `pip install` command —
completed wheels are cached and no user data is touched.

### Verify the environment (issue #3)

```bash
python -m pip check                                            # whole-environment consistency
python -m pytest tests/test_dependency_hygiene.py -q           # framework-pair regression checks
python -c "from api.server import app; print('engine imports OK')"
```

Importing `api` runs the runtime dependency guard: if the installed
FastAPI/Starlette/Streamlit trio is provably incompatible, you get an
actionable `RuntimeDependencyError` — not a cryptic `TypeError` deep
inside Starlette. `python cli.py serve` runs the same guard before
starting Uvicorn.

### Strict isolation alternative

If you prefer not to share one environment, install the engine and the
UI in **separate virtual environments** (engine: `requirements.txt` +
`requirements-dev.txt`; UI: `requirements-ui.txt` alone — Streamlit is
then free to pull whatever Starlette it needs). The Docker deployment
uses exactly this isolation by construction
([09-docker-deployment.md](09-docker-deployment.md)).

## Run

```bash
# 1. Start the engine (API on :8080, database at ./data/leads.db)
python cli.py serve

# 2. In another terminal, start the workspace (UI on :8501)
python cli.py ui
#    or: streamlit run ui/app.py
```

Open `http://localhost:8501` — the workspace talks to the engine at
`ENGINE_URL` (default `http://localhost:8080`).

Both commands preflight their dependencies: `serve` runs the runtime
dependency guard (issue #3), and `ui` additionally verifies the Streamlit
stack is fully installed (issue #24) — a partial install stops with the
missing components named and the remediation printed, never a raw
`ModuleNotFoundError` from inside Streamlit.

## Day-to-day commands

```bash
python cli.py discover -q "pharmacie" -w "Oran" -l 30   # one campaign via CLI
python cli.py analyze                                    # audit pending leads
python cli.py resolve                                    # entity resolution
python cli.py stats                                      # database statistics
python cli.py export -f csv                              # export leads
python cli.py bench                                      # engine benchmarks
```

## Tests & quality

```bash
python -m pytest tests/ -q          # full suite (unit + integration + API + geo + UI + hygiene + perf)
python -m pytest tests/test_ui.py -q        # frontend<->backend integration
ruff check .                         # lint (F/E9 selected)
python benchmarks/bench_engine.py    # CPU hot paths
python benchmarks/bench_storage.py   # storage + API throughput
```

## Project layout

```
api/          FastAPI routes + dependency graph
config/       settings, wilaya catalogue, dialect matrix, service catalog
core/         logging, exceptions
domain/       Lead / Checkpoint models, enums, value objects
engine/       analyzer, scorer, fastops kernel, geo + geodata, resolution/
infrastructure/ storage (SQLite + repos), scrapers, http, resilience
services/     discovery, resolution, crawler, export orchestration
ui/           Streamlit workspace (pure API client)
benchmarks/   engine + storage benchmarks
scripts/      geographic data acquisition + resilient environment setup
tests/        the verification suite
docs/         this documentation
docker/       per-service Dockerfiles (compose at repo root)
```

## Troubleshooting

See [13-troubleshooting.md](13-troubleshooting.md).
