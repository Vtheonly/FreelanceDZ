"""Checkpoint (POI) API — field operations on persisted geographic records.

Full CRUD over ``checkpoints`` (migration 10). Coordinates are validated
against the real wilaya geometry on create: the wilaya field is filled
from the point-in-polygon result when the caller does not supply one, and
mismatches are reported rather than silently accepted.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from api.dependencies import get_checkpoint_repo, get_geo_service
from config.wilayas import normalise_wilaya_name
from domain.models import Checkpoint
from engine.geo import WilayaGeoService
from infrastructure.storage.checkpoint_repo import CheckpointRepository

checkpoints_router = APIRouter(prefix="/api/v2/checkpoints", tags=["checkpoints"])

CATEGORIES = ("prospect", "client", "partner", "hub", "competitor")
STATUSES = ("active", "visited", "archived")


class CheckpointCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(default="prospect", pattern="^(prospect|client|partner|hub|competitor)$")
    wilaya: str = Field(default="", max_length=100)
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    notes: Optional[str] = Field(default=None, max_length=1000)
    status: str = Field(default="active", pattern="^(active|visited|archived)$")


class CheckpointUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    category: Optional[str] = Field(default=None, pattern="^(prospect|client|partner|hub|competitor)$")
    wilaya: Optional[str] = Field(default=None, max_length=100)
    latitude: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    longitude: Optional[float] = Field(default=None, ge=-180.0, le=180.0)
    notes: Optional[str] = Field(default=None, max_length=1000)
    status: Optional[str] = Field(default=None, pattern="^(active|visited|archived)$")


@checkpoints_router.get("")
async def list_checkpoints(
    wilaya: Optional[str] = Query(None),
    category: Optional[str] = Query(None, pattern="^(prospect|client|partner|hub|competitor)$"),
    status: Optional[str] = Query(None, pattern="^(active|visited|archived)$"),
    limit: int = Query(1000, ge=1, le=5000),
    repo: CheckpointRepository = Depends(get_checkpoint_repo),
):
    normalised = normalise_wilaya_name(wilaya) if wilaya else None
    items = await repo.list_checkpoints(
        wilaya=normalised, category=category, status=status, limit=limit
    )
    return {"count": len(items), "checkpoints": [cp.model_dump(mode="json") for cp in items]}


@checkpoints_router.post("", status_code=201)
async def create_checkpoint(
    payload: CheckpointCreate,
    repo: CheckpointRepository = Depends(get_checkpoint_repo),
    geo: WilayaGeoService = Depends(get_geo_service),
):
    # Wilaya resolution: caller-provided value wins; otherwise derive it
    # from the real boundary geometry at these coordinates. Coastal/offshore
    # points can fall just outside the simplified boundary — the nearest
    # wilaya then applies (ports are the canonical checkpoint).
    wilaya = normalise_wilaya_name(payload.wilaya) if payload.wilaya else None
    derived = geo.lookup(payload.longitude, payload.latitude)
    if derived is None:
        nearest = geo.nearest_wilaya(payload.longitude, payload.latitude)
        derived = nearest if nearest else None
    geometry_wilaya = derived["name_fr"] if derived else None
    if wilaya is None:
        wilaya = geometry_wilaya or ""
    elif geometry_wilaya and wilaya != geometry_wilaya:
        # Report the mismatch instead of silently storing wrong geography.
        raise HTTPException(
            status_code=422,
            detail=(
                f"coordinates fall inside wilaya '{geometry_wilaya}' but the "
                f"request names '{wilaya}' — set wilaya to match or omit it"
            ),
        )

    cp = Checkpoint(
        name=payload.name,
        category=payload.category,
        wilaya=wilaya,
        latitude=payload.latitude,
        longitude=payload.longitude,
        notes=payload.notes,
        status=payload.status,
    )
    new_id = await repo.create(cp)
    return {"ok": True, "id": new_id, "wilaya": wilaya, "geometry_wilaya": geometry_wilaya}


@checkpoints_router.get("/{cp_id}")
async def get_checkpoint(cp_id: int, repo: CheckpointRepository = Depends(get_checkpoint_repo)):
    cp = await repo.get(cp_id)
    if not cp:
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    return cp.model_dump(mode="json")


@checkpoints_router.patch("/{cp_id}")
async def update_checkpoint(
    cp_id: int,
    payload: CheckpointUpdate,
    repo: CheckpointRepository = Depends(get_checkpoint_repo),
    geo: WilayaGeoService = Depends(get_geo_service),
):
    existing = await repo.get(cp_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Checkpoint not found")

    fields = payload.model_dump(exclude_unset=True)

    # Moving a checkpoint re-derives its wilaya from the new geometry.
    new_lat = fields.get("latitude", existing.latitude)
    new_lon = fields.get("longitude", existing.longitude)
    if "latitude" in fields or "longitude" in fields:
        derived = geo.lookup(new_lon, new_lat)
        if derived:
            fields["wilaya"] = derived["name_fr"]

    if "wilaya" in fields and fields["wilaya"]:
        fields["wilaya"] = normalise_wilaya_name(fields["wilaya"]) or fields["wilaya"]

    updated = await repo.update(cp_id, **fields)
    if not updated:
        raise HTTPException(status_code=404, detail="Checkpoint not found or no changes made")
    return {"ok": True}


@checkpoints_router.delete("/{cp_id}")
async def delete_checkpoint(cp_id: int, repo: CheckpointRepository = Depends(get_checkpoint_repo)):
    deleted = await repo.delete(cp_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    return {"ok": True}
