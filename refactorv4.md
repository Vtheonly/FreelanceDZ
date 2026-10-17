
Here is the complete, prioritized engineering breakdown. Every task is categorized, with **exact implementation instructions**, **concrete code changes**, and **precise testing strategies** to verify it works.

---

## SECTION 1: Critical Dashboard & API Contract Fixes (Immediate)

These 5 bugs are what caused the crashes and errors in your terminal and browser console.

---

### Task 1: Fix Invisible Search Queue (`campaigns.length` Bug)
* **The Problem:** `GET /api/v2/discover/campaigns` returns `{ "campaigns": [...] }` (an object). `dashboard.html` checks `if (!campaigns.length)`. Since an object has no `.length` property, it evaluates to `undefined` (falsy), immediately overwriting the queue container with `"No active campaigns"` every 3 seconds.
* **File to modify:** `api/templates/dashboard.html`
* **How to Implement:**
  In `dashboard.html`, update `pollCampaigns()`:
  ```javascript
  async function pollCampaigns() {
      try {
          const r = await fetch(API + '/discover/campaigns');
          const data = await r.json();
          const campaigns = Array.isArray(data) ? data : (data.campaigns || []);
          const container = document.getElementById('campaignsRows');
          if (!campaigns.length) {
              container.innerHTML = `<div class="empty-state" style="padding: 10px;">No active campaigns.</div>`;
              return;
          }
          container.innerHTML = campaigns.map(c => {
              const date = new Date(c.created_at).toLocaleTimeString();
              let statusIcon = '';
              let statusText = c.status;
              if (c.status === 'processing') {
                  statusIcon = '<span class="spinner" style="width:10px; height:10px; margin-right:5px;"></span> ';
                  statusText = `<span style="color: var(--accent-glow)">active</span>`;
              } else if (c.status === 'completed') {
                  statusIcon = '<span style="color: var(--accent-emerald)">✓</span> ';
                  statusText = `<span style="color: var(--accent-emerald)">done (+${c.saved_count})</span>`;
              } else if (c.status === 'failed') {
                  statusIcon = '<span style="color: var(--accent-rose)">✗</span> ';
                  statusText = `<span style="color: var(--accent-rose)">failed</span>`;
              }
              return `<div class="metadata-row" style="border-bottom: 1px solid var(--border-primary); padding-bottom: 6px; margin-bottom: 6px;">
                  <span class="metadata-label">${statusIcon}<strong>${escapeHtml(c.query)}</strong> ${c.wilaya ? '(' + escapeHtml(c.wilaya) + ')' : ''}</span>
                  <span class="metadata-value" style="font-size: 10px;">${statusText} <span style="color: var(--text-muted); font-size:9px;">[${date}]</span></span>
              </div>`;
          }).join('');
      } catch (e) { /* silent */ }
  }
  ```
* **How to Test:**
  1. Open DevTools in the browser.
  2. Launch a search from the top bar (e.g. `pharmacie`).
  3. The right-hand sidebar under "Active Sourcing Queue" must immediately show the query with a spinning loader and change to `done (+N)` once completed, without disappearing.

---

### Task 2: Fix Stats Crash (`(data.age_breakdown || []).filter is not a function`)
* **The Problem:** Backend returns `"age_breakdown": {"day": 5, "hour": 2}` (a dictionary). Frontend expects an array and calls `.filter()`, crashing every 15 seconds.
* **File to modify:** `api/templates/dashboard.html`
* **How to Implement:**
  In `dashboard.html`, update `loadStats()`:
  ```javascript
  async function loadStats() {
      try {
          const r = await fetch(API + '/stats');
          const data = await r.json();
          document.getElementById('statTotal').textContent = data.total_leads ?? 0;
          document.getElementById('statAnalysed').textContent = data.analyzed_leads ?? 0;
          document.getElementById('statAvgScore').textContent = (data.average_score ?? 0).toFixed(1);
          document.getElementById('statEntities').textContent = data.total_resolved_entities ?? 0;
          
          // Handles both object: {"day": 5} and array: [{age_class: "day", count: 5}]
          let fresh = 0;
          if (Array.isArray(data.age_breakdown)) {
              fresh = data.age_breakdown
                  .filter(a => ['hour', 'day'].includes(a.age_class))
                  .reduce((s, a) => s + (a.count || 0), 0);
          } else if (typeof data.age_breakdown === 'object' && data.age_breakdown !== null) {
              fresh = (data.age_breakdown.hour || 0) + (data.age_breakdown.day || 0);
          }
          document.getElementById('statFresh').textContent = fresh;
      } catch (e) { console.error('stats failed', e); }
  }
  ```
