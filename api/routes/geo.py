"""Geographic API — wilaya catalogue, boundaries, and point lookup.

Backs the interactive Algeria map: the catalogue joins live lead/checkpoint
counts (SQL GROUP BY, never full-row loads), the boundaries endpoint
serves the versioned GeoJSON dataset for client-side rendering, and the
lookup endpoint resolves coordinates to a wilaya via the engine's
point-in-polygon index.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.dependencies import (
    get_checkpoint_repo,
    get_geo_service,
    get_lead_repo,
)
from engine.geo import WilayaGeoService
from infrastructure.storage.checkpoint_repo import CheckpointRepository
from infrastructure.storage.lead_repo import LeadRepository

geo_router = APIRouter(prefix="/api/v2/geo", tags=["geo"])


class GeoLookupRequest(BaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)


@geo_router.get("/wilayas")
async def list_geo_wilayas(
    leads_repo: LeadRepository = Depends(get_lead_repo),
    cp_repo: CheckpointRepository = Depends(get_checkpoint_repo),
    geo: WilayaGeoService = Depends(get_geo_service),
):
    """The 58-wilaya catalogue with live lead/checkpoint counts and
    geometry-derived centroids (aggregated in SQL, not row loads)."""
    leads_by_wilaya = await leads_repo.count_by_wilaya()
    cps_by_wilaya = await cp_repo.count_by_wilaya()
    return {
        "count": 58,
        "wilayas": geo.wilaya_catalogue(leads_by_wilaya, cps_by_wilaya),
    }


@geo_router.get("/boundaries")
async def get_boundaries(geo: WilayaGeoService = Depends(get_geo_service)):
    """Boundary geometry for client-side map rendering (WGS84 GeoJSON,
    58 features, ~113 KB — cached and immutable per dataset version)."""
    return geo.boundaries_geojson()


@geo_router.post("/lookup")
async def geo_lookup(
    payload: GeoLookupRequest,
    geo: WilayaGeoService = Depends(get_geo_service),
):
    """Resolve a coordinate to its wilaya (point-in-polygon; nearest-wilaya
    fallback with `approximate=true` for border/near-shore misses)."""
    hit = geo.lookup(payload.longitude, payload.latitude)
    if hit is not None:
        return {"found": True, "approximate": False, "wilaya": hit}
    nearest = geo.nearest_wilaya(payload.longitude, payload.latitude)
    if nearest is not None:
        return {"found": True, "approximate": True, "wilaya": nearest}
    return {"found": False, "approximate": False, "wilaya": None}


@geo_router.get("/overview")
async def geo_overview(
    leads_repo: LeadRepository = Depends(get_lead_repo),
    cp_repo: CheckpointRepository = Depends(get_checkpoint_repo),
    geo: WilayaGeoService = Depends(get_geo_service),
):
    """Country-level map summary in one round trip."""
    return {
        "wilayas": 58,
        "leads_geolocated": await leads_repo.count_geolocated(),
        "checkpoints": await cp_repo.count(),
        "bbox": {
            "min_lon": geo.algeria_bbox[0],
            "min_lat": geo.algeria_bbox[1],
            "max_lon": geo.algeria_bbox[2],
            "max_lat": geo.algeria_bbox[3],
        },
        "center": {"lat": 28.0, "lon": 2.65},
    }
