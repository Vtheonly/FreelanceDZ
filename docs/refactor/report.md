# Final Comprehensive Engineering Blueprint: FreelanceDZ High-Performance Architecture

---

## 1. Chronological Conversation & Technical Reconstruction

This section establishes an unbroken record of every technical challenge, requirement, operational failure, architectural debate, and constraint introduced from the start of this project to the present.

### 1.1 Origin & Initial State (v4.0.0 Monolith)
* **Starting Context**: A B2B sales intelligence engine designed for the Algerian market across 58 wilayas.
* **Core Capabilities**: Lead discovery (DuckDuckGo, OpenStreetMap Overpass, SearXNG), deterministic auditing and scoring (no external LLM runtime dependency), entity resolution via Disjoint Set Union (DSU) and 3-bucket evidence scoring, geospatial polygon checking over 58 wilayas, and an interactive workspace.
* **Baseline Architecture**: A modular monolith written in Python (FastAPI backend on port 8080 + Streamlit frontend on port 8501) with SQLite WAL storage.
* **Original Commitments**: Complete deprecation of the legacy Jinja2 UI; replacement of the non-portable, uncompiled C++20 core with `fastops.py`; and strict enforcement that the UI must remain a pure client of the API.

### 1.2 The First Breakdown (Environment, Boot & Runtime Failures)
During initialization on clean machines, three cascading failures occurred:
1. **Network Read Timeout During Package Fetching**:
   * *Log Evidence*: `pip._vendor.urllib3.exceptions.ReadTimeoutError: HTTPSConnectionPool(host='files.pythonhosted.org', port=443): Read timed out.` while fetching the 10.4 MB Streamlit wheel.
   * *Direct Consequence*: `requirements-ui.txt` aborted midway, leaving the environment without Streamlit, Folium, or Pandas.
2. **Terminal Process Blocking & Command Chaining**:
   * *Symptom*: Running `python cli.py serve` followed immediately by `python cli.py ui` in a single command sequence caused the foreground Uvicorn server to block execution. The UI server never started.
3. **HTTP 404 on API Root (`/`)**:
   * *Log Evidence*: `INFO: 127.0.0.1:56424 - "GET / HTTP/1.1" 404 Not Found`.
   * *Cause*: The FastAPI engine is a headless JSON API. The root path (`/`) had no route registered because the old Jinja2 dashboard was removed, leaving developers with an uninformative 404 when testing the server via browser.

### 1.3 The Critical Architectural Audit
A deep-dive technical audit revealed severe gaps between architectural claims and production realities:
1. **The Ingestion Pipeline Desert**:
   * DuckDuckGo’s `html.duckduckgo.com` endpoint silently blocks or throttles un-proxied headless scrapers, yielding 0 results across search variants (`data/logs/deephuntr.log`).
   * Overpass API public servers frequently time out (25-second limit) on country-wide queries, rendering the OpenStreetMap scraper ineffective for broad discovery.
2. **The Self-Inflicted Directory Blacklist**:
   * `utils/spam_filter.py` explicitly placed `ouedkniss.com`, `elmouchir.caci.dz`, and `lespagesjaunes-algerie.com` into `EXACT_DOMAINS` blacklist. The scraper actively discarded the single largest structured repositories of verified Algerian business records, opting instead to search for informal mentions on general search engines.
3. **Inverted Opportunity Scoring Anomaly**:
   * The rule giving `+15` points for missing websites and `+10` points for missing addresses awarded high priority scores (75–80/100) to ghost records, spam snippets, or unregistered individuals who have no capacity or budget for commercial B2B services.
4. **Data Layout Cache Inefficiencies**:
   * The backend processed leads as large, heap-allocated Pydantic models containing arbitrary Python objects, nested dictionaries, and strings (Array of Structures — AoS). Iterating over thousands of these models caused severe L1/L2 cache thrashing.
5. **Streamlit Lifecycle Tax**:
   * Streamlit’s execution model re-runs the entire Python script from line 1 on every user click, forcing re-evaluation of UI code and re-serialization of data between Python and the browser DOM.

### 1.4 The Starlette Dependency Breakage
Following an instruction to install UI dependencies, a severe dependency collision occurred:
* *Terminal Output*: `pip` uninstalled `starlette-0.41.3` (required by `fastapi==0.115.6`) and installed `starlette-1.8.0` (pulled by `streamlit-1.66.0`).
* *Crash*:
  ```text
  File ".../api/routes/checkpoints.py", line 22, in <module>
    checkpoints_router = APIRouter(prefix="/api/v2/checkpoints", tags=["checkpoints"])
  TypeError: Router.__init__() got an unexpected keyword argument 'on_startup'
  ```
* *Root Cause*: Starlette 0.46+ permanently dropped the deprecated `on_startup` and `on_shutdown` parameters from `Router.__init__`. FastAPI 0.115.6 passed these arguments directly. Installing modern Streamlit in the same virtual environment broke the backend runtime.

### 1.5 Final Scope Consolidation & Strategic Directives
The user established the final set of constraints and goals:
1. **Preserve Streamlit and the Map**: Do not drop Streamlit. Do not swap it for Svelte, React, or HTMX. Retain the interactive Folium/Leaflet Algeria map. Make Streamlit fast, responsive, and robust within its native paradigm.
2. **Explore an Ambitious Engine Architecture**: Implement a decoupled, layered engine structure (Frontend $\to$ Core Compute Engine $\to$ Search Engine $\to$ Ingestion Worker) to demonstrate advanced systems engineering and benchmarking skills for a high-end portfolio.
3. **Challenge Assumptions & Prioritize Sound Engineering**: Avoid introducing architectural complexity without measuring its costs. Profile the serialization and network tax of distributed services.
4. **Strict Alignment with the Obsidian Vault**: Adhere directly to the principles of Memory Layout (Chapter 4.1), Work Elimination (Chapter 4.2), Hardware Limits (Chapter 4.3), SIMD/Vectorization (Chapter 4.4), Predictability (Chapter 4.5), and Domain Engines (Chapter 3).

---

## 2. Scope & Preservation of the Original Application

The original capabilities of FreelanceDZ must remain intact. Architectural enhancements must build around these components rather than replacing them.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        PRESERVED USER WORKSPACE                        │
├────────────────────────────────────────────────────────────────────────┤
│ • KPI Ribbon: Lead counts, average priority, contacts, wilaya stats    │
│ • Interactive Algeria Map: 58-wilaya GeoJSON rendering, click-to-filter│
│ • Field Checkpoints POI Manager: Lat/lon validation, CRUD, categories   │
│ • Campaign Launcher & Sourcing Queue: Query, wilaya, limit, progress   │
│ • Leads Matrix Table: Paginated, multi-filter, multi-select, bulk CRM  │
│ • Lead Inspector Drawer: Score breakdown, digital audit, attachments   │
│ • Engine Diagnostics: System health, crawler status, latency monitor   │
└────────────────────────────────────────────────────────────────────────┘
```

### 2.1 Preserved Functional Contracts
1. **Interactive Algeria Map**:
   * Renders real, versioned boundaries for all 58 wilayas (derived from Law 19-12 and OpenStreetMap ODbL data).
   * Map clicks trigger spatial resolution (`/api/v2/geo/lookup`) to filter the workspace by the selected wilaya.
   * Checkpoint markers and geolocated leads display as coordinate layers.
2. **Deterministic B2B Audit & Scoring**:
   * Evaluates digital presence across web, email, mobile phone, WhatsApp availability, and physical location.
   * Generates localized outreach copy in French (`cta_fr`) and Algerian Arabic (`cta_ar`).
   * Produces service recommendations with DZD-denominated budget estimates.
3. **Entity Resolution Pipeline**:
   * Groups duplicate listings across disparate channels into unified entities via DSU clustering.
   * Maintains decision logs, relation tracking (branches, chains, owners), and manual overrides (split/merge).
4. **Field Checkpoints (POI System)**:
   * Full CRUD operations for geographic checkpoints.
   * Coordinate validation against actual administrative boundaries (preventing misallocated wilayas).

---

## 3. Consolidated Architectural Vision & Service Topology

To balance Streamlit's constraints with the ambitious engine architecture from the Obsidian vault, the system adopts an **Asymmetric Multi-Engine Architecture**.

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                           PRESENTATION TIER (ISOLATED)                           │
│  Streamlit Workspace (ui/app.py)                                                 │
│  - Render Optimization: Isolated @st.fragment execution domains                 │
│  - Streamlined IPC: Session-cached GeoJSON, binary transfer, zero full-page runs │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │ HTTP 1.1 / orjson (Localhost:8080)
                                         ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                            CORE ENGINE & API GATEWAY                             │
│  FastAPI Runtime (api/server.py)                                                 │
│  - Hot Lead Working State: 64-byte Cache-Line Aligned NumPy SoA Array            │
│  - Spatial Engine: Precomputed 2D Bounding-Box Grid (O(1) Wilaya Lookup)         │
│  - Compute Kernels: Vectorized SIMD Opportunity Scoring, DSU Entity Resolution   │
└──────────────────┬────────────────────────────────────────────┬──────────────────┘
                   │ Candidate Stream (uint32 IDs)              │ Shared Storage
                   ▼                                            ▼
┌──────────────────────────────────────┐     ┌─────────────────────────────────────┐
│       SEARCH ENGINE SERVICE          │     │        INGESTION & PERSISTENCE      │
│  - Inverted Index & Term Postings    │     │  - Dual-Tier Storage: SQLite WAL    │
│  - WAND / MaxScore Dynamic Pruning   │     │    (Cold ACID) + Hot Arrow Memory   │
│  - Memory-Mapped Forward Index       │     │  - Targeted Workers: Ouedkniss,     │
│  - BM25 Scoring Kernel               │     │    SearXNG, CACI Directory Scrapers │
└──────────────────────────────────────┘     └─────────────────────────────────────┘
```

