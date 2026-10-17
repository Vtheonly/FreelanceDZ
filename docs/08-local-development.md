# 08 · Local Development

## Prerequisites

- Python 3.10+ (3.12 recommended)
- pip

## Setup (five commands)

```bash
git clone https://github.com/Vtheonly/FreelanceDZ.git
cd FreelanceDZ
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-ui.txt -r requirements-dev.txt
cp .env.example .env            # optional: adjust to taste
```

Install all requirement files **in one command** so pip resolves the
shared pins together (see the note in `requirements-ui.txt`).

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
scripts/      geographic data acquisition
tests/        the verification suite
docs/         this documentation
docker/       per-service Dockerfiles (compose at repo root)
```

## Troubleshooting

See [13-troubleshooting.md](13-troubleshooting.md).