* **How to Test:**
  Open browser console on `http://localhost:8080/`. Confirm that `stats failed TypeError` never appears again.

---

### Task 3: Fix 404 Route on Tags
* **The Problem:** Frontend calls `/api/v2/tags`. The backend endpoint is mounted at `/api/v2/leads/tags`.
* **File to modify:** `api/templates/dashboard.html`
* **How to Implement:**
  Change line 445 from:
  ```javascript
  const r = await fetch(API + '/tags');
  ```
  to:
  ```javascript
  const r = await fetch(API + '/leads/tags');
  ```
* **How to Test:**
  Refresh dashboard. Inspect the terminal log: `GET /api/v2/tags 404 Not Found` must be replaced by `GET /api/v2/leads/tags 200 OK`.

---

### Task 4: Fix 422 Unprocessable Entity on Empty Wilaya
* **The Problem:** When the user leaves the Wilaya field blank, the browser sends `wilaya: ""`. The Pydantic validator runs `sanitise_query("")`, which throws `ValueError("Query cannot be empty.")`, generating an HTTP 422.
* **File to modify:** `api/routes/misc.py`
* **How to Implement:**
  Replace `_sanitise` validator in `DiscoverRequest`:
  ```python
  class DiscoverRequest(BaseModel):
      query: str = Field(min_length=2, max_length=200)
      wilaya: Optional[str] = Field(None, max_length=100)
      limit: int = Field(default=30, ge=1, le=200)
      background: bool = False

      @field_validator("query")
      @classmethod
      def _sanitise_query(cls, v: str) -> str:
          return sanitise_query(v)

      @field_validator("wilaya")
      @classmethod
      def _sanitise_wilaya(cls, v: Optional[str]) -> Optional[str]:
          if not v or not v.strip():
              return None
          return sanitise_query(v.strip())
  ```
* **How to Test:**
  Submit a search on the dashboard with `Query = "ecole"` and `Wilaya = ""` (blank). It must return `200 OK`, not `422 Unprocessable Entity`.

---

### Task 5: Unify Search and List Endpoints (Fix Dropped Filters)
* **The Problem:** When typing in the search bar, the UI switches to `/api/v2/leads/search`, which only takes `q` and `limit`. All other parameters (`wilaya`, `is_contact`, `sort_by`, `offset`) are discarded.
* **Files to modify:** `api/routes/leads.py`, `dashboard.html`
* **How to Implement:**
  1. In `api/routes/leads.py`, update `list_leads` to accept an optional `q: Optional[str] = Query(None)` parameter:
     ```python
     @router.get("/leads")
     async def list_leads(
         q: Optional[str] = Query(None),
         wilaya: Optional[str] = Query(None),
         industry: Optional[str] = Query(None),
         status: Optional[str] = Query(None),
         is_contact: Optional[bool] = Query(None),
         tag: Optional[str] = Query(None),
         age_class: Optional[str] = Query(None),
         min_score: float = Query(0.0, ge=0.0, le=100.0),
         sort_by: str = Query("priority_score"),
         sort_order: str = Query("desc"),
         limit: int = Query(50, ge=1, le=500),
         offset: int = Query(0, ge=0),
         repo: LeadRepository = Depends(get_lead_repo),
     ):
         leads = await repo.list_leads(
             q=q, wilaya=wilaya, industry=industry, status=status, is_contact=is_contact,
             tag=tag, age_class=age_class, min_score=min_score,
             sort_by=sort_by, sort_order=sort_order, limit=limit, offset=offset,
         )
         return {"count": len(leads), "leads": [_lead_summary(l) for l in leads]}
     ```
  2. In `infrastructure/storage/lead_repo.py`, add FTS filtering inside `list_leads`:
     ```python
     if q and q.strip():
         phrase = fts_sanitize(q.strip())
         if phrase:
             clauses.append("leads.id IN (SELECT rowid FROM leads_fts WHERE leads_fts MATCH ?)")
             params.append(phrase)
     ```
  3. In `dashboard.html`, change `loadLeads()`:
     ```javascript
     // Remove: if (search) url = API + '/leads/search?...'
     // Always use:
     let url = API + '/leads?' + params.toString();
     ```
