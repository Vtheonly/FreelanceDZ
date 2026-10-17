"""Geographic engine — real wilaya boundaries, spatial queries, aggregation.

Loads the versioned 58-wilaya boundary dataset (``engine/geodata/``) once
per process and provides:

    - point-in-polygon wilaya lookup (bbox pre-filter + ray casting)
    - per-wilaya centroids and bounding boxes (computed from geometry,
      cached)
    - catalogue/stats aggregation for the API and UI map
    - a transport-ready GeoJSON payload (boundaries + live counts)

Design notes:
    - Pure geometry lives here — never inside UI callbacks (refactorv5 §9).
    - The dataset is immutable at runtime, so all derived structures
      (bbox index, centroid cache) are computed once and shared.
    - The class is thread-safe for reads: every mutable structure is fully
      built during ``__init__``.
"""

from __future__ import annotations

import json
import logging
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from config.wilayas import ALGERIA_BBOX, WILAYAS, get_wilaya_by_name

logger = logging.getLogger("engine.geo")

GEODATA_FILE = Path(__file__).resolve().parent / "geodata" / "algeria_wilayas_58.geojson"

ALGERIA_CENTER: tuple[float, float] = (28.0, 2.65)  # lat, lon


def _rings(geometry: dict) -> list[list[list[float]]]:
    """Exterior rings only — holes are irrelevant for point-in-wilaya."""
    if geometry["type"] == "Polygon":
        return [geometry["coordinates"][0]]
    if geometry["type"] == "MultiPolygon":
        return [poly[0] for poly in geometry["coordinates"]]
    return []


def _point_in_ring(lon: float, lat: float, ring: list[list[float]]) -> bool:
    """Ray-casting containment test (odd-even rule)."""
    inside = False
    n = len(ring)
    j = n - 1
    for i in range(n):
        xi, yi = ring[i][0], ring[i][1]
        xj, yj = ring[j][0], ring[j][1]
        if (yi > lat) != (yj > lat):
            intersect_x = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < intersect_x:
                inside = not inside
        j = i
    return inside


