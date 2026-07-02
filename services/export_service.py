"""Export service — write leads / entities to CSV and JSON files.

Produces clean, timestamped exports in ``data/exports/`` so users can
pull data into Excel, a CRM, or another pipeline.
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config.settings import get_settings
from core.interfaces import ILeadRepository, IResolvedEntityRepository


_logger = logging.getLogger("services.export")


class ExportService:
    """Export leads and resolved entities to disk."""

    def __init__(
        self,
        lead_repo: ILeadRepository,
        resolved_repo: IResolvedEntityRepository,
        export_dir: Optional[Path] = None,
    ) -> None:
        self._lead_repo = lead_repo
        self._resolved_repo = resolved_repo
        self._export_dir = export_dir or get_settings().resolved_export_dir
        self._export_dir.mkdir(parents=True, exist_ok=True)

    async def export_leads_csv(self, limit: int = 1000) -> Path:
        """Export the top ``limit`` leads to a CSV file. Returns the path."""
        leads = await self._lead_repo.list_leads(min_score=0.0, limit=limit)
        path = self._export_dir / f"leads_{_timestamp()}.csv"
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "id", "name", "industry", "wilaya", "address", "website",
                "phone", "email", "rating", "review_count", "source",
                "priority_score", "status", "freshness", "discovered_at",
            ])
            for lead in leads:
                biz = lead.business
                writer.writerow([
                    lead.id, biz.name, biz.industry, biz.wilaya, biz.address,
                    biz.website, biz.phone, biz.email, biz.rating, biz.review_count,
                    biz.source.value, lead.priority_score, lead.status.value,
                    biz.freshness.calculated_age_class.value,
                    biz.discovered_at.isoformat() if biz.discovered_at else "",
                ])
        _logger.info("Exported %d leads to %s", len(leads), path)
        return path

    async def export_leads_json(self, limit: int = 1000) -> Path:
        """Export leads to a JSON file. Returns the path."""
        leads = await self._lead_repo.list_leads(min_score=0.0, limit=limit)
        path = self._export_dir / f"leads_{_timestamp()}.json"
        payload = [
            {
                "id": lead.id,
                "business": lead.business.model_dump(mode="json"),
                "priority_score": lead.priority_score,
                "status": lead.status.value,
                "tags": lead.tags,
                "analysis": lead.analysis.model_dump(mode="json") if lead.analysis else None,
            }
            for lead in leads
        ]
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        _logger.info("Exported %d leads to %s", len(leads), path)
        return path

    async def export_entities_json(self, limit: int = 1000) -> Path:
        """Export resolved entities to a JSON file. Returns the path."""
        entities = await self._resolved_repo.list_all(min_confidence=0.0, limit=limit)
        path = self._export_dir / f"entities_{_timestamp()}.json"
        payload = [e.model_dump(mode="json") for e in entities]
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        _logger.info("Exported %d entities to %s", len(entities), path)
        return path


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
