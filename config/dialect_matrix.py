"""Algerian dialect matrix — FR / MSA / Darja keyword variants per industry.

The matrix is the *offline* fallback for the query expander. When the LLM
is unavailable or returns malformed output, the expander falls back to
these curated variants so the scraper still benefits from multi-language
coverage.

Each entry maps a canonical English/French key to three lists:
  * ``fr``    — professional French terminology used in Algeria.
  * ``ar``    — Modern Standard Arabic (MSA) equivalents.
  * ``darja`` — Algerian Arabic (Darja) colloquial variants in Latin script
                (Arabizi) or Arabic script.

Adding a new industry here automatically makes it discoverable by the
query expander — no code changes required.
"""

from __future__ import annotations

from typing import Optional


ALGERIAN_DIALECT_MATRIX: dict[str, dict[str, list[str]]] = {
    "pharmacie": {
        "fr": ["pharmacie", "officine", "parapharmacie", "laboratoire pharmacie"],
        "ar": ["صيدلية", "صيدليات", "شبه صيدلية"],
        "darja": ["farmasi", "farmaci", "صيدلية المناوبة", "صيدلية ليلية"],
    },
    "climatisation": {
        "fr": ["climatisation", "frigoriste", "chauffage central", "climatiseurs", "ventilation"],
        "ar": ["تبريد وتكييف", "تكييف الهواء", "تركيب المكيفات"],
        "darja": ["klimatizasyon", "chuffaj central", "frigoriste", "كليماتيزور"],
    },
    "menuiserie aluminium": {
        "fr": ["menuiserie aluminium", "fenêtres alu", "façadier aluminium", "extrusion aluminium"],
        "ar": ["نجارة الألمنيوم", "ورشة ألمنيوم", "مخزن ألمنيوم"],
        "darja": ["menuiserie aluminuim", "aluminium chabak", "المنيوم ميلة", "شبابيك ألمنيوم"],
    },
    "tolier": {
        "fr": ["tolier carrossier", "carrosserie automobile", "peinture automobile", "débosselage"],
        "ar": ["دهان السيارات", "تصليح هيكل السيارات", "سمكرة السيارات"],
        "darja": ["tolri", "tolri tomobila", "sabgha tomobil", "طولري طوموبيلات"],
    },
    "supermarche": {
        "fr": ["supermarché", "supérette", "alimentation générale", "grossiste alimentation"],
        "ar": ["سوبرماركت", "محل مواد غذائية", "بيع المواد الغذائية بالجملة"],
        "darja": ["superette", "hanout mida", "grossiste", "حانوت بيع المواد الغذائية"],
    },
    "restaurant": {
        "fr": ["restaurant", "snack", "fast-food", "traiteur", "pizzeria"],
        "ar": ["مطعم", "وجبات سريعة", "بيتزا"],
        "darja": ["resto", "snack", "fast food", "مطعم"],
    },
    "logistics": {
        "fr": ["logistique", "transport de marchandises", "transit", "fret", "commissionnaire"],
        "ar": ["النقل واللوجستيك", "شحن البضائع", "ترانزيت"],
        "darja": ["logistique", "transport marchandises", "ترانسيت", "شحن بضاعة"],
    },
    "clinique": {
        "fr": ["clinique", "cabinet médical", "centre de santé", "laboratoire d'analyses"],
        "ar": ["عيادة", "مركز صحي", "مختبر تحاليل"],
        "darja": ["klinique", "cabinet toubib", "مرقص صحي"],
    },
    "avocat": {
        "fr": ["avocat", "cabinet juridique", "conseil juridique", "huissier"],
        "ar": ["محامي", "مكتب محاماة", "استشارات قانونية"],
        "darja": ["avocat", "cabinet juridique", "محامي"],
    },
    "immobilier": {
        "fr": ["agence immobilière", "promoteur immobilier", "location", "vente immobilière"],
        "ar": ["وكالة عقارية", "مروج عقاري", "كراء وبيع"],
        "darja": ["agence immobilire", "immobilier", "promotion immobilière"],
    },
    "automobile": {
        "fr": ["concessionnaire automobile", "garage automobile", "pièces détachées", "mécanique auto"],
        "ar": ["وكيل سيارات", "كراج سيارات", "قطع غيار"],
        "darja": ["concessionnaire auto", "garage", "pièces détachées", "ميكونيسيان"],
    },
    "construction": {
        "fr": ["entreprise BTP", "génie civil", "travaux publics", "maçonnerie", "béton armé"],
        "ar": ["مقاولة بناء", "أشغال عمومية", "بناء مدني"],
        "darja": ["entreprise BTP", "travaux", "maçonnerie", "بي تي بي"],
    },
    "coiffure": {
        "fr": ["salon de coiffure", "barbier", "institut de beauté"],
        "ar": ["صالون حلاقة", "حلاق", "مركز تجميل"],
        "darja": ["salon coiffure", "barbier", "coiffeur", "صالون حلاقة"],
    },
    "boulangerie": {
        "fr": ["boulangerie", "pâtisserie", "viennoiserie"],
        "ar": ["مخبزة", "حلويات"],
        "darja": ["boulangerie", "pâtisserie", "خباز"],
    },
}


def lookup_dialect_variants(query: str) -> Optional[dict[str, list[str]]]:
    """Return the dialect matrix entry whose key or any variant matches ``query``.

    Matching is case-insensitive and substring-based so a query of
    ``"pharma"`` still hits the ``"pharmacie"`` entry.
    """
    if not query:
        return None
    needle = query.lower().strip()
    for key, lang_map in ALGERIAN_DIALECT_MATRIX.items():
        if needle in key:
            return lang_map
        for variants in lang_map.values():
            if any(needle in v.lower() for v in variants):
                return lang_map
    return None