### 3.1 Streamlit Frontend Architecture
* **Isolation**: The frontend runs in an isolated Python environment (or container) with dedicated dependencies, decoupling its Starlette and Pydantic versions from the backend.
* **Component-Level Execution (`st.fragment`)**: Heavy UI blocks (Leads Table, Map Panel, Inspector) run inside isolated fragments. A click on a table row re-renders only the Lead Inspector, preventing the entire application from rerunning.
* **Map Optimization**: The 113 KB GeoJSON boundary file is transferred to the browser once and cached in `session_state`. Leaflet handles layer toggles and polygon highlights client-side. The Python layer receives only primitive coordinate payloads (`{"lat": float, "lon": float}`).

### 3.2 Core Processing Engine
* **Memory Model**: Implements the Structure of Arrays (SoA) layout detailed in Chapter 4.1. Hot fields (lead ID, coordinates, bitmask flags, priority score, digital health) live in contiguous flat arrays.
* **Compute Responsibilities**:
  * Vectorized priority scoring over active channel bitmasks.
  * Spatial lookups using bounding-box pre-filtering and localized ray-casting.
  * Graph-based entity resolution with DSU clustering.
* **Interface**: Operates as a compiled/in-memory Python service using `numpy` and `fastops`, exposed via FastAPI endpoints.

### 3.3 Dedicated Search Engine
* **Decoupled Retrieval Model**: Translates free-text search queries into document IDs using an inverted index (Chapter 3.2).
* **Index Structure**: Compressed posting lists mapping stemmed tokens to `uint32` document IDs.
* **Dynamic Pruning**: Employs the **WAND (Weak AND)** algorithm (Chapter 4.2.3) to terminate evaluation early once the top-$k$ candidates cannot be overtaken.
* **IPC Protocol**: Returns compact lists of matching `uint32` lead IDs to the Core Engine rather than serializing heavy lead objects.

### 3.4 Ingestion & Persistence Engine
* **Multi-Source Workers**: Targeted async workers extract structured data from Ouedkniss, CACI El Mouchir, and SearXNG.
* **Dual-Tier Storage Architecture**:
  * **Hot Tier**: Memory-mapped Apache Arrow record batches or NumPy arrays resident in RAM for instant reads ($<1\text{ ms}$).
  * **Cold Tier**: SQLite in WAL mode for ACID write-ahead logging, historical audits, notes, and raw JSON storage.

---

## 4. Performance Engineering Strategy & Vault Alignment

### 4.1 Mapping to Obsidian Vault Principles

```
┌──────────────────────────────────────┬────────────────────────────────────────────────────────┐
│ Vault Concept                        │ Implementation in FreelanceDZ                          │
├──────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ Ch 1.3: Iterative Loop vs Function   │ Engine runs continuous background ingestion and state  │
│                                      │ refinement rather than one-shot pipeline executions.   │
├──────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ Ch 2.2: State Representation Ceiling │ Conversion from Pydantic models (AoS) to a contiguous  │
│                                      │ 64-byte NumPy structured array (SoA) matching L1/L2.   │
├──────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ Ch 2.3: Multi-Stage Cascade          │ Search $\to$ Spatial BBox $\to$ Vectorized Score $\to$ │
│                                      │ Entity Resolution $\to$ Cold Details hydration.        │
├──────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ Ch 3.2: WAND Early Termination       │ Search index scores posting lists with dynamic score   │
│                                      │ bounding, skipping 90%+ of non-viable candidates.      │
├──────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ Ch 4.1: Cache-Line-Aware Structs     │ HotLead struct packed to exactly 64 bytes (1 cache     │
│                                      │ line), eliminating false sharing and memory waste.     │
├──────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ Ch 4.4: SIMD & Vectorization Batching│ Bitwise channel scoring implemented via vectorized     │
│                                      │ array operations rather than Python scalar loops.      │
├──────────────────────────────────────┼────────────────────────────────────────────────────────┤
│ Ch 5.3: Stateful Memory Management   │ Transposition-style caches for spatial lookup and DSU  │
│                                      │ clustering state, eliminating redundant computation.   │
└──────────────────────────────────────┴────────────────────────────────────────────────────────┘
```

### 4.2 Memory Layout: Array of Structures (AoS) vs. Structure of Arrays (SoA)

The original code stored leads in heap-allocated Pydantic models:
```text
[ Lead Object 1 ] ─── Pointer ───> [ Dict: gaps ]
                  ─── Pointer ───> [ Dict: score_breakdown ]
                  ─── Pointer ───> [ String: name ] (Scattered across heap)
```
Scanning 10,000 leads to filter by `wilaya == "Oran"` required walking pointer chains across gigabytes of memory, generating continuous L1/L2 cache misses (100 ns DRAM stalls).

The optimized layout separates hot primitives into a contiguous 64-byte structured array matching the CPU cache line:

```c
struct alignas(64) HotLead {
    uint32_t lead_id;         // 4 bytes: Database primary key
    uint8_t  wilaya_id;       // 1 byte:  Official code 1-58
    uint8_t  industry_id;     // 1 byte:  Categorical catalog enum
    uint16_t channel_flags;   // 2 bytes: Packed bitmask (Phone, Web, SSL, WhatsApp, etc.)
    float    latitude;        // 4 bytes: IEEE 754 32-bit float
    float    longitude;       // 4 bytes: IEEE 754 32-bit float
    float    priority_score;  // 4 bytes: Computed opportunity priority (0.0 - 100.0)
    uint8_t  digital_score;   // 1 byte:  Digital presence health (0 - 100)
    uint8_t  status_id;       // 1 byte:  CRM status enum
    uint8_t  is_contact;      // 1 byte:  Boolean flag
    uint8_t  padding[41];     // 41 bytes: Reserved alignment padding to exactly 64 bytes
};
```
* **Memory Footprint**: 100,000 leads require exactly **6.4 MB**, fitting comfortably within modern CPU L3 caches.
* **Scan Latency**: Filtering 100,000 leads down to 500 candidates runs via SIMD vector instructions in **under 250 microseconds**.

---

## 5. Critical Architectural Evaluation & Trade-Off Analysis

### 5.1 Decision 1: Keeping Streamlit vs. Dropping for a Custom SPA
* **Proposed Approach**: Keep Streamlit; isolate component execution via `@st.fragment`; strip Map data interchange down to click coordinates.
* **Intended Benefit**: Preserves the functional, Python-native workspace and avoids a full UI rewrite.
* **Technical Weaknesses**: Streamlit remains single-threaded per session. The Python-to-JavaScript bridge still introduces a 15–30 ms baseline delay on complex UI events.
* **Alternatives Considered**: FastHTML/HTMX (faster, pure Python) or SvelteKit SPA (native 60 FPS, zero Python UI overhead).
* **Final Engineering Decision**: **Keep Streamlit, but heavily optimize it.** The user explicitly mandated keeping Streamlit and the map. By applying `@st.fragment` and caching GeoJSON client-side, we eliminate 90% of the UI latency without breaking the existing interface.

