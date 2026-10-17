#!/usr/bin/env python3
"""Acquire and normalise the Algeria wilaya boundary dataset.

Fetches the 58-wilaya boundary GeoJSON, re-maps its features onto the
official Law 19-12 wilaya codes used by ``config/wilayas.py``, rounds
coordinates to 4 decimal places (~11 m), drops duplicate consecutive
points, validates the geometry, and writes the versioned dataset consumed
by ``engine/geo.py``.

Usage:
    python scripts/fetch_wilaya_boundaries.py [--source URL|FILE] [--force]

Output:
    engine/geodata/algeria_wilayas_58.geojson

Provenance / license:
    The upstream geometry is derived from OpenStreetMap and distributed
    under the Open Database License (ODbL-1.0). See
    engine/geodata/ATTRIBUTION.md — attribution and share-alike
    obligations apply when redistributing.
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from config.wilayas import ALGERIA_BBOX, WILAYAS  # noqa: E402

DEFAULT_SOURCE = (
    "https://raw.githubusercontent.com/namrouche993/algeria-wilayas-geojson/"
    "main/derived-from-v69/v58.geojson"
)
OUTPUT = PROJECT_ROOT / "engine" / "geodata" / "algeria_wilayas_58.geojson"


def _fold(name: str) -> str:
    """Accent/case-insensitive folding for name matching."""
    decomposed = unicodedata.normalize("NFD", name)
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return " ".join(stripped.lower().replace("'", " ").split())


def _clean_ring(ring: list) -> list:
    """Round to 4 dp and drop consecutive duplicates; keep the ring closed."""
    out: list[list[float]] = []
    for lon, lat in ring:
        pt = [round(float(lon), 4), round(float(lat), 4)]
        if not out or out[-1] != pt:
            out.append(pt)
    if len(out) > 1 and out[0] != out[-1]:
        out.append(list(out[0]))
    return out


def _clean_geometry(geom: dict) -> dict:
    if geom["type"] == "Polygon":
        return {"type": "Polygon", "coordinates": [_clean_ring(r) for r in geom["coordinates"]]}
    if geom["type"] == "MultiPolygon":
        return {
            "type": "MultiPolygon",
            "coordinates": [[_clean_ring(r) for r in poly] for poly in geom["coordinates"]],
        }
    raise ValueError(f"unsupported geometry type {geom['type']!r}")


def _validate(features: list[dict]) -> None:
    codes = [f["properties"]["code"] for f in features]
    assert len(features) == 58, f"expected 58 features, got {len(features)}"
    assert sorted(codes) == list(range(1, 59)), "codes must be exactly 1..58"
    min_lon, min_lat, max_lon, max_lat = ALGERIA_BBOX
    # The bbox check uses a small tolerance for simplified offshore vertices.
    tol = 0.35
    for f in features:
        geom = f["geometry"]
        polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        for poly in polys:
            for ring in poly:
                assert ring[0] == ring[-1], f"unclosed ring in wilaya {f['properties']['code']}"
                for lon, lat in ring:
                    assert (min_lon - tol) <= lon <= (max_lon + tol), f"lon {lon} out of range"
                    assert (min_lat - tol) <= lat <= (max_lat + tol), f"lat {lat} out of range"


def build(source: str) -> dict:
    path = Path(source)
    if path.exists():
        raw = json.loads(path.read_text(encoding="utf-8"))
    else:
        raw = json.loads(_download(source))

    catalogue_by_fold = {}
    for w in WILAYAS:
        for key in ("name_fr", "name_en"):
            catalogue_by_fold[_fold(str(w[key]))] = w

    seen_codes: set[int] = set()
    features: list[dict] = []
    unmatched: list[str] = []

    for feat in raw["features"]:
        props = feat.get("properties", {})
        raw_name = str(props.get("name") or props.get("name_fr") or props.get("name_en") or "")
        entry = catalogue_by_fold.get(_fold(raw_name))
        if entry is None:
            unmatched.append(raw_name)
            continue
        code = int(entry["code"])  # type: ignore[arg-type]
        if code in seen_codes:
            raise ValueError(f"duplicate wilaya code {code} after re-mapping")
        seen_codes.add(code)
        features.append({
            "type": "Feature",
            "properties": {
                "code": code,
                "name_fr": str(entry["name_fr"]),
                "name_en": str(entry["name_en"]),
                "name_ar": str(entry["name_ar"]),
            },
            "geometry": _clean_geometry(feat["geometry"]),
        })

    if unmatched:
        raise ValueError(f"features not matched to the catalogue: {unmatched}")
    _validate(features)
    features.sort(key=lambda f: f["properties"]["code"])

    return {
        "type": "FeatureCollection",
        "name": "algeria_wilayas_58",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
        "features": features,
    }


def _download(url: str) -> str:
    import urllib.request

    print(f"downloading {url}")
    with urllib.request.urlopen(url, timeout=120) as resp:  # noqa: S310 - pinned https URL
        return resp.read().decode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=DEFAULT_SOURCE, help="URL or local file")
    parser.add_argument("--force", action="store_true", help="overwrite existing output")
    args = parser.parse_args()

    if OUTPUT.exists() and not args.force:
        print(f"{OUTPUT} already exists (use --force to rebuild)")
        return 0

    dataset = build(args.source)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(dataset, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    size_kb = OUTPUT.stat().st_size / 1024
    n_points = sum(
        len(ring)
        for f in dataset["features"]
        for poly in ([f["geometry"]["coordinates"]] if f["geometry"]["type"] == "Polygon"
                     else f["geometry"]["coordinates"])
        for ring in poly
    )
    print(f"wrote {OUTPUT} ({size_kb:.1f} KB, {len(dataset['features'])} wilayas, {n_points} vertices)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
