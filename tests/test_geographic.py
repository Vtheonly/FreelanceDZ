"""Geographic engine tests — data integrity and spatial correctness.

Covers: boundary dataset integrity (58 wilayas, closed rings, in-bbox,
official Law 19-12 codes), point-in-polygon accuracy against known
coordinates, catalogue/centroid coherence, and the telephony area-code
inference contract (v4 Task 9).
"""

from __future__ import annotations

import json

import pytest

from config.wilayas import (
    ALGERIA_BBOX,
    AREA_CODE_TO_WILAYA,
    WILAYAS,
    get_wilaya_by_code,
    normalise_wilaya_name,
)
from engine.geo import GEODATA_FILE, WilayaGeoService
from utils.geo_inference import (
    get_wilaya_coordinates,
    infer_wilaya_from_phone,
    infer_wilaya_from_text,
)


@pytest.fixture(scope="module")
def geo() -> WilayaGeoService:
    return WilayaGeoService()


@pytest.fixture(scope="module")
def dataset() -> dict:
    return json.loads(GEODATA_FILE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Dataset integrity
# ---------------------------------------------------------------------------
def test_dataset_has_58_wilayas_with_official_codes(dataset):
    codes = sorted(f["properties"]["code"] for f in dataset["features"])
    assert codes == list(range(1, 59)), "codes must be exactly the official 1..58"


def test_dataset_geometry_valid(dataset):
    min_lon, min_lat, max_lon, max_lat = ALGERIA_BBOX
    tol = 0.35  # simplified offshore vertices
    n_points = 0
    for feature in dataset["features"]:
        geom = feature["geometry"]
        polys = [geom["coordinates"]] if geom["type"] == "Polygon" else geom["coordinates"]
        for poly in polys:
            for ring in poly:
                assert ring[0] == ring[-1], f"unclosed ring in {feature['properties']['name_fr']}"
                for lon, lat in ring:
                    assert (min_lon - tol) <= lon <= (max_lon + tol)
                    assert (min_lat - tol) <= lat <= (max_lat + tol)
                n_points += len(ring)
    # Compact enough for interactive transport (API + browser payload).
    assert GEODATA_FILE.stat().st_size < 300_000
    assert n_points < 20_000


def test_dataset_names_match_catalogue(dataset):
    for feature in dataset["features"]:
        props = feature["properties"]
        catalogue = get_wilaya_by_code(props["code"])
        assert catalogue is not None
        assert props["name_fr"] == catalogue["name_fr"]
        assert props["name_en"] == catalogue["name_en"]
        assert props["name_ar"] == catalogue["name_ar"]


def test_catalogue_coordinates_inside_algeria():
    for w in WILAYAS:
        lat, lon = float(w["lat"]), float(w["lon"])  # type: ignore[arg-type]
        assert 19.0 <= lat <= 37.2, f"{w['name_fr']} latitude {lat}"
        assert -8.8 <= lon <= 12.2, f"{w['name_fr']} longitude {lon}"


def test_catalogue_area_codes_valid():
    assert len(AREA_CODE_TO_WILAYA) >= 20
    for prefix, name in AREA_CODE_TO_WILAYA.items():
        assert prefix.startswith("0") and len(prefix) == 3
        assert normalise_wilaya_name(name) == name, f"{name} not a canonical name"


# ---------------------------------------------------------------------------
# Spatial queries
# ---------------------------------------------------------------------------
KNOWN_POINTS = [
    (36.7538, 3.0588, "Alger"),        # capital centre
    (35.6976, -0.6337, "Oran"),        # Oran centre
    (36.3650, 6.6147, "Constantine"),
    (22.7850, 5.5228, "Tamanrasset"),  # deep south
    (34.8504, 5.7281, "Biskra"),
    (31.9493, 5.3250, "Ouargla"),
    (36.1906, 5.4103, "Sétif"),
]


@pytest.mark.parametrize("lat,lon,expected", KNOWN_POINTS)
def test_lookup_known_cities(geo, lat, lon, expected):
    hit = geo.lookup(lon, lat)
    assert hit is not None, f"no wilaya contains ({lat}, {lon})"
    assert hit["name_fr"] == expected


def test_lookup_outside_country(geo):
    assert geo.lookup(2.35, 48.85) is None   # Paris
    assert geo.lookup(-0.13, 51.5) is None   # London


def test_nearest_wilaya_fallback(geo):
    near = geo.nearest_wilaya(3.2, 36.9)     # just off the Alger coast
    assert near is not None


def test_centroids_inside_their_own_wilaya(geo):
    """Geometry-derived centroid of each wilaya falls inside it (robust
    for the vast majority of shapes; a few concave ones may legitimately
    miss, so we assert a strong majority)."""
    inside = 0
    for code in range(1, 59):
        c_lat, c_lon = geo.centroid(code)
        if geo.lookup(c_lon, c_lat) is not None and geo.lookup(c_lon, c_lat)["code"] == code:
            inside += 1
    assert inside >= 50, f"only {inside}/58 centroids self-contain"


def test_boundaries_transport_payload(geo):
    payload = geo.boundaries_geojson()
    assert payload["type"] == "FeatureCollection"
    assert len(payload["features"]) == 58


def test_wilaya_catalogue_counts(geo):
    rows = geo.wilaya_catalogue(
        leads_by_wilaya={"oran": 7}, checkpoints_by_wilaya={"oran": 2}
    )
    assert len(rows) == 58
    oran = next(r for r in rows if r["name_fr"] == "Oran")
    assert oran["leads_count"] == 7
    assert oran["checkpoints_count"] == 2
    assert oran["code"] == 31


# ---------------------------------------------------------------------------
# Telephony inference (v4 Task 9)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "phone,expected",
    [
        ("+21321456789", "Alger"),
        ("0021341334455", "Oran"),
        ("041 33 22 11", "Oran"),
        ("031-88-99-00", "Constantine"),
        ("049 12 34 56", "Béchar"),
        ("0550 12 34 56", None),      # mobile — non-geographic
        ("+33123456789", None),       # foreign
        ("12345", None),
        (None, None),
        ("", None),
    ],
)
def test_infer_wilaya_from_phone(phone, expected):
    assert infer_wilaya_from_phone(phone) == expected


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Grand magasin situé à Tizi Ouzou", "Tizi Ouzou"),
        ("Cabinet médical — Oran,Algérie", "Oran"),
        ("صيدلية المركز في وهران", "Oran"),
        ("Boutique en ligne", None),
    ],
)
def test_infer_wilaya_from_text(text, expected):
    assert infer_wilaya_from_text(text) == expected


def test_get_wilaya_coordinates_defaults_safely():
    lat, lon = get_wilaya_coordinates("Nowhere")
    assert (lat, lon) == (36.7538, 3.0588)  # Algiers default
    lat, lon = get_wilaya_coordinates("Oran")
    assert abs(lat - 35.6976) < 0.01 and abs(lon + 0.6337) < 0.01


def test_normalise_wilaya_name():
    assert normalise_wilaya_name("oran") == "Oran"
    assert normalise_wilaya_name("ALGER") == "Alger"
    assert normalise_wilaya_name("وهران") == "Oran"
    assert normalise_wilaya_name("") is None
    assert normalise_wilaya_name("Atlantis") is None
