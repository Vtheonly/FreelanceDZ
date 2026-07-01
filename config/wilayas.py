"""All 58 Algerian wilayas (post-2021 administrative reform).

Source: official Algerian administrative division (Décret exécutif 19-02).
Each entry: (code, name_en, name_fr, name_ar).
"""

from __future__ import annotations

from typing import Dict, List

from domain.models import Wilaya


# Tuple of tuples for compactness; converted into Wilaya objects below.
_WILAYA_TUPLES = (
    (1,  "Adrar",            "Adrar",            "أدرار"),
    (2,  "Chlef",            "Chlef",            "الشلف"),
    (3,  "Laghouat",         "Laghouat",         "الأغواط"),
    (4,  "Oum El Bouaghi",   "Oum El Bouaghi",   "أم البواقي"),
    (5,  "Batna",            "Batna",            "باتنة"),
    (6,  "Bejaia",           "Béjaïa",           "بجاية"),
    (7,  "Biskra",           "Biskra",           "بسكرة"),
    (8,  "Bechar",           "Béchar",           "بشار"),
    (9,  "Blida",            "Blida",            "البليدة"),
    (10, "Bouira",           "Bouira",           "البويرة"),
    (11, "Tamanrasset",      "Tamanrasset",      "تمنراست"),
    (12, "Tebessa",          "Tébessa",          "تبسة"),
    (13, "Tlemcen",          "Tlemcen",          "تلمسان"),
    (14, "Tiaret",           "Tiaret",           "تيارت"),
    (15, "Tizi Ouzou",       "Tizi Ouzou",       "تيزي وزو"),
    (16, "Algiers",          "Alger",            "الجزائر"),
    (17, "Djelfa",           "Djelfa",           "الجلفة"),
    (18, "Jijel",            "Jijel",            "جيجل"),
    (19, "Setif",            "Sétif",            "سطيف"),
    (20, "Saida",            "Saïda",            "سعيدة"),
    (21, "Skikda",           "Skikda",           "سكيكدة"),
    (22, "Sidi Bel Abbes",   "Sidi Bel Abbès",   "سيدي بلعباس"),
    (23, "Annaba",           "Annaba",           "عنابة"),
    (24, "Guelma",           "Guelma",           "قالمة"),
    (25, "Constantine",      "Constantine",      "قسنطينة"),
    (26, "Medea",            "Médéa",            "المدية"),
    (27, "Mostaganem",       "Mostaganem",       "مستغانم"),
    (28, "M'Sila",           "M'Sila",           "المسيلة"),
    (29, "Mascara",          "Mascara",          "معسكر"),
    (30, "Ouargla",          "Ouargla",          "ورقلة"),
    (31, "Oran",             "Oran",             "وهران"),
    (32, "El Bayadh",        "El Bayadh",        "البيض"),
    (33, "Illizi",           "Illizi",           "إليزي"),
    (34, "Bordj Bou Arreridj","Bordj Bou Arréridj","برج بوعريريج"),
    (35, "Boumerdes",        "Boumerdès",        "بومرداس"),
    (36, "El Tarf",          "El Tarf",          "الطارف"),
    (37, "Tindouf",          "Tindouf",          "تندوف"),
    (38, "Tissemsilt",       "Tissemsilt",       "تيسمسيلت"),
    (39, "El Oued",          "El Oued",          "الوادي"),
    (40, "Khenchela",        "Khenchela",        "خنشلة"),
    (41, "Souk Ahras",       "Souk Ahras",       "سوق أهراس"),
    (42, "Tipaza",           "Tipaza",           "تيبازة"),
    (43, "Mila",             "Mila",             "ميلة"),
    (44, "Ain Defla",        "Aïn Defla",        "عين الدفلى"),
    (45, "Naama",            "Naâma",            "النعامة"),
    (46, "Ain Temouchent",   "Aïn Témouchent",   "عين تموشنت"),
    (47, "Ghardaia",         "Ghardaïa",         "غرداية"),
    (48, "Relizane",         "Relizane",         "غليزان"),
    (49, "Timimoun",         "Timimoun",         "تيميمون"),
    (50, "Bordj Badji Mokhtar","Bordj Badji Mokhtar","برج باجي مختار"),
    (51, "Ouled Djellal",    "Ouled Djellal",    "أولاد جلال"),
    (52, "Beni Abbes",       "Béni Abbès",       "بني عباس"),
    (53, "In Salah",         "In Salah",         "عين صالح"),
    (54, "In Guezzam",       "In Guezzam",       "عين قزام"),
    (55, "Touggourt",        "Touggourt",        "تقرت"),
    (56, "Djanet",           "Djanet",           "جانت"),
    (57, "El M'Ghair",       "El M'Ghair",       "المغير"),
    (58, "El Meniaa",        "El Meniaa",        "المنيعة"),
)


WILAYAS: List[Wilaya] = [
    Wilaya(code=c, name_en=en, name_fr=fr, name_ar=ar)
    for (c, en, fr, ar) in _WILAYA_TUPLES
]

# Fast lookup maps for runtime use.
WILAYA_BY_NAME_EN: Dict[str, Wilaya] = {w.name_en.lower(): w for w in WILAYAS}
WILAYA_BY_NAME_FR: Dict[str, Wilaya] = {w.name_fr.lower(): w for w in WILAYAS}
WILAYA_BY_CODE: Dict[int, Wilaya] = {w.code: w for w in WILAYAS}


def all_wilaya_names() -> List[str]:
    """Return English names of all 58 wilayas (sorted by code)."""
    return [w.name_en for w in WILAYAS]


def resolve_wilaya(name: str) -> Wilaya:
    """Resolve a wilaya name (EN/FR/AR, case-insensitive) to its Wilaya object.

    Raises:
        KeyError: if the name does not match any wilaya.
    """
    key = name.strip().lower()
    if key in WILAYA_BY_NAME_EN:
        return WILAYA_BY_NAME_EN[key]
    if key in WILAYA_BY_NAME_FR:
        return WILAYA_BY_NAME_FR[key]
    # Try Arabic lookup
    for w in WILAYAS:
        if w.name_ar == name.strip():
            return w
    raise KeyError(f"Unknown wilaya: {name!r}")


# Approximate bounding boxes (south, west, north, east) for the largest wilayas.
# Used by the Overpass scraper to focus queries. (Coordinates are rough.)
WILAYA_BBOXES: Dict[str, tuple] = {
    "Algiers":     (36.65, 2.90, 36.85, 3.20),
    "Oran":        (35.55, -0.80, 35.85, -0.45),
    "Constantine": (36.25, 6.45, 36.45, 6.75),
    "Annaba":      (36.80, 7.65, 37.10, 8.00),
    "Blida":       (36.30, 2.70, 36.60, 3.10),
    "Setif":       (36.05, 5.10, 36.30, 5.50),
    "Tizi Ouzou":  (36.45, 3.70, 36.80, 4.30),
    "Bejaia":      (36.40, 4.80, 36.80, 5.30),
    "Tlemcen":     (34.70, -1.50, 35.10, -1.10),
    "Batna":       (35.40, 6.00, 35.70, 6.40),
}
