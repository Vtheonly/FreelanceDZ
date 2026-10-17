"""Configuration package — settings singleton plus static domain catalogues."""

from config.settings import AppSettings, get_settings
from config.wilayas import WILAYAS, all_wilaya_names, get_wilaya_by_name
from config.industries import INDUSTRIES, get_industry_by_key
from config.services_catalog import SERVICES_CATALOG
from config.dialect_matrix import ALGERIAN_DIALECT_MATRIX, lookup_dialect_variants

__all__ = [
    "AppSettings",
    "get_settings",
    "WILAYAS",
    "all_wilaya_names",
    "get_wilaya_by_name",
    "INDUSTRIES",
    "get_industry_by_key",
    "SERVICES_CATALOG",
    "ALGERIAN_DIALECT_MATRIX",
    "lookup_dialect_variants",
]
