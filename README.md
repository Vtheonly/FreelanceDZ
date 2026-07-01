# DZ Sales Intelligence

An AI-powered **business discovery and lead intelligence platform** built specifically for the Algerian market. It crawls public online sources (OpenStreetMap, DuckDuckGo, local directories), analyzes each business's digital gaps using free-tier LLM APIs (Groq / OpenRouter), and outputs prioritized sales leads for software development services.

---

## Key Features

| Capability | Description |
|---|---|
| Multi-source discovery | OpenStreetMap Overpass API + DuckDuckGo search + mock fallback |
| 58-wilaya coverage | Built-in catalogue of all Algerian wilayas (with codes) |
| Industry templates | 50+ Algerian business categories with default software gaps |
| Free LLM analysis | Groq / OpenRouter with disk cache + exponential backoff |
| Lead scoring (0–100) | Multi-factor: digital gaps, activity, deal size, industry |
| SQLite persistence | Local, serverless, low-RAM storage |
| REST dashboard | FastAPI + Jinja2 dashboard to browse/search leads |
| CLI | Click-based CLI: `discover`, `analyze`, `export`, `stats`, `serve` |
| Docker | Single-container deployment under 200 MB RAM |

---

## Architecture

```
+------------------+      +------------------+      +------------------+
|   Scrapers       | ---> |   LLM Analyzer   | ---> |   Lead Scorer    |
| (Overpass / DDG  |      | (Groq / OpenRtr  |      | (Multi-factor)   |
|  / Mock)         |      |  with cache)     |      |                  |
+------------------+      +------------------+      +------------------+
        |                          |                          |
        v                          v                          v
+------------------------------------------------------------------------+
|              Prospecting Pipeline (services/pipeline.py)               |
+------------------------------------------------------------------------+
                                  |
                                  v
                      +-----------------------+
                      |  SQLite Repository    |
                      |  (data/leads.db)      |
                      +-----------------------+
                                  |
              +-------------------+-------------------+
              v                                       v
    +-------------------+                  +--------------------+
    |  CLI (click)      |                  |  FastAPI Dashboard |
    +-------------------+                  +--------------------+
```

Clean architecture / domain-driven design:

- **`domain/`** – pure Pydantic models & exceptions (no I/O).
- **`core/`** – abstract interfaces (contracts).
- **`infrastructure/`** – concrete adapters (scrapers, LLM clients, SQLite repo).
- **`services/`** – orchestration & business logic (pipeline, scorer).
- **`config/`** – settings + static catalogues (wilayas, industries, services).
- **`api/`** – optional FastAPI dashboard.
- **`cli.py`** – entry point.

---

## Quick Start

### 1. Configure

```bash
cp .env.example .env
# Edit .env and add your LLM_API_KEY (Groq or OpenRouter)
```

### 2. Run with Docker

```bash
docker-compose up --build
# In another shell, run commands:
docker exec -it dz_sales_intel python cli.py discover --query "restaurant" --wilaya "Algiers" --limit 20
docker exec -it dz_sales_intel python cli.py analyze
docker exec -it dz_sales_intel python cli.py stats
docker exec -it dz_sales_intel python cli.py serve  # Start dashboard on :8080
```

### 3. Run locally (without Docker)

```bash
pip install -r requirements.txt
python cli.py discover --query "pharmacie" --wilaya "Oran" --limit 10
python cli.py analyze
python cli.py export --format csv --out ./data/exports/leads.csv
python cli.py serve
```

Open the dashboard at <http://localhost:8080>.

---

## CLI Reference

| Command | Description |
|---|---|
| `discover --query Q --wilaya W --limit N` | Crawl sources and persist raw businesses |
| `analyze [--force]` | Run LLM analysis on un-analyzed leads |
| `score` | Recompute lead priority scores |
| `export --format {csv,json,md} --out PATH` | Export leads to file |
| `stats` | Show database statistics |
| `top --n 20` | Show top-N prioritized leads |
| `serve [--host 0.0.0.0 --port 8080]` | Launch FastAPI dashboard |
| `pipeline --query Q --limit N` | Full run: discover → analyze → score |

---

## Free-Tier Rate-Limit Safety

- All LLM calls pass through a disk cache (`data/cache/llm/`) keyed by `hash(business + prompt)`.
- Exponential backoff on HTTP 429 (1s → 2s → 4s → 8s).
- Configurable base delay (`RATE_LIMIT_DELAY_SECONDS`).
- Graceful fallback: if all LLM retries fail, a rule-based heuristic generates a usable `LeadAnalysis` so the pipeline never crashes.

---

## Extending the Platform

### Add a new scraper

1. Create `infrastructure/scrapers/my_source.py`
2. Subclass `core.interfaces.IScraper`
3. Register it in `infrastructure/scrapers/aggregator.py`

### Add a new LLM provider

1. Create `infrastructure/llm/my_provider.py`
2. Subclass `core.interfaces.ILLMClient`
3. Register it in `infrastructure/llm/factory.py`

### Add a new industry template

Edit `config/industries.py` and append an entry to `INDUSTRY_TEMPLATES`.

---

## Project Layout

```
.
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── README.md
├── cli.py
├── main.py
├── config/
│   ├── settings.py
│   ├── wilayas.py
│   ├── industries.py
│   └── services_catalog.py
├── domain/
│   ├── models.py
│   └── exceptions.py
├── core/
│   ├── interfaces.py
│   └── logging_setup.py
├── infrastructure/
│   ├── scrapers/
│   │   ├── base.py
│   │   ├── overpass.py
│   │   ├── duckduckgo.py
│   │   ├── mock.py
│   │   └── aggregator.py
│   ├── llm/
│   │   ├── base.py
│   │   ├── groq_client.py
│   │   ├── openrouter_client.py
│   │   ├── factory.py
│   │   ├── cache.py
│   │   └── prompts.py
│   └── storage/
│       ├── schema.sql
│       └── sqlite_repo.py
├── services/
│   ├── pipeline.py
│   ├── scorer.py
│   └── analyzer.py
└── api/
    ├── server.py
    └── templates/dashboard.html
```

---

## License

MIT — use freely for commercial and personal projects.
