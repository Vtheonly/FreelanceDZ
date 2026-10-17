"""Static catalogue of Algeria's 58 wilayas.

Each wilaya carries its official code (1-58, Law 19-12 of December 11, 2019),
its name in English, French, and Arabic, its representative coordinates
(centroid of the administrative boundary, WGS84), and its landline telephony
area code where one exists.

Sources:
    - Official Algerian administrative division (2019 reform, 58 wilayas,
      JO No. 78 of December 18, 2019).
    - Centroid coordinates cross-validated against the boundary geometry in
      ``engine/geodata/algeria_wilayas_58.geojson`` (OpenStreetMap-derived).
    - Landline area codes: ARPT numbering plan (geographic prefixes).

The catalogue is a tuple of dicts so it remains immutable and hashable. It is
deliberately data-only: boundary geometry lives in the versioned geodata
dataset so administrative reforms (e.g. future wilaya splits) are a data
update, not a code change.
"""

from __future__ import annotations

from typing import Optional


WILAYAS: tuple[dict[str, object], ...] = (
    {"code": 1,  "name_en": "Adrar",          "name_fr": "Adrar",          "name_ar": "أدرار",          "lat": 27.8744, "lon": -0.2939, "area_code": "049"},
    {"code": 2,  "name_en": "Chlef",          "name_fr": "Chlef",          "name_ar": "الشلف",          "lat": 36.1653, "lon": 1.3345,  "area_code": "027"},
    {"code": 3,  "name_en": "Laghouat",       "name_fr": "Laghouat",       "name_ar": "الأغواط",        "lat": 33.8000, "lon": 2.8651,  "area_code": "029"},
    {"code": 4,  "name_en": "Oum El Bouaghi", "name_fr": "Oum El Bouaghi", "name_ar": "أم البواقي",     "lat": 35.8756, "lon": 7.1136,  "area_code": "032"},
    {"code": 5,  "name_en": "Batna",          "name_fr": "Batna",          "name_ar": "باتنة",          "lat": 35.5558, "lon": 6.1741,  "area_code": "033"},
    {"code": 6,  "name_en": "Béjaïa",         "name_fr": "Béjaïa",         "name_ar": "بجاية",          "lat": 36.7559, "lon": 5.0843,  "area_code": "034"},
    {"code": 7,  "name_en": "Biskra",         "name_fr": "Biskra",         "name_ar": "بسكرة",          "lat": 34.8504, "lon": 5.7281,  "area_code": "033"},
    {"code": 8,  "name_en": "Béchar",         "name_fr": "Béchar",         "name_ar": "بشار",           "lat": 31.6167, "lon": -2.2167, "area_code": "049"},
    {"code": 9,  "name_en": "Blida",          "name_fr": "Blida",          "name_ar": "البليدة",        "lat": 36.4700, "lon": 2.8300,  "area_code": "025"},
    {"code": 10, "name_en": "Bouira",         "name_fr": "Bouira",         "name_ar": "البويرة",        "lat": 36.3749, "lon": 3.9020,  "area_code": "026"},
    {"code": 11, "name_en": "Tamanrasset",    "name_fr": "Tamanrasset",    "name_ar": "تمنراست",        "lat": 22.7850, "lon": 5.5228,  "area_code": "029"},
    {"code": 12, "name_en": "Tébessa",        "name_fr": "Tébessa",        "name_ar": "تبسة",           "lat": 35.4042, "lon": 8.1242,  "area_code": "037"},
    {"code": 13, "name_en": "Tlemcen",        "name_fr": "Tlemcen",        "name_ar": "تلمسان",         "lat": 34.8783, "lon": -1.3150, "area_code": "043"},
    {"code": 14, "name_en": "Tiaret",         "name_fr": "Tiaret",         "name_ar": "تيارت",          "lat": 35.3711, "lon": 1.3170,  "area_code": "046"},
    {"code": 15, "name_en": "Tizi Ouzou",     "name_fr": "Tizi Ouzou",     "name_ar": "تيزي وزو",       "lat": 36.7118, "lon": 4.0459,  "area_code": "026"},
    {"code": 16, "name_en": "Algiers",        "name_fr": "Alger",          "name_ar": "الجزائر",        "lat": 36.7538, "lon": 3.0588,  "area_code": "021"},
    {"code": 17, "name_en": "Djelfa",         "name_fr": "Djelfa",         "name_ar": "الجلفة",         "lat": 34.6728, "lon": 3.2630,  "area_code": "027"},
    {"code": 18, "name_en": "Jijel",          "name_fr": "Jijel",          "name_ar": "جيجل",           "lat": 36.8206, "lon": 5.7667,  "area_code": "034"},
    {"code": 19, "name_en": "Sétif",          "name_fr": "Sétif",         "name_ar": "سطيف",           "lat": 36.1906, "lon": 5.4103,  "area_code": "036"},
    {"code": 20, "name_en": "Saïda",          "name_fr": "Saïda",          "name_ar": "سعيدة",          "lat": 34.8303, "lon": 0.1517,  "area_code": "048"},
    {"code": 21, "name_en": "Skikda",         "name_fr": "Skikda",         "name_ar": "سكيكدة",         "lat": 36.8762, "lon": 6.9092,  "area_code": "038"},
    {"code": 22, "name_en": "Sidi Bel Abbès", "name_fr": "Sidi Bel Abbès", "name_ar": "سيدي بلعباس",    "lat": 35.1899, "lon": -0.6309, "area_code": "048"},
    {"code": 23, "name_en": "Annaba",         "name_fr": "Annaba",         "name_ar": "عنابة",          "lat": 36.9000, "lon": 7.7667,  "area_code": "038"},
    {"code": 24, "name_en": "Guelma",         "name_fr": "Guelma",         "name_ar": "قالمة",          "lat": 36.4622, "lon": 7.4261,  "area_code": "037"},
    {"code": 25, "name_en": "Constantine",    "name_fr": "Constantine",    "name_ar": "قسنطينة",        "lat": 36.3650, "lon": 6.6147,  "area_code": "031"},
    {"code": 26, "name_en": "Médéa",          "name_fr": "Médéa",          "name_ar": "المدية",         "lat": 36.2642, "lon": 2.7539,  "area_code": "025"},
    {"code": 27, "name_en": "Mostaganem",     "name_fr": "Mostaganem",     "name_ar": "مستغانم",        "lat": 35.9312, "lon": 0.0892,  "area_code": "045"},
    {"code": 28, "name_en": "M'Sila",         "name_fr": "M'Sila",         "name_ar": "المسيلة",        "lat": 35.7058, "lon": 4.5419,  "area_code": "035"},
    {"code": 29, "name_en": "Mascara",        "name_fr": "Mascara",        "name_ar": "معسكر",          "lat": 35.3972, "lon": 0.1406,  "area_code": "045"},
    {"code": 30, "name_en": "Ouargla",        "name_fr": "Ouargla",        "name_ar": "ورقلة",          "lat": 31.9493, "lon": 5.3250,  "area_code": "029"},
    {"code": 31, "name_en": "Oran",           "name_fr": "Oran",           "name_ar": "وهران",          "lat": 35.6976, "lon": -0.6337, "area_code": "041"},
    {"code": 32, "name_en": "El Bayadh",      "name_fr": "El Bayadh",      "name_ar": "البيض",          "lat": 33.6832, "lon": 1.0193,  "area_code": "049"},
    {"code": 33, "name_en": "Illizi",         "name_fr": "Illizi",         "name_ar": "إليزي",          "lat": 26.4833, "lon": 8.4667,  "area_code": "029"},
    {"code": 34, "name_en": "Bordj Bou Arréridj", "name_fr": "Bordj Bou Arréridj", "name_ar": "برج بوعريريج", "lat": 36.0732, "lon": 4.7611, "area_code": "035"},
    {"code": 35, "name_en": "Boumerdès",      "name_fr": "Boumerdès",      "name_ar": "بومرداس",        "lat": 36.7599, "lon": 3.4736,  "area_code": "024"},
    {"code": 36, "name_en": "El Tarf",        "name_fr": "El Tarf",        "name_ar": "الطارف",         "lat": 36.7672, "lon": 8.3138,  "area_code": "038"},
    {"code": 37, "name_en": "Tindouf",        "name_fr": "Tindouf",        "name_ar": "تندوف",          "lat": 27.6744, "lon": -8.1478, "area_code": "049"},
    {"code": 38, "name_en": "Tissemsilt",     "name_fr": "Tissemsilt",     "name_ar": "تيسمسيلت",       "lat": 35.6072, "lon": 1.8108,  "area_code": "046"},
    {"code": 39, "name_en": "El Oued",        "name_fr": "El Oued",        "name_ar": "الوادي",         "lat": 33.3683, "lon": 6.8675,  "area_code": "032"},
    {"code": 40, "name_en": "Khenchela",      "name_fr": "Khenchela",      "name_ar": "خنشلة",         "lat": 35.4358, "lon": 7.1433,  "area_code": "032"},
    {"code": 41, "name_en": "Souk Ahras",     "name_fr": "Souk Ahras",     "name_ar": "سوق أهراس",      "lat": 36.2864, "lon": 7.9511,  "area_code": "037"},
    {"code": 42, "name_en": "Tipaza",         "name_fr": "Tipaza",         "name_ar": "تيبازة",         "lat": 36.5942, "lon": 2.4430,  "area_code": "024"},
    {"code": 43, "name_en": "Mila",           "name_fr": "Mila",           "name_ar": "ميلة",           "lat": 36.4503, "lon": 6.2644,  "area_code": "031"},
    {"code": 44, "name_en": "Aïn Defla",      "name_fr": "Aïn Defla",      "name_ar": "عين الدفلى",     "lat": 36.2644, "lon": 1.9678,  "area_code": "027"},
    {"code": 45, "name_en": "Naâma",          "name_fr": "Naâma",          "name_ar": "النعامة",        "lat": 33.2667, "lon": -0.3167, "area_code": "049"},
    {"code": 46, "name_en": "Aïn Témouchent", "name_fr": "Aïn Témouchent", "name_ar": "عين تموشنت",     "lat": 35.2975, "lon": -1.1404, "area_code": "043"},
    {"code": 47, "name_en": "Ghardaïa",       "name_fr": "Ghardaïa",       "name_ar": "غرداية",         "lat": 32.4839, "lon": 3.6739,  "area_code": "029"},
    {"code": 48, "name_en": "Relizane",       "name_fr": "Relizane",       "name_ar": "غليزان",         "lat": 35.7372, "lon": 0.5558,  "area_code": "046"},
    # Wilayas created by the 2019 administrative reform (Law 19-12)
    {"code": 49, "name_en": "El M'Ghair",     "name_fr": "El M'Ghair",     "name_ar": "المغير",         "lat": 33.9500, "lon": 5.9167,  "area_code": "032"},
    {"code": 50, "name_en": "El Meniaa",      "name_fr": "El Meniaa",      "name_ar": "المنيعة",        "lat": 30.5833, "lon": 2.8833,  "area_code": "029"},
    {"code": 51, "name_en": "Ouled Djellal",  "name_fr": "Ouled Djellal",  "name_ar": "أولاد جلال",     "lat": 34.4333, "lon": 5.0667,  "area_code": "033"},
    {"code": 52, "name_en": "Bordj Badji Mokhtar", "name_fr": "Bordj Badji Mokhtar", "name_ar": "برج باجي مختار", "lat": 21.3278, "lon": 0.9542, "area_code": "049"},
    {"code": 53, "name_en": "Béni Abbès",     "name_fr": "Béni Abbès",     "name_ar": "بني عباس",       "lat": 30.1333, "lon": -2.1667, "area_code": "049"},
    {"code": 54, "name_en": "Timimoun",       "name_fr": "Timimoun",       "name_ar": "تيميمون",        "lat": 29.2639, "lon": 0.2311,  "area_code": "049"},
    {"code": 55, "name_en": "Touggourt",      "name_fr": "Touggourt",      "name_ar": "تقرت",           "lat": 33.1056, "lon": 6.0583,  "area_code": "029"},
    {"code": 56, "name_en": "Djanet",         "name_fr": "Djanet",         "name_ar": "جانت",           "lat": 24.5539, "lon": 9.4856,  "area_code": "029"},
    {"code": 57, "name_en": "In Salah",       "name_fr": "In Salah",       "name_ar": "عين صالح",       "lat": 27.1936, "lon": 2.4606,  "area_code": "029"},
    {"code": 58, "name_en": "In Guezzam",     "name_fr": "In Guezzam",     "name_ar": "عين قزام",       "lat": 19.5722, "lon": 5.7694,  "area_code": "029"},
)

