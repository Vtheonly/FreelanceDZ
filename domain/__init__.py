"""Domain package — pure business models, free of I/O or framework concerns.

Anything that touches the network, the database, or external services
belongs in ``infrastructure`` or ``services``. This package only defines
*what* the data looks like and *what* the rules are.
"""

from domain.enums import (
    CrawlStatus,
    DataSource,
    EntityType,
    FreshnessAge,
    LeadStatus,
    PhoneType,
    ProxyHealthState,
    ResolutionStrategy,
)
from domain.models import (
    BusinessRaw,
    CrawlTask,
    Lead,
    LeadAnalysis,
    ProposedService,
    ProxyNode,
    RawRecord,
    ResolvedEntity,
)
from domain.value_objects import (
    Contact,
    FreshnessMetadata,
    GeoPoint,
    PhoneDetails,
)

__all__ = [
    # enums
    "CrawlStatus",
    "DataSource",
    "EntityType",
    "FreshnessAge",
    "LeadStatus",
    "PhoneType",
    "ProxyHealthState",
    "ResolutionStrategy",
    # value objects
    "Contact",
    "FreshnessMetadata",
    "GeoPoint",
    "PhoneDetails",
    # models
    "BusinessRaw",
    "CrawlTask",
    "Lead",
    "LeadAnalysis",
    "ProposedService",
    "ProxyNode",
    "RawRecord",
    "ResolvedEntity",
]
