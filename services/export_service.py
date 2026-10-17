"""Export service — CSV/JSON snapshots of leads and clusters.

v3 fix: file I/O is offloaded to a worker thread (v2 wrote files directly
on the event loop).
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from config.settings import get_settings
from infrastructure.storage.cluster_repo import ClusterRepository
from infrastructure.storage.lead_repo import LeadRepository

logger = logging.getLogger("services.export")

CSV_COLUMNS = (
    "id", "name", "industry", "wilaya", "phone", "email", "website", "address",
    "priority_score", "digital_score", "status", "tags", "source",
    "discovered_at",
)


class ExportService:
    def __init__(
        self,
        repo: LeadRepository,
        clusters: ClusterRepository,
        export_dir: Optional[Path] = None,
    ) -> None:
        self._repo = repo
        self._clusters = clusters
        self._dir = export_dir or get_settings().resolved_export_dir

    async def export_leads_csv(self, limit: int = 1000) -> Path:
        leads = await self._repo.list_leads(limit=limit, exclude_rejected=False)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = self._dir / f"leads_{stamp}.csv"

        def _write() -> Path:
            with path.open("w", newline="", encoding="utf-8-sig") as fh:
                writer = csv.writer(fh)
                writer.writerow(CSV_COLUMNS)
                for l in leads:
                    writer.writerow([
                        l.id, l.name, l.industry, l.wilaya, l.phone or "",
                        l.email or "", l.website or "", l.address or "",
                        l.priority_score, l.digital_score if l.digital_score is not None else "",
                        l.status.value, ";".join(l.tags), l.source.value,
                        l.discovered_at.isoformat(),
                    ])
            return path

        result = await asyncio.to_thread(_write)
        logger.info("Exported %d leads to %s", len(leads), result)
        return result

    async def export_leads_json(self, limit: int = 1000) -> Path:
        leads = await self._repo.list_leads(limit=limit, exclude_rejected=False)
        payload = [l.model_dump(mode="json") for l in leads]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = self._dir / f"leads_{stamp}.json"

        def _write() -> Path:
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            return path

        result = await asyncio.to_thread(_write)
        logger.info("Exported %d leads to %s", len(leads), result)
        return result

    async def export_clusters_json(self, limit: int = 1000) -> Path:
        clusters = await self._clusters.list_clusters(limit=limit)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        path = self._dir / f"entities_{stamp}.json"

        def _write() -> Path:
            path.write_text(
                json.dumps(clusters, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
            return path

        result = await asyncio.to_thread(_write)
        return result