### 5.2 Decision 2: Decoupled Search Engine Service vs. Monolithic Inverted Index
* **Proposed Approach**: Run a dedicated Search Engine service (`engine-search`) communicating with `engine-core` via localhost IPC.
* **Intended Benefit**: Demonstrates clean microservice decoupling and allows independent scaling of memory-intensive text retrieval.
* **Technical Weaknesses & Hidden Costs**: Network serialization overhead. If the search service returns full lead objects, JSON serialization burns 10–20 ms per request.
* **Alternatives Considered**: In-process inverted index module within the Core Engine.
* **Compromise Strategy**: **Implement the Search Engine as a decoupled service, but restrict its IPC contract to primitive arrays (`uint32[]` candidate IDs).** The search engine returns only matched document IDs. The Core Engine hydrates and scores those IDs directly from its in-memory SoA buffer. This provides microservice modularity while keeping network overhead under 0.5 ms.

### 5.3 Decision 3: Resolving the Python Dependency Collision
* **Proposed Approach**: Isolate the UI and the Backend into separate execution environments (independent virtual environments or Docker containers).
* **Intended Benefit**: Resolves the Starlette/FastAPI/Streamlit version collision cleanly without hacky workarounds.
* **Alternatives Considered**: Upgrading FastAPI to `0.115.11` to accept modern Starlette in a shared environment.
* **Final Engineering Decision**: **Dual-layer fix.** First, upgrade FastAPI to `>=0.115.8` to fix the local virtual environment immediately. Second, update the `docker-compose.yml` configuration so the `ui` and `engine` containers build from independent dependency manifests (`requirements.txt` vs. `requirements-ui.txt`), enforcing process-level and dependency-level isolation.

---

## 6. Comprehensive Task-by-Task Engineering Specifications

The 18 core engineering tasks below address every bug, performance bottleneck, architectural enhancement, and domain flaw identified across the system.

---

### Task 0.1: Environment Dependency De-confliction & Server Boot Restoration

1. **Task Identification & History**: Triggered by the Starlette 1.8.0 vs. FastAPI 0.115.6 version collision during UI setup.
2. **Problem Definition**: Uvicorn crashes on boot with `TypeError: Router.__init__() got an unexpected keyword argument 'on_startup'`.
3. **Current Implementation**: `requirements.txt` pins `fastapi==0.115.6`, which calls Starlette's deprecated `on_startup` hooks.
4. **Root-Cause Analysis**: `streamlit==1.66.0` pulls `starlette>=0.46.0` (installing `1.8.0`), which removed those arguments entirely.
5. **Desired Outcome**: Engine API boots cleanly on port 8080 without warnings or errors.
6. **Selected Solution**: Upgrade FastAPI to `>=0.115.8` in `requirements.txt`, which supports Starlette 0.46+. Isolate container builds so UI dependencies never bleed into backend images.
7. **Algorithms & Data Structures**: Standard packaging dependency resolution.
8. **Architectural Placement**: Build system, `pyproject.toml`, `requirements.txt`, `docker/`.
9. **Alternatives Considered**: Downgrading Streamlit (rejected: breaks map components and modern features).
10. **Performance Analysis**: Zero runtime cost; restores operational boot state.
11. **Dependencies**: None.
12. **Implementation Sequence**:
    * Edit `requirements.txt` to set `fastapi>=0.115.8`.
    * Run `pip install -r requirements.txt`.
    * Verify import of `api.server`.
13. **Testing Strategy**: Run `pytest tests/test_api.py`. Boot server via `python cli.py serve`.
14. **Acceptance Criteria**: `GET /health` returns status 200 and JSON `{"status": "ok"}`.
15. **Risks & Mitigations**: Potential minor API behavior shifts in FastAPI. Mitigate by running the existing 230-test suite.
16. **Final Engineering Decision**: Upgrade FastAPI in the primary manifest and enforce environment isolation in Docker.

---

### Task 0.2: Port 8080 Root Handling & Local Developer Guidance

1. **Task Identification & History**: Triggered by repeated `GET / HTTP/1.1 404 Not Found` logs in developer terminal sessions.
2. **Problem Definition**: Visiting `http://localhost:8080/` displays a raw 404 error, confusing developers expecting a dashboard.
3. **Current Implementation**: `api/server.py` defines routes under `/api/v2/` and `/health`, with no root route handler.
4. **Root-Cause Analysis**: Deprecation of the legacy Jinja2 dashboard removed `/` without adding a redirect or informative landing page.
5. **Desired Outcome**: Visiting `/` automatically redirects to interactive documentation (`/docs`) or displays a clear JSON route manifest.
6. **Selected Solution**: Add an explicit root route in `api/server.py` redirecting HTTP requests to `/docs`.
7. **Algorithms & Data Structures**: HTTP 307 Temporary Redirect response.
8. **Architectural Placement**: `api/server.py`.
9. **Alternatives Considered**: Serving static HTML (rejected: duplicates docs and violates headless API design).
10. **Performance Analysis**: Saves developer troubleshooting time; negligible overhead.
11. **Dependencies**: Task 0.1.
12. **Implementation Sequence**:
    * In `api/server.py`, add `@app.get("/", include_in_schema=False)`.
    * Return `RedirectResponse(url="/docs")`.
13. **Testing Strategy**: Query `GET /` with `TestClient` and assert a 307 redirect to `/docs`.
14. **Acceptance Criteria**: Browser navigating to `http://localhost:8080/` loads Swagger UI automatically.
15. **Risks & Mitigations**: None.
16. **Final Engineering Decision**: Implement root redirect to `/docs`.

---

### Task 1.1: Streamlit Fragment Isolation (`st.fragment`)

1. **Task Identification & History**: Follows from Section 1.5 & 3.1: Streamlit full-script rerun bottleneck.
2. **Problem Definition**: Every interaction (clicking a lead, updating a status, toggling a filter) re-executes the entire `ui/app.py` script.
3. **Current Implementation**: Global script flow calls panel render functions sequentially on every run.
4. **Root-Cause Analysis**: Streamlit's default execution model reruns the entire file on any session state update.
5. **Desired Outcome**: User interactions within a panel re-render only that panel. Global reruns occur only on explicit navigation or filter resets.
6. **Selected Solution**: Decorate isolated panels (`render_leads_matrix`, `render_lead_inspector`, `render_checkpoints_panel`) with `@st.fragment`.
7. **Algorithms & Data Structures**: Granular UI execution domains.
8. **Architectural Placement**: `ui/components/leads_table.py`, `ui/components/lead_detail.py`, `ui/components/checkpoints.py`.
9. **Alternatives Considered**: Migrating away from Streamlit (explicitly rejected by user).
10. **Performance Analysis**: Drops interactive response times from 400–1200 ms to under 50 ms.
11. **Dependencies**: Task 0.1.
12. **Implementation Sequence**:
    * Audit each component function for global state mutations.
    * Wrap self-contained rendering logic in `@st.fragment`.
    * Ensure inter-panel communication uses `st.session_state` keys without triggering global reruns.
13. **Testing Strategy**: Manual verification in browser; automated testing using Streamlit's `AppTest` harness asserting local element updates.
14. **Acceptance Criteria**: Interacting with the Leads Table updates the DOM without re-rendering the Map or KPI Ribbon.
15. **Risks & Mitigations**: Stale state across fragments. Mitigate by using shared session state keys and selective invalidation.
16. **Final Engineering Decision**: Wrap all secondary panels in `@st.fragment`.

---

### Task 1.2: Folium Map Serialization & Geometry Caching

