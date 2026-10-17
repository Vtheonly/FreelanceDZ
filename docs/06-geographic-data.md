# 06 · Geographic Data: Boundaries, CRS, and Updates

## Datasets

| Dataset | Location | Contents |
|---|---|---|
| Wilaya boundaries | `engine/geodata/algeria_wilayas_58.geojson` | 58 Polygon/MultiPolygon features, WGS84 (CRS84 / EPSG:4326), ~113 KB, ~7.1k vertices, coordinates rounded to 4 dp (~11 m) |
| Wilaya catalogue | `config/wilayas.py` | official codes 1–58 (Law 19-12), FR/EN/AR names, representative coordinates, ARPT landline area codes |

Both are **data, not code**: an administrative reform is a dataset swap,
never a code change (refactorv5 §4).

## Provenance & license

The boundary geometry is derived from **OpenStreetMap** and is
redistributed under the **Open Database License (ODbL-1.0)** — see
`engine/geodata/ATTRIBUTION.md` (kept next to the file, as the license
requires). Rendering it in the application is a produced work (attribution
obligation only); redistributing the file or a derivative database
carries the share-alike obligation.

Chain: `yasserstudio/geoalgeria` (OSM-derived boundaries) →
`namrouche993/algeria-wilayas-geojson` (v58 derivation) →
`scripts/fetch_wilaya_boundaries.py` (this repo) which re-maps features
onto **official Law 19-12 codes** — the upstream file assigns different
codes to the ten post-2019 southern wilayas — rounds coordinates,
deduplicates consecutive vertices, and validates the result.

## Validation (enforced by tests)

`tests/test_geographic.py` asserts:
- exactly 58 features with codes exactly 1–58;
- every ring closed, all coordinates inside the national bbox (+ tolerance
  for simplified offshore vertices);
- names identical to the catalogue in all three scripts;
- known city coordinates resolve to the right wilaya via point-in-polygon
  (Alger, Oran, Constantine, Sétif, Biskra, Ouargla, Tamanrasset);
- the file stays compact (<300 KB) for API transport.

## Updating the dataset

```bash
python scripts/fetch_wilaya_boundaries.py --force        # pinned upstream
python scripts/fetch_wilaya_boundaries.py --source FILE  # local file
```

The script fails loudly on any structural violation. Keep
`config/wilayas.py` in sync when the administrative division changes
(codes, names), then re-run the geographic tests.

## Coordinate systems

- Storage & API: WGS84 latitude/longitude in decimal degrees.
- `POST /api/v2/geo/lookup` validates ranges (lat ±90, lon ±180) and
  resolves via bbox-prefiltered ray casting (~40k points/s) with a
  nearest-wilaya fallback for coastal/offshore clicks (ports are the
  canonical checkpoint — `approximate: true` marks those results).
- National bbox used for validation and Overpass nationwide fallback:
  `(-8.68, 18.96, 12.0, 37.09)` (lon min, lat min, lon max, lat max).

## Telephony geo-inference (v4 Task 9)

Algerian landlines are geographic: `AREA_CODE_TO_WILAYA` maps the ARPT
prefixes (021–049) to wilayas. `utils/geo_inference.py` recovers the
wilaya for online-only businesses (landline, no map pin, no address), with
a free-text mention fallback. Mobile prefixes (05/06/07) are deliberately
non-geographic.
