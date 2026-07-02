"""Configuration package — every tunable parameter lives here.

The package exposes a single ``settings`` singleton (cached via
``functools.lru_cache``) plus a handful of static catalogues that never
change at runtime (wilayas, industries, dialect matrix, services).
"""

from config.settings import AppSettings, get_settings, settings
from config.wilayas import WILAYAS, all_wilaya_names, get_wilaya_by_name
from config.industries import INDUSTRIES, get_industry_by_key
from config.services_catalog import SERVICES_CATALOG
from config.dialect_matrix import ALGERIAN_DIALECT_MATRIX, lookup_dialect_variants
from config.proxies import PROXY_POOL, parse_proxy_list

__all__ = [
    "AppSettings",
    "get_settings",
    "settings",
    "WILAYAS",
    "all_wilaya_names",
    "get_wilaya_by_name",
    "INDUSTRIES",
    "get_industry_by_key",
    "SERVICES_CATALOG",
    "ALGERIAN_DIALECT_MATRIX",
    "lookup_dialect_variants",
    "PROXY_POOL",
    "parse_proxy_list",
]
