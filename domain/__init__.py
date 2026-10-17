"""Domain layer — pure models, enums, and value objects."""

from domain.enums import (
    CrawlStatus,
    DataSource,
    FreshnessAge,
    LeadStatus,
    PhoneType,
    ProxyHealthState,
    ResolutionStrategy,
)
from domain.models import CrawlTask, Lead
from domain.value_objects import FreshnessMetadata, PhoneDetails

__all__ = [
    "CrawlStatus",
    "CrawlTask",
    "DataSource",
    "FreshnessAge",
    "FreshnessMetadata",
    "Lead",
    "LeadStatus",
    "PhoneDetails",
    "PhoneType",
    "ProxyHealthState",
    "ResolutionStrategy",
]
