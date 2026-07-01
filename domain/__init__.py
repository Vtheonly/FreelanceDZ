"""DZ Sales Intelligence — Domain Models.

Pure data structures (Pydantic v2) shared across all layers.
No I/O, no external dependencies beyond pydantic.
"""

from domain.models import (  # noqa: F401
    BusinessRaw,
    ProposedService,
    LeadAnalysis,
    Lead,
    LeadStatus,
    Wilaya,
    IndustryTemplate,
    DataSource,
)
