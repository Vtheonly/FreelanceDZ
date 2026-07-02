"""Static catalogue of Algeria's 58 wilayas.

Each wilaya carries its code (1–58) and its name in English, French, and
Arabic. The catalogue is a tuple of dataclass-like dicts so it remains
immutable and hashable.

Sources: official Algerian administrative division (2021 reform, 58 wilayas).
"""

from __future__ import annotations

from typing import Optional


WILAYAS: tuple[dict[str, object], ...] = (
    {"code": 1,  "name_en": "Adrar",          "name_fr": "Adrar",          "name_ar": "أدرار"},
    {"code": 2,  "name_en": "Chlef",          "name_fr": "Chlef",          "name_ar": "الشلف"},
    {"code": 3,  "name_en": "Laghouat",       "name_fr": "Laghouat",       "name_ar": "الأغواط"},
    {"code": 4,  "name_en": "Oum El Bouaghi", "name_fr": "Oum El Bouaghi", "name_ar": "أم البواقي"},
    {"code": 5,  "name_en": "Batna",          "name_fr": "Batna",          "name_ar": "باتنة"},
    {"code": 6,  "name_en": "Béjaïa",         "name_fr": "Béjaïa",         "name_ar": "بجاية"},
    {"code": 7,  "name_en": "Biskra",         "name_fr": "Biskra",         "name_ar": "بسكرة"},
    {"code": 8,  "name_en": "Béchar",         "name_fr": "Béchar",         "name_ar": "بشار"},
    {"code": 9,  "name_en": "Blida",          "name_fr": "Blida",          "name_ar": "البليدة"},
    {"code": 10, "name_en": "Bouira",         "name_fr": "Bouira",         "name_ar": "البويرة"},
    {"code": 11, "name_en": "Tamanrasset",    "name_fr": "Tamanrasset",    "name_ar": "تمنراست"},
    {"code": 12, "name_en": "Tébessa",        "name_fr": "Tébessa",        "name_ar": "تبسة"},
    {"code": 13, "name_en": "Tlemcen",        "name_fr": "Tlemcen",        "name_ar": "تلمسان"},
    {"code": 14, "name_en": "Tiaret",         "name_fr": "Tiaret",         "name_ar": "تيارت"},
    {"code": 15, "name_en": "Tizi Ouzou",     "name_fr": "Tizi Ouzou",     "name_ar": "تيزي وزو"},
    {"code": 16, "name_en": "Algiers",        "name_fr": "Alger",          "name_ar": "الجزائر"},
    {"code": 17, "name_en": "Djelfa",         "name_fr": "Djelfa",         "name_ar": "الجلفة"},
    {"code": 18, "name_en": "Jijel",          "name_fr": "Jijel",          "name_ar": "جيجل"},
    {"code": 19, "name_en": "Sétif",          "name_fr": "Sétif",          "name_ar": "سطيف"},
    {"code": 20, "name_en": "Saïda",          "name_fr": "Saïda",          "name_ar": "سعيدة"},
    {"code": 21, "name_en": "Skikda",         "name_fr": "Skikda",         "name_ar": "سكيكدة"},
    {"code": 22, "name_en": "Sidi Bel Abbès", "name_fr": "Sidi Bel Abbès", "name_ar": "سيدي بلعباس"},
    {"code": 23, "name_en": "Annaba",         "name_fr": "Annaba",         "name_ar": "عنابة"},
    {"code": 24, "name_en": "Guelma",         "name_fr": "Guelma",         "name_ar": "قالمة"},
    {"code": 25, "name_en": "Constantine",    "name_fr": "Constantine",    "name_ar": "قسنطينة"},
    {"code": 26, "name_en": "Médéa",          "name_fr": "Médéa",          "name_ar": "المدية"},
    {"code": 27, "name_en": "Mostaganem",     "name_fr": "Mostaganem",     "name_ar": "مستغانم"},
    {"code": 28, "name_en": "M'Sila",         "name_fr": "M'Sila",         "name_ar": "المسيلة"},
    {"code": 29, "name_en": "Mascara",        "name_fr": "Mascara",        "name_ar": "معسكر"},
    {"code": 30, "name_en": "Ouargla",        "name_fr": "Ouargla",        "name_ar": "ورقلة"},
    {"code": 31, "name_en": "Oran",           "name_fr": "Oran",           "name_ar": "وهران"},
    {"code": 32, "name_en": "El Bayadh",      "name_fr": "El Bayadh",      "name_ar": "البيض"},
    {"code": 33, "name_en": "Illizi",         "name_fr": "Illizi",         "name_ar": "إليزي"},
    {"code": 34, "name_en": "Bordj Bou Arréridj", "name_fr": "Bordj Bou Arréridj", "name_ar": "برج بوعريريج"},
    {"code": 35, "name_en": "Boumerdès",      "name_fr": "Boumerdès",      "name_ar": "بومرداس"},
    {"code": 36, "name_en": "El Tarf",        "name_fr": "El Tarf",        "name_ar": "الطارف"},
    {"code": 37, "name_en": "Tindouf",        "name_fr": "Tindouf",        "name_ar": "تندوف"},
    {"code": 38, "name_en": "Tissemsilt",     "name_fr": "Tissemsilt",     "name_ar": "تيسمسيلت"},
    {"code": 39, "name_en": "El Oued",        "name_fr": "El Oued",        "name_ar": "الوادي"},
    {"code": 40, "name_en": "Khenchela",      "name_fr": "Khenchela",      "name_ar": "خنشلة"},
    {"code": 41, "name_en": "Souk Ahras",     "name_fr": "Souk Ahras",     "name_ar": "سوق أهراس"},
    {"code": 42, "name_en": "Tipaza",         "name_fr": "Tipaza",         "name_ar": "تيبازة"},
    {"code": 43, "name_en": "Mila",           "name_fr": "Mila",           "name_ar": "ميلة"},
    {"code": 44, "name_en": "Aïn Defla",      "name_fr": "Aïn Defla",      "name_ar": "عين الدفلى"},
    {"code": 45, "name_en": "Naâma",          "name_fr": "Naâma",          "name_ar": "النعامة"},
    {"code": 46, "name_en": "Aïn Témouchent", "name_fr": "Aïn Témouchent", "name_ar": "عين تموشنت"},
    {"code": 47, "name_en": "Ghardaïa",       "name_fr": "Ghardaïa",       "name_ar": "غرداية"},
    {"code": 48, "name_en": "Relizane",       "name_fr": "Relizane",       "name_ar": "غليزان"},
    # New wilayas created by the 2019/2021 administrative reform
    {"code": 49, "name_en": "El M'Ghair",     "name_fr": "El M'Ghair",     "name_ar": "المغير"},
    {"code": 50, "name_en": "El Meniaa",      "name_fr": "El Meniaa",      "name_ar": "المنيعة"},
    {"code": 51, "name_en": "Ouled Djellal",  "name_fr": "Ouled Djellal",  "name_ar": "أولاد جلال"},
    {"code": 52, "name_en": "Bordj Badji Mokhtar", "name_fr": "Bordj Badji Mokhtar", "name_ar": "برج باجي مختار"},
    {"code": 53, "name_en": "Béni Abbès",     "name_fr": "Béni Abbès",     "name_ar": "بني عباس"},
    {"code": 54, "name_en": "Timimoun",       "name_fr": "Timimoun",       "name_ar": "تيميمون"},
    {"code": 55, "name_en": "Touggourt",      "name_fr": "Touggourt",      "name_ar": "تقرت"},
    {"code": 56, "name_en": "Djanet",         "name_fr": "Djanet",         "name_ar": "جانت"},
    {"code": 57, "name_en": "In Salah",       "name_fr": "In Salah",       "name_ar": "عين صالح"},
    {"code": 58, "name_en": "In Guezzam",     "name_fr": "In Guezzam",     "name_ar": "عين قزام"},
)


def all_wilaya_names() -> list[str]:
    """Return every wilaya English name, sorted by code."""
    return [str(w["name_en"]) for w in WILAYAS]


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