* **How to Test:**
  Filter by `Wilaya = "Oran"`, then type a name in the search box. Confirm both the name search and the wilaya filter remain active together.

---

### Task 6: Eliminate Database Race Condition in `LeadRepository.upsert`
* **The Problem:** `_execute` runs a `SELECT`, then `INSERT`. Two concurrent tasks cause a crash with `sqlite3.IntegrityError: UNIQUE constraint failed: leads.fingerprint`.
* **File to modify:** `infrastructure/storage/lead_repo.py`
* **How to Implement:**
  Rewrite `upsert` using native SQLite atomic `ON CONFLICT` with `RETURNING id`:
  ```python
  def _execute() -> tuple[int, bool]:
      with self._db.connection() as conn:
          cursor = conn.execute(
              """
              INSERT INTO leads (
                  fingerprint, name, industry, wilaya, address, website, phone, email,
                  social_links, rating, review_count, latitude, longitude, source, source_url,
                  phone_details, freshness, digital_score, digital_tier, gaps,
                  recommended_services, cta_fr, cta_ar, analysis_model, priority_score,
                  score_breakdown, status, tags, is_contact, notes, discovered_at, updated_at
              ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
              ON CONFLICT(fingerprint) DO UPDATE SET
                  address = COALESCE(excluded.address, leads.address),
                  website = COALESCE(excluded.website, leads.website),
                  phone = COALESCE(excluded.phone, leads.phone),
                  email = COALESCE(excluded.email, leads.email),
                  social_links = CASE WHEN excluded.social_links != '[]' THEN excluded.social_links ELSE leads.social_links END,
                  phone_details = CASE WHEN excluded.phone_details != '[]' THEN excluded.phone_details ELSE leads.phone_details END,
                  digital_score = COALESCE(excluded.digital_score, leads.digital_score),
                  digital_tier = COALESCE(excluded.digital_tier, leads.digital_tier),
                  priority_score = MAX(excluded.priority_score, leads.priority_score),
                  updated_at = excluded.updated_at
              RETURNING id, (created_at = updated_at) AS is_new;
              """,
              (...params...)
          )
          row = cursor.fetchone()
          if row:
              return row[0], bool(row[1])
          return 0, False
  ```
* **How to Test:**
  Run `asyncio.gather(*[repo.upsert(identical_lead) for _ in range(50)])`. It must complete with 0 exceptions and return the same ID for all 50 calls.

---

### Task 7: Fix Stored XSS in Link Rendering
* **The Problem:** `dashboard.html` renders `<a href="${lead.website}">`. A scraped URL starting with `javascript:` will execute arbitrary code in the browser when clicked.
* **File to modify:** `api/templates/dashboard.html`
* **How to Implement:**
  Add a URL sanitizer function in JavaScript:
  ```javascript
  function safeUrl(url) {
      if (!url) return '';
      const clean = url.trim();
      if (/^(https?:|\/\/)/i.test(clean)) {
          return clean;
      }
      return '#';
  }
  ```
  Update every anchor in `dashboard.html`:
  ```javascript
  `<a href="${safeUrl(lead.website)}" class="app-link" target="_blank" rel="noopener noreferrer">${escapeHtml(lead.website)}</a>`
  ```
* **How to Test:**
  Create a lead with `website = "javascript:alert(1)"`. Click "Visit Website" on the dashboard. It must navigate to `#` and execute nothing.

---

## SECTION 2: Decoupling OpenStreetMap & Intelligent Geo-Inference

---

