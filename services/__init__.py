"""Services package — high-level orchestration of business workflows.

Services sit between the API layer and the infrastructure layer. They
contain *business logic* (what to do, in what order, with what
fallbacks) and depend only on the abstractions in ``core.interfaces``.
"""

from services.discovery_service import DiscoveryService
from services.analysis_service import AnalysisService
from services.scoring_service import ScoringService
from services.resolution_service import ResolutionService
from services.export_service import ExportService
from services.infinite_crawler import AutonomousInfiniteCrawler

__all__ = [
    "DiscoveryService",
    "AnalysisService",
    "ScoringService",
    "ResolutionService",
    "ExportService",
    "AutonomousInfiniteCrawler",
]