1. **Task Identification & History**: Section 1.5: Map latency and browser-Python payload thrashing.
2. **Problem Definition**: Clicking a wilaya triggers a heavy data exchange, sending the entire 113 KB GeoJSON structure back to Python.
3. **Current Implementation**: `st_folium(m, return_on_click=True)` returns all map state, layers, and objects.
4. **Root-Cause Analysis**: `streamlit-folium` defaults to returning every map object unless explicitly restricted.
5. **Desired Outcome**: Map interactions transmit only the click coordinates (`lat`, `lon`), executing in $<15\text{ ms}$.
6. **Selected Solution**: Pass `returned_objects=["last_clicked"]` to `st_folium`. Cache the rendered Folium Map object in `st.session_state`.
7. **Algorithms & Data Structures**: Client-side coordinate serialization; session-level singleton map instance.
8. **Architectural Placement**: `ui/components/algeria_map.py`.
9. **Alternatives Considered**: Replacing Folium with PyDeck (rejected: PyDeck doesn't support the same click-to-polygon selection without complex layer hacking).
10. **Performance Analysis**: Eliminates 113 KB of JSON parsing per map click; network payload drops to $<100\text{ bytes}$.
11. **Dependencies**: Task 0.1, Task 1.1.
12. **Implementation Sequence**:
    * Refactor `render_map()` in `ui/components/algeria_map.py`.
    * Cache boundary geometry using `@st.cache_data`.
    * Restrict `st_folium` returned objects to `["last_clicked"]`.
13. **Testing Strategy**: Assert payload size in browser developer tools; test coordinate resolution with `AppTest`.
14. **Acceptance Criteria**: Clicking a polygon triggers an immediate filter update without map flickering.
15. **Risks & Mitigations**: Map zoom/pan resetting on rerun. Mitigate by storing center/zoom in `st.session_state`.
16. **Final Engineering Decision**: Restrict `st_folium` return payload and cache map assets.

---

### Task 1.3: Asynchronous Non-Blocking Discovery UX

1. **Task Identification & History**: Section 3.1: UI freeze during discovery execution.
2. **Problem Definition**: Launching a discovery campaign blocks the UI thread if executed synchronously.
3. **Current Implementation**: Background task option exists, but the UI lacks an isolated live progress monitor.
4. **Root-Cause Analysis**: Lack of dedicated progress streaming back to Streamlit without full script reruns.
5. **Desired Outcome**: Discovery campaigns run entirely in the background while Streamlit displays a live, polling progress indicator that does not block the map or tables.
6. **Selected Solution**: Build a discovery progress fragment using `@st.fragment(run_every=2)` that queries `/api/v2/discover/campaigns` every 2 seconds until complete.
7. **Algorithms & Data Structures**: Polling loop wrapped in a UI fragment.
8. **Architectural Placement**: `ui/components/discovery.py`.
9. **Alternatives Considered**: WebSockets (unstable inside native Streamlit components without custom plugins).
10. **Performance Analysis**: Frees the main UI thread completely; zero impact on browsing, map navigation, or CRM operations.
11. **Dependencies**: Task 1.1.
12. **Implementation Sequence**:
    * Create `_render_campaign_tracker()` wrapped in `@st.fragment(run_every=2)`.
    * Query active campaigns; refresh only the progress bar and status text.
13. **Testing Strategy**: Trigger discovery campaign; verify map remains fully interactive while progress updates.
14. **Acceptance Criteria**: Campaign progresses from 0% to 100% smoothly without user interaction interrupts.
15. **Risks & Mitigations**: Excessive polling load on the backend. Mitigate by setting a minimum 2-second polling interval.
16. **Final Engineering Decision**: Implement dedicated `@st.fragment` polling for active discovery tasks.

---

### Task 2.1: Spam Filter Re-Classification (Directory Unblocking)

1. **Task Identification & History**: Section 1.3 & 1.5: The self-inflicted data desert.
2. **Problem Definition**: High-value business directories (`Ouedkniss`, `CACI El Mouchir`, `Pages Jaunes DZ`) are permanently blacklisted as spam.
3. **Current Implementation**: `utils/spam_filter.py` includes these domains in `EXACT_DOMAINS`.
4. **Root-Cause Analysis**: Original author conflated generic SEO aggregators (Cybo, Yelp) with local commercial marketplaces.
5. **Desired Outcome**: Commercial directory domains are recognized as structured data sources and routed to targeted parsers.
6. **Selected Solution**: Remove legitimate business directories from `EXACT_DOMAINS`. Add an `ALLOWED_DIRECTORIES` set in `config/` and create dedicated extraction rules.
7. **Algorithms & Data Structures**: Hash set lookup for domain classification.
8. **Architectural Placement**: `utils/spam_filter.py`, `config/settings.py`.
9. **Alternatives Considered**: Scraping directories through generic DuckDuckGo search snippets (rejected: low accuracy, missing phone numbers).
10. **Performance Analysis**: Unlocks thousands of verified local commercial entities.
11. **Dependencies**: None.
12. **Implementation Sequence**:
    * Edit `utils/spam_filter.py`.
    * Remove `ouedkniss.com`, `ouedkniss.fr`, `elmouchir.caci.dz`, `lespagesjaunes-algerie.com` from `EXACT_DOMAINS`.
    * Update unit tests in `tests/test_spam_filter.py`.
13. **Testing Strategy**: Run `pytest tests/test_spam_filter.py` asserting Ouedkniss store URLs return `is_spam() == False`.
14. **Acceptance Criteria**: Legitimate directory links pass through the quality gate while aggregators remain blocked.
15. **Risks & Mitigations**: Scraper ingesting directory search pages instead of store profiles. Mitigate via URL path pattern matching.
16. **Final Engineering Decision**: Unblock verified Algerian commercial directories.

---

### Task 2.2: Dedicated Ouedkniss Store Scraper Engine

1. **Task Identification & History**: Section 1.5: Ingestion pipeline overhaul.
2. **Problem Definition**: The engine cannot reliably discover informal businesses that operate exclusively on Algerian marketplaces.
3. **Current Implementation**: System relies on generic DuckDuckGo web results.
4. **Root-Cause Analysis**: Lack of a dedicated adapter for Algeria's largest commercial trading platform.
5. **Desired Outcome**: An asynchronous crawler that ingests Ouedkniss store profiles, extracting business name, phone, wilaya, address, and category.
6. **Selected Solution**: Implement `OuedknissScraper` conforming to the `Scraper` protocol in `infrastructure/scrapers/ouedkniss.py`.
7. **Algorithms & Data Structures**: DOM extraction via BeautifulSoup/Fastops regex; phone normalization via `SmartPhoneValidator`.
8. **Architectural Placement**: `infrastructure/scrapers/ouedkniss.py`.
9. **Alternatives Considered**: Selenium/Playwright headless browsing (rejected: heavy resource overhead; Ouedkniss store profiles render initial state in static HTML/JSON).
10. **Performance Analysis**: Generates 20–50 verified leads per category query with near 100% phone and wilaya fill rates.
11. **Dependencies**: Task 2.1.
12. **Implementation Sequence**:
    * Create `infrastructure/scrapers/ouedkniss.py`.
    * Implement search query URL construction and store profile extraction.
    * Register scraper in `api/dependencies.py` within `ScraperAggregator`.
13. **Testing Strategy**: Mock HTTP responses of Ouedkniss store pages; verify field extraction and phone validation.
14. **Acceptance Criteria**: Querying `pharmacie` or `climatisation` yields structured leads from Ouedkniss with verified Algerian mobile numbers.
15. **Risks & Mitigations**: Site markup changes. Mitigate by extracting structured JSON-LD or Next.js `__NEXT_DATA__` state payloads when present.
16. **Final Engineering Decision**: Implement dedicated Ouedkniss store scraper.

---

### Task 2.3: SearXNG Primary Gateway Integration

1. **Task Identification & History**: Section 1.3 & 1.5: Replacing fragile DDG scraping.
2. **Problem Definition**: DuckDuckGo blocks direct requests from data-center or local IPs within minutes.
3. **Current Implementation**: SearXNG scraper exists but is optional and inactive by default.
4. **Root-Cause Analysis**: Architecture treated metasearch as secondary rather than primary infrastructure.
5. **Desired Outcome**: All general web search discovery flows through a local SearXNG container via clean JSON APIs.
6. **Selected Solution**: Enable SearXNG by default in `docker-compose.yml`. Configure `DiscoveryService` to prioritize SearXNG over raw DDG HTML scraping.
7. **Algorithms & Data Structures**: HTTP JSON client with token-bucket rate limiting.
8. **Architectural Placement**: `docker-compose.yml`, `config/settings.py`, `infrastructure/scrapers/searxng.py`.
9. **Alternatives Considered**: Commercial proxy rotation services (rejected: adds external costs for a portfolio project).
10. **Performance Analysis**: Eliminates anti-bot blocks; reduces SERP parsing time from 2.5 seconds to 350 ms.
11. **Dependencies**: None.
12. **Implementation Sequence**:
    * Update `docker-compose.yml` to remove the `profiles: ["searxng"]` gate.
    * Set default `SEARXNG_URL=http://searxng:8080` in `.env.example`.
    * Update `api/dependencies.py` to position SearXNG as the primary web scraper.
13. **Testing Strategy**: Integration test with local SearXNG instance asserting structured lead generation.
14. **Acceptance Criteria**: Discovery campaigns return results reliably without triggering HTTP 429 or CAPTCHA errors.
15. **Risks & Mitigations**: SearXNG container memory usage. Mitigate by configuring minimal engine plugins (Google, Bing, Brave only).
16. **Final Engineering Decision**: Make local SearXNG the default search provider.

---

### Task 2.4: Asynchronous Bounded Ingestion Queue

1. **Task Identification & History**: Vault Chapter 1.3: Iterative loop and decoupled ingestion.
2. **Problem Definition**: Discovery scrapers write directly to SQLite during network fetching, causing write lock contention with API requests.
3. **Current Implementation**: `DiscoveryService` calls `repo.upsert()` sequentially inside the scraper streaming loop.
4. **Root-Cause Analysis**: Tight coupling between I/O-bound network workers and transaction-bound storage.
5. **Desired Outcome**: Scrapers push to an in-memory queue; a dedicated background task batches database insertions.
6. **Selected Solution**: Implement an `asyncio.Queue` buffer. Ingestion drains the queue in batches of 50 leads using atomic multi-row upserts.
7. **Algorithms & Data Structures**: Thread-safe FIFO bounded queue; SQLite multi-row `INSERT ... ON CONFLICT DO UPDATE`.
8. **Architectural Placement**: `services/discovery_service.py`, `infrastructure/storage/lead_repo.py`.
9. **Alternatives Considered**: Celery / Redis queue (rejected: unnecessary operational bloat for single-node execution).
10. **Performance Analysis**: Reduces SQLite transaction frequency by 90%, preventing database lock errors during heavy discovery runs.
11. **Dependencies**: None.
12. **Implementation Sequence**:
    * Add `_ingest_queue = asyncio.Queue(maxsize=1000)` to `DiscoveryService`.
    * Implement `_batch_persistence_worker()` running as an async background task.
    * Flush remaining items upon campaign completion.
13. **Testing Strategy**: Run high-concurrency ingestion test; assert zero `sqlite3.OperationalError: database is locked` errors.
14. **Acceptance Criteria**: 500 leads persist smoothly while simultaneous UI read queries execute without latency spikes.
15. **Risks & Mitigations**: Data loss on ungraceful process termination. Mitigate by setting a 1-second maximum queue flush timeout.
16. **Final Engineering Decision**: Implement in-memory bounded batch ingestion.

---

### Task 3.1: Dedicated Inverted Index & Posting Lists (Search Engine)

1. **Task Identification & History**: Vault Chapter 3.2: High-Scale Text Search Engines & Section 3.3.
2. **Problem Definition**: SQLite FTS5 table scans require reading disk pages and parsing virtual table B-trees on every filter change.
3. **Current Implementation**: Full-text queries execute via SQL: `SELECT rowid FROM leads_fts WHERE leads_fts MATCH ?`.
4. **Root-Cause Analysis**: Reliance on generic database extensions rather than an in-memory inverted index for the search tier.
5. **Desired Outcome**: In-memory inverted index providing sub-millisecond term matching and posting list lookups across all leads.
6. **Selected Solution**: Build an in-memory `InvertedIndex` in `engine/search/index.py` storing sorted `uint32` posting lists.
7. **Algorithms & Data Structures**:
   * Dictionary mapping token hashes (`uint64`) to contiguous arrays of lead IDs (`np.ndarray[uint32]`).
   * Elias-Fano or delta-compressed posting arrays for maximum cache compression (Chapter 3.2.1).
8. **Architectural Placement**: `engine/search/index.py`.
9. **Alternatives Considered**: Running an external Elasticsearch container (rejected: burns 1 GB+ RAM and introduces heavy JSON network hops).
10. **Performance Analysis**: Memory footprint for 100,000 documents: $\approx 2.4\text{ MB}$. Term lookup latency: $<50\text{ }\mu\text{s}$.
11. **Dependencies**: Task 2.4.
12. **Implementation Sequence**:
    * Create `engine/search/index.py`.
    * Implement token extraction, normalization, and posting list registration.
    * Implement index synchronization hook on lead creation/updates.
13. **Testing Strategy**: Unit tests indexing 10,000 documents; verify exact document matching and posting list correctness.
14. **Acceptance Criteria**: Term queries return correct matching lead IDs in under $100\text{ }\mu\text{s}$.
15. **Risks & Mitigations**: Memory growth with vocabulary size. Mitigate by applying frequency thresholds (prune rare/junk tokens).
16. **Final Engineering Decision**: Build a dedicated in-memory inverted index.

---

### Task 3.2: BM25 Scoring Kernel with WAND Early Termination

1. **Task Identification & History**: Vault Chapter 3.2.2 & 4.2.3: BM25 relevance and WAND pruning.
2. **Problem Definition**: Scoring every document in a long posting list wastes CPU cycles on documents that cannot rank in the top-$k$.
3. **Current Implementation**: SQLite FTS5 rank scoring calculates full BM25 for all matching rows.
4. **Root-Cause Analysis**: Lack of dynamic score bounding and candidate pruning.
5. **Desired Outcome**: BM25 scoring with **WAND (Weak AND)** early termination, evaluating only viable candidates.
6. **Selected Solution**: Implement WAND traversal in `engine/search/retrieval.py`. Precompute maximum term score contributions ($U_t$) and skip documents whose upper-bound score cannot beat the running top-$k$ threshold.
7. **Algorithms & Data Structures**:
   $$\text{MaxScore}(d) = \sum_{t \in Q} U_t < \theta \implies \text{Skip } d$$
   Priority queue (min-heap) maintaining the top-$k$ scores.
8. **Architectural Placement**: `engine/search/retrieval.py`.
9. **Alternatives Considered**: Naive full posting list scoring (rejected: $O(N)$ with respect to matches).
10. **Performance Analysis**: 10x to 50x reduction in document evaluations for multi-term queries.
11. **Dependencies**: Task 3.1.
12. **Implementation Sequence**:
    * Implement BM25 formula with parameters $k_1 = 1.2, b = 0.75$.
    * Implement WAND algorithm maintaining candidate heap.
    * Add unit tests verifying top-$k$ parity with exhaustive scoring.
13. **Testing Strategy**: Benchmark WAND versus brute-force BM25 on synthetic 100,000-document posting lists.
14. **Acceptance Criteria**: Produces identical top-$k$ results to exhaustive scoring while evaluating $<15\%$ of total matching documents.
15. **Risks & Mitigations**: Floating-point inaccuracy in thresholding. Mitigate by using small epsilon tolerances in upper bounds.
16. **Final Engineering Decision**: Implement BM25 with WAND early termination.

---

### Task 3.3: Search Engine Candidate ID Protocol

1. **Task Identification & History**: Vault Chapter 2.3 & Section 5.2: Service decoupling without serialization tax.
2. **Problem Definition**: Cross-service communication returning full lead dictionaries over HTTP creates severe JSON serialization latency.
3. **Current Implementation**: Backend API endpoints serialize full lead records with all metadata.
4. **Root-Cause Analysis**: Treating search retrieval as an end-to-end presentation endpoint rather than a candidate generator.
5. **Desired Outcome**: Search Engine returns only compact arrays of `uint32` document IDs.
6. **Selected Solution**: Expose `GET /api/v2/search/candidates?q=...&limit=...` returning a raw JSON array of integers (`[12, 45, 991]`) using `orjson`.
7. **Algorithms & Data Structures**: Compact integer array serialization.
8. **Architectural Placement**: `api/routes/leads.py` (or dedicated search route).
9. **Alternatives Considered**: Protobuf / gRPC (rejected: requires extra compilation tools; `orjson` serializing flat integer lists takes $<0.2\text{ ms}$).
10. **Performance Analysis**: Payload size for 1,000 candidates drops from 850 KB to 4 KB; network transfer time drops to $<0.3\text{ ms}$.
11. **Dependencies**: Task 3.2.
12. **Implementation Sequence**:
    * Add `/candidates` route to search engine router.
    * Integrate with WAND retrieval kernel.
    * Wire Core Engine client to consume candidate ID streams.
13. **Testing Strategy**: Measure serialization and deserialization times for 1,000 candidate IDs across localhost.
14. **Acceptance Criteria**: 1,000 candidates retrieved and deserialized in $<1\text{ ms}$ total round-trip time.
15. **Risks & Mitigations**: Mismatched IDs between Search and Core. Mitigate by using the SQLite database primary key as the universal ID.
16. **Final Engineering Decision**: Restrict search IPC to primitive integer candidate IDs.

---

### Task 4.1: Hot/Cold State Decoupling (64-Byte SoA NumPy Array)

1. **Task Identification & History**: Vault Chapter 2.2, 4.1: State representation ceiling and Structure of Arrays.
2. **Problem Definition**: Heap-allocated Pydantic models cause pointer chasing and cache misses during lead filtering and scoring.
3. **Current Implementation**: `LeadRepository.list_leads()` builds and filters Pydantic `Lead` instances.
4. **Root-Cause Analysis**: Array of Structures (AoS) object modeling in the engine's hot read path.
5. **Desired Outcome**: An in-memory, contiguous, 64-byte aligned structured array storing all hot attributes for up to 200,000 leads.
6. **Selected Solution**: Implement `HotLeadArray` using NumPy structured arrays in `engine/state.py`.
7. **Algorithms & Data Structures**:
   * Contiguous memory buffer matching hardware cache line boundaries (64 bytes).
   * Bit-packed integer fields for categorical and boolean flags.
8. **Architectural Placement**: `engine/state.py`, loaded into FastAPI `app.state.hot_leads`.
9. **Alternatives Considered**: In-process DuckDB (viable, but NumPy provides zero-overhead in-memory slicing and direct SIMD interop).
10. **Performance Analysis**: 100,000 leads reside in 6.4 MB (L3 cache resident). Filtering by Wilaya + Status takes $<150\text{ }\mu\text{s}$.
11. **Dependencies**: Task 0.1.
12. **Implementation Sequence**:
    * Define `HOT_LEAD_DTYPE` with 64-byte alignment padding.
    * Implement `HotLeadState` manager with insert, update, and slice methods.
    * Populate state from SQLite at startup during FastAPI `lifespan`.
13. **Testing Strategy**: Assert memory alignment with `hot_array.ctypes.data % 64 == 0`. Test filter operations across 100,000 synthetic records.
14. **Acceptance Criteria**: Memory consumption verified at $\le 6.4\text{ MB}$ per 100k records; multi-field filtering executes in $<1\text{ ms}$.
15. **Risks & Mitigations**: Keeping memory synchronized with SQLite writes. Mitigate by wrapping all write operations in a write-through repository hook.
16. **Final Engineering Decision**: Implement contiguous 64-byte SoA state array for hot attributes.

---

### Task 4.2: Vectorized Batch Opportunity Scoring

1. **Task Identification & History**: Vault Chapter 4.4: Vectorized Processing & Section 1.3: Scoring calibration.
2. **Problem Definition**: Python scalar loops in `LeadScorer` score leads one by one. The scoring formula awards points to invalid ghost records.
3. **Current Implementation**: `engine/scorer.py` loops over leads, evaluating Python dictionaries and bitwise operators.
4. **Root-Cause Analysis**: Scalar interpretation overhead and flawed opportunity incentives.
5. **Desired Outcome**: Vectorized scoring across the hot NumPy array executing at $>10\text{M leads/second}$, with calibrated commercial logic.
6. **Selected Solution**: Implement `score_hot_array()` in `engine/fastops.py` using vectorized NumPy array operations.
7. **Algorithms & Data Structures**:
   * Vectorized bitmask operations on `uint16 channel_flags`.
   * Calibrated scoring logic:
     $$\text{Opportunity} = (\text{has\_phone} \lor \text{has\_address}) \times [(\neg \text{has\_web}) \times 15.0 + (\neg \text{has\_geo}) \times 10.0]$$
     *(Businesses with no phone and no address receive 0 opportunity points).*
8. **Architectural Placement**: `engine/fastops.py`.
9. **Alternatives Considered**: Cython / C extensions (rejected: NumPy achieves native C vectorization without compilation complexity).
10. **Performance Analysis**: Scores 100,000 leads in $<10\text{ ms}$ (vs. 102 ms previously).
11. **Dependencies**: Task 4.1.
12. **Implementation Sequence**:
    * Write vectorized calculation functions in `engine/fastops.py`.
    * Update `engine/scorer.py` to route batch scoring through the vectorized kernel.
    * Update unit tests asserting that empty/ghost leads do not receive high opportunity scores.
13. **Testing Strategy**: Run `pytest tests/test_fastops.py` and execute `benchmarks/bench_engine.py`.
14. **Acceptance Criteria**: Vectorized scoring throughput exceeds $10,000,000\text{ leads/sec}$; ghost leads score $\le 30/100$.
15. **Risks & Mitigations**: Numerical parity differences with single-lead scoring. Mitigate by asserting exact parity in unit tests.
16. **Final Engineering Decision**: Deploy vectorized NumPy scoring kernel with recalibrated opportunity logic.

---

### Task 4.3: Precomputed 2D Spatial Grid Index (Morton BBox Pruning)

1. **Task Identification & History**: Vault Chapter 4.2: Work elimination & Section 1.1: Geospatial engine optimization.
2. **Problem Definition**: Point-in-polygon ray-casting tests every coordinate against all polygon vertices, wasting CPU cycles on interior points.
3. **Current Implementation**: `engine/geo.py` iterates through bounding boxes, then casts rays across exterior rings.
4. **Root-Cause Analysis**: Lack of spatial binning to provide $O(1)$ short-circuit lookups for points deep inside a wilaya.
5. **Desired Outcome**: Point-in-wilaya lookups exceed $500,000\text{ lookups/sec}$ by resolving 90%+ of queries in $O(1)$ time.
6. **Selected Solution**: Precompute a $0.05^\circ \times 0.05^\circ$ (~5 km) 2D lookup grid covering Algeria. Cells entirely enclosed by a single wilaya return its ID immediately. Ambiguous boundary cells fall back to ray-casting.
7. **Algorithms & Data Structures**:
   * Precomputed 2D integer array (`wilaya_grid[lat_idx, lon_idx]`).
   * Values: `1-58` for interior points, `0` for ambiguous border cells requiring ray-casting.
8. **Architectural Placement**: `engine/geo.py`.
9. **Alternatives Considered**: Full R-Tree via `rtree` library (rejected: introduces heavy C library dependencies; flat 2D grid is faster for fixed geographic boundaries).
10. **Performance Analysis**: Increases spatial lookup throughput from 39,600/s to $>500,000/\text{s}$.
11. **Dependencies**: None.
12. **Implementation Sequence**:
    * In `engine/geo.py`, implement `_build_spatial_grid()`, executed once on startup.
    * Modify `WilayaGeoService.lookup(lon, lat)` to check the grid before running `_point_in_ring()`.
13. **Testing Strategy**: Run 100,000 random lookups across Algeria; assert identical classification results to pure ray-casting.
14. **Acceptance Criteria**: Over 85% of queries short-circuit in $O(1)$; benchmark throughput exceeds $500,000\text{ lookups/sec}$.
15. **Risks & Mitigations**: Grid memory footprint. At $0.05^\circ$ resolution, grid requires $\approx 360 \times 400 = 144,000\text{ bytes}$ ($144\text{ KB}$), easily fitting in L2 cache.
16. **Final Engineering Decision**: Implement precomputed 2D spatial grid index.

---

### Task 4.4: Integer-Indexed DSU Entity Resolution

1. **Task Identification & History**: Vault Chapter 3.1 & 5.3: Disjoint Set Union and stateful memoization.
2. **Problem Definition**: Entity resolution compares and logs string attributes repeatedly across candidate pairs.
3. **Current Implementation**: `engine/resolution/` builds `RecordFeatures` and compares string representations.
4. **Root-Cause Analysis**: String comparisons and allocations during pair scoring inside `EntityResolver.resolve()`.
5. **Desired Outcome**: Entity resolution executes on compact integer IDs, phone hashes, and pre-tokenized bitsets, doubling resolution speed.
6. **Selected Solution**: Intern tokens into integer IDs; compare bitsets and precomputed hashes in `comparators.py`.
7. **Algorithms & Data Structures**: DSU (Disjoint Set Union) with path compression, rank union, and must-not-link constraints.
8. **Architectural Placement**: `engine/resolution/`.
9. **Alternatives Considered**: Replacing DSU with graph libraries like NetworkX (rejected: NetworkX is orders of magnitude slower and allocates heavy Python node objects).
10. **Performance Analysis**: Resolves 5,000 candidate pairs in $<50\text{ ms}$.
11. **Dependencies**: Task 4.1.
12. **Implementation Sequence**:
    * Profile `engine/resolution/resolver.py` to identify hot comparison functions.
    * Replace string equality checks with token ID checks.
    * Retain all multi-bucket scoring logic, conflict penalties, and human review queue mechanisms.
13. **Testing Strategy**: Run `pytest tests/test_resolution.py` to assert 100% decision and cluster parity.
14. **Acceptance Criteria**: Cluster output matches previous implementation identically while cutting runtime in half.
15. **Risks & Mitigations**: Subtle behavior changes in string metrics. Mitigate with regression testing against existing test fixtures.
16. **Final Engineering Decision**: Optimize DSU resolution pipeline with integer token interning.

---

### Task 5.1: Containerized Multi-Service Topology

1. **Task Identification & History**: Section 3 & User Directive: Explore incremental microservices via Docker.
2. **Problem Definition**: Running all services in a single Python environment creates dependency collisions and prevents independent process profiling.
3. **Current Implementation**: Two containers: `engine` and `ui`, with SearXNG optional.
4. **Root-Cause Analysis**: Monolithic packaging of disparate functional concerns.
5. **Desired Outcome**: Decoupled, containerized topology separating UI, Core Engine, Search Engine, and SearXNG with explicit health checks and resource limits.
6. **Selected Solution**: Configure `docker-compose.yml` with four isolated services: `ui`, `engine-core`, `engine-search`, and `searxng`.
7. **Algorithms & Data Structures**: Docker Compose v2 specification; health-gated startup dependencies.
8. **Architectural Placement**: `docker-compose.yml`, `docker/`.
9. **Alternatives Considered**: Kubernetes / Nomad (rejected: massive overengineering for a single-host application).
10. **Performance Analysis**: Enforces memory caps (e.g., Search Engine capped at 512 MB, Core Engine at 1.5 GB); isolates crashes.
11. **Dependencies**: Task 0.1, Task 3.3, Task 4.1.
12. **Implementation Sequence**:
    * Write `docker/search.Dockerfile`.
    * Update `docker-compose.yml` to define all four services.
    * Configure internal network `fdz-net` and volume mounts for SQLite WAL files.
13. **Testing Strategy**: Run `docker compose up --build`; verify all containers report healthy.
14. **Acceptance Criteria**: All four containers start cleanly, pass healthchecks, and communicate without port collisions.
15. **Risks & Mitigations**: Increased local resource usage. Mitigate by setting explicit CPU and RAM limits in `docker-compose.yml`.
16. **Final Engineering Decision**: Implement clean four-container service topology.

---

### Task 5.2: Low-Latency High-Throughput Inter-Service IPC

1. **Task Identification & History**: Vault Chapter 7.5 & Section 5.2: Zero-copy and serialization minimization.
2. **Problem Definition**: Standard Python `json.dumps()` in FastAPI introduces significant latency on large list responses.
3. **Current Implementation**: Standard FastAPI endpoints use default Pydantic / JSON encoders.
4. **Root-Cause Analysis**: Inefficient serialization libraries and redundant JSON parsing in intermediate hops.
5. **Desired Outcome**: Inter-service serialization takes $<0.3\text{ ms}$ for lists of 1,000 items.
6. **Selected Solution**: Replace standard JSON encoding with `orjson` across all FastAPI routers and clients using `ORJSONResponse`.
7. **Algorithms & Data Structures**: SIMD-accelerated C-Rust JSON serialization via `orjson`.
8. **Architectural Placement**: `api/server.py`, `ui/api_client.py`.
9. **Alternatives Considered**: Custom binary protocol (rejected: added complexity not justified when `orjson` serializes 1,000 IDs in microseconds).
10. **Performance Analysis**: 4x to 10x faster serialization; reduced API endpoint latency.
11. **Dependencies**: Task 5.1.
12. **Implementation Sequence**:
    * Install `orjson`.
    * Set `default_response_class=ORJSONResponse` in FastAPI app factory (`api/server.py`).
    * Use `orjson.loads()` inside `ui/api_client.py`.
13. **Testing Strategy**: Benchmark endpoint serialization times using `httpx` and `orjson`.
14. **Acceptance Criteria**: JSON serialization time for 1,000 records drops below $500\text{ }\mu\text{s}$.
15. **Risks & Mitigations**: `orjson` handling of non-standard types (e.g. UUID, datetime). Mitigate by configuring `default=str` fallback.
16. **Final Engineering Decision**: Standardize on `orjson` for all inter-service communication.

---

### Task 5.3: End-to-End Latency Budget & Distributed Instrumentation

1. **Task Identification & History**: Vault Chapter 3.1.4: Latency measurement & Section 3.
2. **Problem Definition**: No objective measurement exists to quantify the performance overhead introduced by splitting services.
3. **Current Implementation**: Single `/health` latency probe in UI diagnostics.
4. **Root-Cause Analysis**: Lack of fine-grained timestamping across request lifecycles.
5. **Desired Outcome**: Precise breakdown of time spent in each layer: UI render, network transit, search retrieval, core scoring, and database reads.
6. **Selected Solution**: Implement a lightweight request-timing middleware that injects `Server-Timing` headers into HTTP responses and surfaces them in the Streamlit diagnostics panel.
7. **Algorithms & Data Structures**: Monotonic nanosecond clock (`time.perf_counter_ns()`).
8. **Architectural Placement**: `api/server.py`, `ui/components/diagnostics.py`.
9. **Alternatives Considered**: OpenTelemetry / Jaeger (rejected: heavy dependencies and complex infrastructure for a portfolio project).
10. **Performance Analysis**: Measures latency accurately with $<2\text{ }\mu\text{s}$ measurement overhead.
11. **Dependencies**: Task 5.2.
12. **Implementation Sequence**:
    * Add timing middleware to FastAPI in `api/server.py`.
    * Include `Server-Timing: search;dur=1.2, score;dur=0.4` headers.
    * Parse and display these timing breakdowns in `ui/components/diagnostics.py`.
13. **Testing Strategy**: Verify `Server-Timing` headers exist on API responses and correctly render in UI diagnostics.
14. **Acceptance Criteria**: UI diagnostics panel shows exact millisecond breakdown for each stage of request processing.
15. **Risks & Mitigations**: None.
16. **Final Engineering Decision**: Implement `Server-Timing` instrumentation across all backend services.

---

### Task 6.1: Comparative Micro-Benchmarking Suite

1. **Task Identification & History**: Vault Chapter 6.4: Profiling-Driven Micro-Optimization & Section 4.
2. **Problem Definition**: Inability to prove to technical recruiters and clients that optimizations produced measurable gains.
3. **Current Implementation**: Basic script in `benchmarks/bench_engine.py` measuring raw regex and SQLite throughput.
4. **Root-Cause Analysis**: Lack of structured, comparative before-and-after benchmarks.
5. **Desired Outcome**: An automated benchmark suite demonstrating performance differences between naive and optimized implementations.
6. **Selected Solution**: Build `benchmarks/bench_comparative.py` that runs side-by-side benchmarks across four key operations:
   * SQLite FTS scan vs. Dedicated Inverted Index + WAND.
   * Scalar Python loop scoring vs. Vectorized NumPy SoA scoring.
   * Brute-force ray-casting vs. Precomputed 2D BBox grid lookup.
   * Monolithic in-process call vs. Decoupled containerized IPC call.
7. **Algorithms & Data Structures**: Statistical benchmarking harness computing iterations, p50, p95, p99, and memory consumption.
8. **Architectural Placement**: `benchmarks/bench_comparative.py`.
9. **Alternatives Considered**: Running benchmarks manually in Jupyter notebooks (rejected: not reproducible or version-controlled).
10. **Performance Analysis**: Provides verifiable proof of engineering claims.
11. **Dependencies**: Tasks 3.2, 4.2, 4.3, 5.2.
12. **Implementation Sequence**:
    * Implement synthetic data generator for 100,000 leads.
    * Write benchmark functions for each comparison pair.
    * Format output as clean Markdown tables.
13. **Testing Strategy**: Execute benchmark script in CI/test runner.
14. **Acceptance Criteria**: Script runs cleanly, outputs reproducible latency numbers, and documents performance deltas.
15. **Risks & Mitigations**: CPU frequency scaling introducing noise. Mitigate by taking median values over multiple iterations.
16. **Final Engineering Decision**: Build automated comparative benchmarking suite.

---

### Task 6.2: Engineering Portfolio Documentation & Architectural Case Study

1. **Task Identification & History**: User Core Objective: Demonstrating elite software engineering skills to land freelance clients.
2. **Problem Definition**: The documentation previously read like generic marketing copy rather than a rigorous engineering case study.
3. **Current Implementation**: Basic markdown docs in `docs/` describing high-level features.
4. **Root-Cause Analysis**: Documentation described *what* the system does rather than *why* architectural decisions were made and *how* trade-offs were measured.
5. **Desired Outcome**: A technical README and architectural whitepaper documenting system design, trade-offs, and empirical benchmarks.
6. **Selected Solution**: Rewrite `README.md` and create `docs/SYSTEM_DESIGN_CASE_STUDY.md`.
7. **Algorithms & Data Structures**: Technical documentation incorporating Mermaid diagrams and benchmark tables.
8. **Architectural Placement**: `README.md`, `docs/`.
9. **Alternatives Considered**: None.
10. **Performance Analysis**: High portfolio impact; showcases senior systems thinking.
11. **Dependencies**: Task 6.1.
12. **Implementation Sequence**:
    * Document the 6-layer engine mapping.
    * Detail the microservices trade-off analysis and the IPC serialization tax.
    * Include empirical benchmark results.
13. **Testing Strategy**: Review for clarity, technical precision, and absence of buzzword fluff.
14. **Acceptance Criteria**: README presents a defensible, well-benchmarked systems architecture.
15. **Risks & Mitigations**: None.
16. **Final Engineering Decision**: Author definitive system design case study.

---

## 7. Implementation Roadmap & Execution Sequencing

The execution order follows strict dependency gating: **Foundational Correctness $\to$ Core Compute Optimization $\to$ Search Decoupling $\to$ UI Surgery $\to$ Distribution & Benchmarking**.

```
[Phase 0: Environment Rescue]
  ├── Task 0.1: Fix Starlette/FastAPI/Streamlit version collision
  └── Task 0.2: Add root redirect to /docs
         │
         ▼
[Phase 1: Ingestion & Data Quality]
  ├── Task 2.1: Unblock Ouedkniss & CACI in spam filter
  ├── Task 2.2: Implement Ouedkniss store scraper
  ├── Task 2.3: Set SearXNG as default search gateway
  └── Task 2.4: Asynchronous bounded ingestion queue
         │
         ▼
[Phase 2: Core Engine Optimization]
  ├── Task 4.1: Hot/Cold state separation (64-byte SoA NumPy array)
  ├── Task 4.2: Vectorized batch scoring kernel
  ├── Task 4.3: Precomputed 2D spatial grid index
  └── Task 4.4: Integer-indexed DSU entity resolution
         │
         ▼
[Phase 3: Search Engine Service]
  ├── Task 3.1: In-memory inverted index & posting lists
  ├── Task 3.2: BM25 scoring with WAND early termination
  └── Task 3.3: Candidate ID IPC protocol (uint32 streaming)
         │
         ▼
[Phase 4: Streamlit & Map Performance Surgery]
  ├── Task 1.1: Panel isolation with @st.fragment
  ├── Task 1.2: Restrict Folium map return payload to click coords
  └── Task 1.3: Background discovery progress tracking
         │
         ▼
[Phase 5: Container Topology & IPC Instrumentation]
  ├── Task 5.1: Multi-service docker-compose orchestration
  ├── Task 5.2: orjson IPC integration
  └── Task 5.3: Server-Timing latency instrumentation
         │
         ▼
[Phase 6: Benchmarking & Portfolio Packaging]
  ├── Task 6.1: Automated comparative benchmark suite
  └── Task 6.2: System design case study & technical README
```

---

## 8. Measurable Performance Targets & Verification Baselines

All optimization tasks are tied to verifiable metrics:

| Metric | Measurement Tool | Baseline (Current) | Target (Optimized) | Verification Method |
| :--- | :--- | :--- | :--- | :--- |
| **Hot Filter Scan (100k records)** | `benchmarks/bench_engine.py` | 150 ms (SQLite JSON scan) | **$<1.0\text{ ms}$** | Filter by wilaya + score over NumPy SoA array |
| **Scoring Throughput** | `benchmarks/bench_engine.py` | 978,000 leads/sec | **$>10,000,000\text{ leads/sec}$** | Vectorized bitmask math execution |
| **Point-in-Wilaya Lookup** | `benchmarks/bench_engine.py` | 39,600 lookups/sec | **$>500,000\text{ lookups/sec}$** | 2D BBox grid lookup with boundary ray-cast |
| **Search Retrieval (100k docs)** | `benchmarks/bench_engine.py` | 45 ms (FTS5 match) | **$<2.0\text{ ms}$** | Inverted index + WAND dynamic pruning |
| **Search IPC Transfer (1k IDs)** | Network benchmark | 18 ms (full JSON objects) | **$<0.5\text{ ms}$** | `orjson` serialization of `uint32[]` list |
| **Map Click Latency** | Browser DevTools / Timer | 450–1,100 ms | **$<30\text{ ms}$** | `st.fragment` isolated rerun execution |
| **Lead Inspector Render** | Streamlit AppTest | 350–800 ms | **$<25\text{ ms}$** | Row selection re-rendering only detail panel |
| **Discovery Fill-Rate (Phone/Wilaya)**| Pipeline log inspection | $<20\%$ (DDG generic) | **$>90\%$** | Targeted Ouedkniss & CACI ingestion |
| **Engine RAM (100k records)** | `psutil` process monitor | ~180 MB (Pydantic models) | **$<15\text{ MB}$** | Packed 64-byte SoA contiguous array |

---

## 9. Requirements Traceability Matrix

This matrix maps every conversational requirement, bug, and design directive to its dedicated task, architectural placement, and verification strategy:

| Original Requirement / Issue | Addressed In | Implementation Component | Verification Method |
| :--- | :--- | :--- | :--- |
| **FastAPI/Starlette collision crash** | Task 0.1 | `requirements.txt`, packaging | Server boots cleanly without `TypeError` |
| **Port 8080 404 confusion** | Task 0.2 | `api/server.py` | Browser visiting `/` redirects to `/docs` |
| **Preserve Streamlit frontend** | Task 1.1 | `ui/app.py`, `ui/components/` | Streamlit remains primary UI framework |
| **Preserve 58-wilaya interactive map**| Task 1.2 | `ui/components/algeria_map.py` | Map remains interactive; renders boundaries |
| **Make Streamlit fast & responsive** | Task 1.1, 1.2 | `ui/` (@st.fragment, caching) | Sub-50ms UI response on panel interaction |
| **Fix DDG scraper blocking (0 leads)**| Task 2.3 | `infrastructure/scrapers/searxng.py` | Discovery returns leads consistently |
| **Overpass API timeout failures** | Task 2.3 | `searxng`, `overpass.py` fallback | Web campaigns proceed even if Overpass stalls |
| **Unblock Algerian directories** | Task 2.1, 2.2 | `utils/spam_filter.py`, scrapers | Ouedkniss store links pass quality gate |
| **Calibrate opportunity scoring** | Task 4.2 | `engine/fastops.py`, `engine/scorer.py` | Empty ghost leads do not receive high scores |
| **Hardware-Aware Memory Layout (SoA)**| Task 4.1 | `engine/state.py` | Contiguous 64-byte aligned HotLead array |
| **Vectorized batch scoring** | Task 4.2 | `engine/fastops.py` | Vectorized NumPy math $>10\text{M leads/sec}$ |
| **Accelerate spatial wilaya lookups** | Task 4.3 | `engine/geo.py` | Precomputed 2D grid $>500\text{k lookups/sec}$ |
| **Dedicated Search Engine Service** | Task 3.1, 3.2 | `engine/search/` | Inverted index + WAND $<2\text{ ms}$ latency |
| **Low-overhead candidate IPC** | Task 3.3, 5.2 | API route, `orjson` | Candidate stream payload $<5\text{ KB}$, $<0.5\text{ ms}$ |
| **Containerized Microservices** | Task 5.1 | `docker-compose.yml` | 4 isolated services communicating cleanly |
| **Demonstrate Systems Benchmarking** | Task 5.3, 6.1 | `benchmarks/bench_comparative.py` | Automated comparative latency benchmark suite |
| **Professional Portfolio Packaging** | Task 6.2 | `README.md`, `docs/` | System design case study with real trade-offs |

---

## 10. Final Engineering Directive & Approval Gate

1. **Strictly Python**: All implementations use clean, idiomatic, high-performance Python 3.12 (`fastapi`, `numpy`, `uvloop`, `orjson`, `streamlit`, `httpx`). No external C/Rust toolchains are introduced.
2. **Preservation of Core Identity**: Streamlit, Leaflet/Folium map rendering, DSU entity resolution, and the 58-wilaya boundary system remain the foundation of the product.
3. **No Phantom Code**: Implementation will begin strictly task-by-task starting with **Phase 0** upon your approval.