class WilayaGeoService:
    """Boundary-backed geographic operations over the 58 wilayas."""

    _instance: Optional["WilayaGeoService"] = None
    _instance_lock = threading.Lock()

    def __init__(self, geodata_path: Path = GEODATA_FILE) -> None:
        self._features: list[dict[str, Any]] = []
        self._by_code: dict[int, dict[str, Any]] = {}
        self._bbox_by_code: dict[int, tuple[float, float, float, float]] = {}
        self._rings_by_code: dict[int, list[list[list[float]]]] = {}
        self._centroid_by_code: dict[int, tuple[float, float]] = {}
        self._load(geodata_path)

    @classmethod
    def get(cls) -> "WilayaGeoService":
        """Process-wide singleton (the dataset is immutable)."""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = WilayaGeoService()
        return cls._instance

    # ------------------------------------------------------------------
    # Loading / indexing
    # ------------------------------------------------------------------
    def _load(self, path: Path) -> None:
        if not path.exists():
            raise FileNotFoundError(
                f"wilaya boundary dataset missing: {path} "
                "(run scripts/fetch_wilaya_boundaries.py)"
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        for feat in data["features"]:
            props = feat["properties"]
            code = int(props["code"])
            geometry = feat["geometry"]
            rings = _rings(geometry)
            if not rings:
                logger.warning("wilaya %s has no polygon geometry", code)
                continue
            self._features.append(feat)
            self._by_code[code] = feat
            self._rings_by_code[code] = rings
            self._bbox_by_code[code] = self._bbox(rings)
            self._centroid_by_code[code] = self._centroid(rings)
        if len(self._features) != 58:
            raise ValueError(
                f"expected 58 wilaya features, loaded {len(self._features)}"
            )
        logger.info("geographic engine ready: %d wilayas from %s", len(self._features), path.name)

    @staticmethod
    def _bbox(rings: list[list[list[float]]]) -> tuple[float, float, float, float]:
        min_lon = min_lat = 180.0
        max_lon = max_lat = -180.0
        for ring in rings:
            for lon, lat in ring:
                if lon < min_lon:
                    min_lon = lon
                if lon > max_lon:
                    max_lon = lon
                if lat < min_lat:
                    min_lat = lat
                if lat > max_lat:
                    max_lat = lat
        return (min_lon, min_lat, max_lon, max_lat)

    @staticmethod
    def _centroid(rings: list[list[list[float]]]) -> tuple[float, float]:
        """Area-weighted centroid of the largest ring (stable representative)."""
        best_area = -1.0
        best = (0.0, 0.0)
        for ring in rings:
            area = cx = cy = 0.0
            n = len(ring)
            for i in range(n - 1):
                x1, y1 = ring[i][0], ring[i][1]
                x2, y2 = ring[i + 1][0], ring[i + 1][1]
                cross = x1 * y2 - x2 * y1
                area += cross
                cx += (x1 + x2) * cross
                cy += (y1 + y2) * cross
            if abs(area) < 1e-12:
                continue
            point = (cy / (3.0 * area), cx / (3.0 * area))  # lat, lon
            if abs(area) / 2.0 > best_area:
                best_area = abs(area) / 2.0
                best = point
        return best if best_area >= 0 else (0.0, 0.0)

    # ------------------------------------------------------------------
    # Spatial queries
    # ------------------------------------------------------------------
    def lookup(self, lon: float, lat: float) -> Optional[dict[str, Any]]:
        """Wilaya containing the point, or ``None`` outside Algeria.

        Bbox pre-filter keeps the common case O(1)-ish; the ray-cast only
        runs for bbox hits (typically 1-2 wilayas at shared borders).
        """
        for code, (min_lon, min_lat, max_lon, max_lat) in self._bbox_by_code.items():
            if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
                continue
            for ring in self._rings_by_code[code]:
                if _point_in_ring(lon, lat, ring):
                    return self._by_code[code]["properties"]
        return None

    def nearest_wilaya(self, lon: float, lat: float) -> Optional[dict[str, Any]]:
        """Closest wilaya by centroid distance (fallback for border misses)."""
        best_code: Optional[int] = None
        best_dist = float("inf")
        for code, (c_lat, c_lon) in self._centroid_by_code.items():
            d2 = (c_lat - lat) ** 2 + (c_lon - lon) ** 2
            if d2 < best_dist:
                best_dist = d2
                best_code = code
        return self._by_code[best_code]["properties"] if best_code else None

    def centroid(self, code: int) -> tuple[float, float]:
        """(lat, lon) centroid for a wilaya code."""
        return self._centroid_by_code.get(code, ALGERIA_CENTER)

    def bbox_of(self, code: int) -> Optional[tuple[float, float, float, float]]:
        return self._bbox_by_code.get(code)

    def wilaya_code_for_name(self, name: str) -> Optional[int]:
        w = get_wilaya_by_name(name)
        return int(w["code"]) if w else None  # type: ignore[arg-type]

    # ------------------------------------------------------------------
    # Aggregation / transport
    # ------------------------------------------------------------------
    def wilaya_catalogue(
        self,
        leads_by_wilaya: Optional[dict[str, int]] = None,
        checkpoints_by_wilaya: Optional[dict[str, int]] = None,
    ) -> list[dict[str, Any]]:
        """Catalogue rows joined with live lead/checkpoint counts.

        ``*_by_wilaya`` maps lowercase wilaya name -> count (produced by the
        repositories' GROUP BY queries — never by loading full rows).
        """
        leads_by_wilaya = leads_by_wilaya or {}
        checkpoints_by_wilaya = checkpoints_by_wilaya or {}
        rows: list[dict[str, Any]] = []
        for w in WILAYAS:
            code = int(w["code"])  # type: ignore[arg-type]
            name_fr = str(w["name_fr"])
            key = name_fr.strip().lower()
            c_lat, c_lon = self._centroid_by_code.get(code, (float(w["lat"]), float(w["lon"])))  # type: ignore[arg-type]
            rows.append({
                "code": code,
                "name_fr": name_fr,
                "name_en": w["name_en"],
                "name_ar": w["name_ar"],
                "lat": round(c_lat, 4),
                "lon": round(c_lon, 4),
                "area_code": w.get("area_code", ""),
                "leads_count": leads_by_wilaya.get(key, 0),
                "checkpoints_count": checkpoints_by_wilaya.get(key, 0),
            })
        return rows

    def boundaries_geojson(self) -> dict[str, Any]:
        """The raw boundary FeatureCollection (for API transport)."""
        return {
            "type": "FeatureCollection",
            "name": "algeria_wilayas_58",
            "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:OGC:1.3:CRS84"}},
            "features": self._features,
        }

    @property
    def feature_count(self) -> int:
        return len(self._features)

    @property
    def algeria_bbox(self) -> tuple[float, float, float, float]:
        return ALGERIA_BBOX


@lru_cache(maxsize=1)
def get_geo_service() -> WilayaGeoService:
    """Cached accessor matching the project's settings/repo convention."""
    return WilayaGeoService.get()