### Task 8: Decouple OpenStreetMap as an Asymmetric Oracle
* **The Problem:** The engine treats map nodes and online listings as conflicting definitions of a business, or relies on map entries for wilaya verification.
* **Files to modify:** `infrastructure/scrapers/overpass.py`, `services/discovery_service.py`
* **How to Implement:**
  1. In `infrastructure/scrapers/overpass.py`, remove the rule that skips queries without a wilaya:
     Allow Overpass to run as an optional asynchronous background enrichment job.
  2. In `services/discovery_service.py`, set:
     ```python
     # OSM failure MUST NOT stop web discovery
     try:
         osm_leads = await overpass_scraper.discover(...)
     except Exception:
         osm_leads = [] # Silent degradation
     ```
* **How to Test:**
  Turn off internet connection to Overpass servers (e.g. block `overpass-api.de` in `/etc/hosts`). Run a search. The engine must continue finding leads from DDG/Web without failure.

---

### Task 9: Implement Telephony Area Code Wilaya Inference
* **The Problem:** When businesses exist online (Facebook/Instagram/Web) with a landline but no map pin and no address, their Wilaya is marked as unknown.
* **File to create:** `utils/geo_inference.py`
* **How to Implement:**
  ```python
  ALGERIAN_LANDLINE_AREA_CODES = {
      "021": "Alger", "023": "Alger", "024": "Boumerdès", "025": "Blida",
      "026": "Tizi Ouzou", "027": "Chlef", "029": "Ghardaïa",
      "041": "Oran", "043": "Tlemcen", "045": "Mostaganem", "046": "Mascara",
      "048": "Relizane", "049": "Béchar",
      "031": "Constantine", "032": "Oum El Bouaghi", "033": "Batna",
      "034": "Béjaïa", "035": "Bordj Bou Arréridj", "036": "Sétif",
      "037": "Guelma", "038": "Annaba",
  }

  def infer_wilaya_from_phone(e164_or_national: str) -> str | None:
      clean = "".join(c for c in e164_or_national if c.isdigit())
      if clean.startswith("213"):
          clean = "0" + clean[3:]
      if len(clean) >= 3:
          prefix3 = clean[:3]
          if prefix3 in ALGERIAN_LANDLINE_AREA_CODES:
              return ALGERIAN_LANDLINE_AREA_CODES[prefix3]
      return None
  ```
  Integrate this into `DuckDuckGoScraper._result_to_lead`:
  ```python
  if not lead.wilaya and lead.phone:
      inferred = infer_wilaya_from_phone(lead.phone)
      if inferred:
          lead.wilaya = inferred
  ```
* **How to Test:**
  Feed a snippet: `"Contactez notre bureau au 041 33 22 11"`. Assert that `lead.wilaya == "Oran"`.

---

### Task 10: Invert the Map-Absence Scoring Penalty
* **The Problem:** `engine/scorer.py` awards 10 points for address and GPS coordinates. Businesses without websites and without map pins are penalised, even though they represent the highest-value prospects for web design and local SEO.
* **File to modify:** `engine/scorer.py`
* **How to Implement:**
  Update `LeadScorer.explain()` and scoring arithmetic:
  ```python
  # Instead of penalizing missing address/geo:
  # Award "Local Presence Gap" bonus to opportunity deficit
  if not lead.address and lead.latitude is None:
      factors["local_seo_opportunity"] = 10.0  # Needs Google Business Profile & Map presence
  if not lead.website:
      factors["website_build_opportunity"] = 15.0 # Needs primary website
  ```
* **How to Test:**
  Score a lead with verified phone but no website and no map coordinates. Assert its score is $\ge 60/100$, prioritized for digital presence setup.

---

## SECTION 3: Scraper Throughput & Bottleneck Elimination

---

### Task 11: Kill the Sequential Dialect Multiplier Bomb
* **The Problem:** Expanding a query into 11 variants runs 11 sequential searches $\times$ 3 pages $\times$ jitter delays, forcing users to wait over 60 seconds per search.
* **File to modify:** `services/discovery_service.py`
* **How to Implement:**
  In `services/discovery_service.py`:
  ```python
  async def stream(self, query: str, wilaya: Optional[str] = None, limit: int = 30):
      # Pick only TOP 2 variants (Primary + Arabic/Darja equivalent)
      all_variants = await self._expander.expand(query)
      primary_variants = all_variants[:2]  # Reduce from 11 to 2

      # Dispatch both variants in parallel
      async for lead in self._aggregator.stream_discover(primary_variants, wilaya, limit):
          ...
  ```