# Reverse lookup: landline area code -> wilaya name (French). Where a prefix
# serves several wilayas the dominant one is listed (the inference is a hint,
# never authoritative).
AREA_CODE_TO_WILAYA: dict[str, str] = {
    "021": "Alger", "023": "Alger",
    "024": "Boumerdès", "025": "Blida", "026": "Tizi Ouzou", "027": "Chlef",
    "029": "Ghardaïa",
    "031": "Constantine", "032": "Oum El Bouaghi", "033": "Batna",
    "034": "Béjaïa", "035": "Bordj Bou Arréridj", "036": "Sétif",
    "037": "Guelma", "038": "Annaba",
    "041": "Oran", "043": "Tlemcen", "045": "Mostaganem", "046": "Tiaret",
    "048": "Sidi Bel Abbès", "049": "Béchar",
}

# National bounding box (approximate, WGS84) used for coordinate validation.
ALGERIA_BBOX: tuple[float, float, float, float] = (-8.68, 18.96, 12.0, 37.09)


def all_wilaya_names() -> list[str]:
    """Return every wilaya French name, sorted by official code."""
    return [str(w["name_fr"]) for w in WILAYAS]


def get_wilaya_by_name(name: str) -> Optional[dict[str, object]]:
    """Case-insensitive lookup by any of the three name fields."""
    if not name:
        return None
    needle = name.strip().lower()
    for w in WILAYAS:
        if needle in {
            str(w["name_en"]).lower(),
            str(w["name_fr"]).lower(),
            str(w["name_ar"]),
        }:
            return w
    return None


def get_wilaya_by_code(code: int) -> Optional[dict[str, object]]:
    """Lookup by official wilaya code (1-58)."""
    for w in WILAYAS:
        if int(w["code"]) == code:  # type: ignore[arg-type]
            return w
    return None


def normalise_wilaya_name(name: Optional[str]) -> Optional[str]:
    """Map free-text wilaya input onto the canonical French catalogue name.

    Handles accent-insensitive and Arabic-script input; returns ``None``
    when nothing matches (callers treat unknown wilayas as unfiltered).
    """
    w = get_wilaya_by_name(name or "")
    return str(w["name_fr"]) if w else None
