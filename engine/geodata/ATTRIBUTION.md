# Geographic data attribution — `algeria_wilayas_58.geojson`

## What this file is

Versioned boundary geometry for Algeria's 58 wilayas (official division of
Law 19-12, December 11, 2019), WGS84 (EPSG:4326), coordinates rounded to 4
decimal places (~11 m). Each feature carries `code` (official 1-58),
`name_fr`, `name_en`, and `name_ar` properties. Consumed by `engine/geo.py`.

## Provenance

| Step | Source | Notes |
|------|--------|-------|
| 1 | `namrouche993/algeria-wilayas-geojson` → `derived-from-v69/v58.geojson` | Derived by that project from `yasserstudio/geoalgeria`'s wilaya-boundaries dataset |
| 2 | `yasserstudio/geoalgeria` → `packages/dataset/data/geojson/wilaya-boundaries.geojson` | Boundary geometry derived from **OpenStreetMap** |
| 3 | This project's `scripts/fetch_wilaya_boundaries.py` | Re-maps features onto official Law 19-12 codes (the upstream file uses a different code assignment for the 10 post-2019 southern wilayas), rounds coordinates, deduplicates vertices, and validates rings/bbox |

## License — ODbL 1.0

The geometry is derived from OpenStreetMap and is distributed under the
**Open Database License (ODbL) v1.0**:

- <https://opendatacommons.org/licenses/odbl/1-0/>
- <https://www.openstreetmap.org/copyright>

If you redistribute this file (or a derivative database built from it) you
must: (1) attribute OpenStreetMap and its contributors, and (2) offer the
derivative database under ODbL. Rendering the boundaries in the application
(a "produced work") carries only the attribution requirement.

## Updating the dataset

```
python scripts/fetch_wilaya_boundaries.py --force            # from pinned upstream
python scripts/fetch_wilaya_boundaries.py --source FILE      # from a local file
```

The script fails loudly unless exactly 58 features with codes 1-58, closed
rings, and in-bbox vertices are produced. Administrative reforms (e.g. a
future division change) are a data update: swap the source, keep the
catalogue in `config/wilayas.py` in sync, and re-run.