* **How to Test:**
  Trigger a search for `"pharmacie"`. Measure Time-To-First-Result (TTFR). It must drop from $\approx 45\text{s}$ to $< 2\text{s}$.

---

### Task 12: Implement a Strict Business Quality Gate (Block Cartoons/Amazon)
* **The Problem:** The scraper currently indexes Wikipedia articles, French cartoons, Amazon search pages, and government portals as leads.
* **File to modify:** `utils/spam_filter.py`
* **How to Implement:**
  Update `SourcingSpamFilter`:
  ```python
  # Add to EXACT_DOMAINS:
  JUNK_DOMAINS = frozenset({
      "amazon.com", "amazon.fr", "etsy.com", "aliexpress.com",
      "wikipedia.org", "youtube.com", "facebook.com", "instagram.com", "tiktok.com",
      "interieur.gov.dz", "mfa.gov.dz", "sante.gov.dz", "joradp.dz"
  })

  # Title words that guarantee a page is not an individual business
  NON_BUSINESS_TITLE_TOKENS = (
      "loi", "guide complet", "ministère", "actualités", "provinces of algeria",
      "série tv", "téléchargements", "avis de recrutement", "concours", "décret"
  )

  def is_spam(self, url: str, title: str) -> bool:
      ...
      # Check junk domains
      if any(domain == d or domain.endswith("." + d) for d in JUNK_DOMAINS):
          return True

      # Check non-business keywords in title
      title_lower = title.lower()
      if any(token in title_lower for token in NON_BUSINESS_TITLE_TOKENS):
          return True
      ...
  ```
* **How to Test:**
  Run `is_spam("https://amazon.fr/s?k=tshirt", "Amazon.fr : T Shirt Algerie Homme")`. Assert `True`.
  Run `is_spam("https://france.tv/show", "Petite Casbah - France TV")`. Assert `True`.

---

### Task 13: Purge C++ SIMD Theater in Favor of Optimized Python Packages
* **The Problem:** The C++ native core (`engine_native`) contains no real SIMD in its HTML scanner, has thread-safety bugs in its global Bloom filter, and is slower than standard `rapidfuzz`.
* **Action:**
  1. Replace `engine.native` Levenshtein with `rapidfuzz.distance.Levenshtein.distance`.
  2. Replace `engine.native` HTML extraction with `selectolax` (C-based lexer) or pre-compiled regex for `<title>`, `<meta>`, `tel:`, and `mailto:`.
  3. Replace `g_bloom` with a standard thread-safe Python `set` or SQLite index.
* **File to modify:** `engine/native.py`, `pyproject.toml`
* **How to Implement:**
  Install `selectolax`:
  ```bash
  pip install selectolax
  ```
  In `engine/native.py`:
  ```python
  from selectolax.parser import HTMLParser

  def fast_extract_html(html: bytes) -> ExtractionResult:
      tree = HTMLParser(html)
      title = tree.css_first("title")
      title_text = title.text().strip() if title else ""
      
      links = [a.attributes.get("href", "") for a in tree.css("a") if "href" in a.attributes]
      ...
  ```
* **How to Test:**
  Run `benchmarks/bench_engine.py`. Confirm memory stability and identical parsing speeds without compilation or ctypes overhead.

---

### Task 14: Isolate Backoff State Per-Domain
* **The Problem:** `CrawlerEngine` shares a single `ExponentialBackoff` instance across all concurrent workers. If one worker hits a block on one domain, it increases the delay for all workers on unrelated domains.
* **File to modify:** `services/crawler_service.py`
* **How to Implement:**
  In `services/crawler_service.py`, change:
  ```python
  # Replace: self._backoff = ExponentialBackoff()
  # With a per-domain registry:
  self._domain_backoffs: dict[str, ExponentialBackoff] = defaultdict(ExponentialBackoff)
  ```
  In `_crawl_one`:
  ```python
  backoff = self._domain_backoffs[domain]
  if response.status_code in (429, 503):
      await backoff.sleep()
  else:
      backoff.reset()
  ```
* **How to Test:**
  Simulate an HTTP 429 on `domain-a.com` while crawling `domain-b.com`. Assert `domain-b.com` proceeds with 0 delay.

---

### Task 15: Fix SQLite WAL Re-declaration Anti-Pattern
* **The Problem:** `PRAGMA journal_mode = WAL;` is executed on every single SQLite connection. In SQLite, this acquires an exclusive disk lock to check WAL status.
* **File to modify:** `infrastructure/storage/database.py`
* **How to Implement:**
  Remove `PRAGMA journal_mode = WAL;` from the connection factory:
  ```python
  @contextmanager
  def connection(self) -> Iterator[sqlite3.Connection]:
      conn = sqlite3.connect(
          str(self._db_path),
          timeout=30.0,
          isolation_level="",
          check_same_thread=False,
      )
      conn.row_factory = sqlite3.Row
      try:
          conn.execute("PRAGMA foreign_keys = ON;")
          conn.execute("PRAGMA synchronous = NORMAL;")
          conn.execute("PRAGMA busy_timeout = 5000;") # Wait up to 5s on lock
          yield conn
          conn.commit()
      ...
  ```
  Only execute `PRAGMA journal_mode = WAL;` once inside `DatabaseManager.initialise()`.
* **How to Test:**
  Execute 100 concurrent read/write queries via `asyncio.gather()`. Check for `sqlite3.OperationalError: database is locked`. It should run cleanly with zero lock exceptions.

---

## SECTION 4: Step-by-Step Implementation Order

Follow this sequence to avoid breaking dependencies:

```
[Phase 1: Zero-Crash Baseline]
  ├── Task 1: Fix Queue Visibility (dashboard.html)
  ├── Task 2: Fix Stats Crash (dashboard.html)
  ├── Task 3: Fix 404 Route on Tags (dashboard.html)
  └── Task 4: Fix 422 Search Error (api/routes/misc.py)

[Phase 2: Data Integrity & Storage Stability]
  ├── Task 6: Atomic SQLite Upsert (lead_repo.py)
  ├── Task 15: Remove redundant PRAGMA WAL declarations (database.py)
  └── Task 7: Fix Stored XSS in Link Rendering (dashboard.html)

[Phase 3: Search & Dashboard Usability]
  └── Task 5: Unify Search and List Endpoints (leads.py, lead_repo.py)

[Phase 4: Open-World Geo & Sourcing Pipeline]
  ├── Task 8: Decouple OSM into an optional Oracle (discovery_service.py)
  ├── Task 9: Implement Telephony Area Code Inference (geo_inference.py)
  ├── Task 10: Invert Map-Absence Scoring Penalty (scorer.py)
  ├── Task 11: Kill Sequential Dialect Multiplier (discovery_service.py)
  ├── Task 12: Business Quality Gate Spam Filter (spam_filter.py)
  └── Task 14: Per-Domain Backoff State (crawler_service.py)

[Phase 5: Performance & Cleanup]
  └── Task 13: Replace engine_native with selectolax & rapidfuzz
```

---

## SECTION 5: Additional Bottleneck Avoidance & Speedups

To maximize overall pipeline throughput:

1. **DNS Pre-Caching:**
   `httpx` resolves DNS for every new host, introducing 50–150ms latency per unique domain. Add `aiohttp` or an in-memory `aiodns` resolver cache to your HTTP factory to eliminate repeated DNS roundtrips.
2. **Local SearXNG Instance:**
   Deploy a local Docker container for SearXNG:
   ```bash
   docker run -d --name searxng -p 8888:8080 -e "SEARXNG_BASE_URL=http://localhost:8888/" searxng/searxng
   ```
   Querying SearXNG returns clean, aggregated JSON results from multiple search backends in $< 400\text{ms}$, bypassing DuckDuckGo HTML scraping and anti-bot rate limits completely.
3. **HTTP Head-First Content Verification:**
   Before running a full `GET` request on discovered URLs (which downloads megabytes of image assets and script bundles), execute a lightweight `HEAD` request or stream only the first 32 KB of the body. You only need the `<head>` and top text to extract identity and contact data. This reduces crawl bandwidth consumption by over 80%.


and then push it with these pats 
one them works 
