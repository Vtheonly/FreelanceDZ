"""Engine HTTP client — the UI's single integration surface.

Design contract (refactorv5 §7, user task §4):

    * The UI calls the same public API any other client would call; it
      never imports repositories, the database, or engine internals.
    * Read helpers are cached with TTLs so Streamlit reruns (every widget
      interaction) do NOT re-hit the engine — the expensive data stays
      client-side and invalidation happens only on mutations.
    * Every failure mode surfaces as a typed, catchable error so panels
      can render a clean error state instead of crashing the app.

Caching rules are deliberate: boundaries are immutable per dataset
version (no TTL), the catalogue changes only on writes (cleared
explicitly), stats/leads/campaigns carry short TTLs, and the health probe
is never cached.
"""

from __future__ import annotations

import os
from typing import Any, Optional

import httpx
import streamlit as st

DEFAULT_ENGINE_URL = "http://localhost:8080"
_TIMEOUT = httpx.Timeout(30.0, connect=5.0)
_DISCOVER_TIMEOUT = httpx.Timeout(180.0, connect=5.0)  # foreground campaigns


class EngineUnavailable(Exception):
    """The engine could not be reached (connection-level failure)."""


class EngineError(Exception):
    """The engine answered with an error status.

    Carries the status code and the API's ``detail`` message — surfaced
    to the user as-is, never swallowed.
    """

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"engine returned {status}: {detail}")
        self.status = status
        self.detail = detail


class EngineClient:
    """Thin sync HTTP client for the FreelanceDZ engine API."""

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self.base_url, timeout=_TIMEOUT)

    # ------------------------------------------------------------------
    def request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        request_timeout = (
            httpx.Timeout(timeout, connect=5.0) if timeout is not None else _TIMEOUT
        )
        try:
            response = self._client.request(
                method, path, params=params, json=json, timeout=request_timeout
            )
        except httpx.HTTPError as exc:
            raise EngineUnavailable(f"{self.base_url}{path}: {exc}") from exc

        if response.status_code >= 400:
            detail = ""
            try:
                detail = str(response.json().get("detail", ""))
            except ValueError:
                detail = response.text[:200]
            raise EngineError(response.status_code, detail)
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    def get(self, path: str, params: Optional[dict[str, Any]] = None) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, json: Optional[dict[str, Any]] = None,
             timeout: Optional[float] = None) -> Any:
        return self.request("POST", path, json=json, timeout=timeout)

    def patch(self, path: str, json: Optional[dict[str, Any]] = None) -> Any:
        return self.request("PATCH", path, json=json)

    def delete(self, path: str) -> Any:
        return self.request("DELETE", path)

    def close(self) -> None:
        self._client.close()


@st.cache_resource(show_spinner=False)
def get_engine_client() -> EngineClient:
    """One client per Streamlit server process (connection pooling)."""
    return EngineClient(os.environ.get("ENGINE_URL", DEFAULT_ENGINE_URL))


# ---------------------------------------------------------------------------
# Cached reads — TTL-bounded so reruns are free while data stays fresh.
# Mutation helpers below clear exactly the caches their writes affect.
# ---------------------------------------------------------------------------
@st.cache_data(ttl=10, show_spinner=False)
def fetch_stats() -> dict[str, Any]:
    return get_engine_client().get("/api/v2/stats")


@st.cache_data(ttl=10, show_spinner=False)
def fetch_leads(
    q: Optional[str] = None,
    wilaya: Optional[str] = None,
    status: Optional[str] = None,
    is_contact: Optional[bool] = None,
    min_score: float = 0.0,
    sort_by: str = "priority_score",
    sort_order: str = "desc",
    limit: int = 100,
    offset: int = 0,
) -> dict[str, Any]:
    params: dict[str, Any] = {
        "min_score": min_score,
        "sort_by": sort_by,
        "sort_order": sort_order,
        "limit": limit,
        "offset": offset,
    }
    if q:
        params["q"] = q
    if wilaya:
        params["wilaya"] = wilaya
    if status:
        params["status"] = status
    if is_contact is not None:
        params["is_contact"] = is_contact
    return get_engine_client().get("/api/v2/leads", params=params)


@st.cache_data(ttl=0, show_spinner=False)
def fetch_lead(lead_id: int) -> dict[str, Any]:
    return get_engine_client().get(f"/api/v2/leads/{lead_id}")


@st.cache_data(ttl=60, show_spinner=False)
def fetch_tags() -> list[str]:
    return get_engine_client().get("/api/v2/tags").get("tags", [])


@st.cache_data(ttl=5, show_spinner=False)
def fetch_campaigns(limit: int = 8) -> dict[str, Any]:
    return get_engine_client().get(
        "/api/v2/discover/campaigns", params={"limit": limit}
    )


@st.cache_data(ttl=30, show_spinner=False)
def fetch_wilayas() -> list[dict[str, Any]]:
    return get_engine_client().get("/api/v2/geo/wilayas").get("wilayas", [])


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_boundaries() -> dict[str, Any]:
    """Immutable per dataset version — long TTL, cleared only on upgrade."""
    return get_engine_client().get("/api/v2/geo/boundaries")


@st.cache_data(ttl=10, show_spinner=False)
def fetch_geo_overview() -> dict[str, Any]:
    return get_engine_client().get("/api/v2/geo/overview")


@st.cache_data(ttl=10, show_spinner=False)
def fetch_checkpoints(
    wilaya: Optional[str] = None,
    category: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 2000,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": limit}
    if wilaya:
        params["wilaya"] = wilaya
    if category:
        params["category"] = category
    if status:
        params["status"] = status
    return get_engine_client().get("/api/v2/checkpoints", params=params)


@st.cache_data(ttl=0, show_spinner=False)
def fetch_health() -> dict[str, Any]:
    return get_engine_client().get("/health")


@st.cache_data(ttl=0, show_spinner=False)
def geo_lookup(latitude: float, longitude: float) -> dict[str, Any]:
    return get_engine_client().post(
        "/api/v2/geo/lookup", json={"latitude": latitude, "longitude": longitude}
    )


@st.cache_data(ttl=15, show_spinner=False)
def fetch_crawler_status() -> dict[str, Any]:
    return get_engine_client().get("/api/v2/crawler/status")


@st.cache_data(ttl=15, show_spinner=False)
def fetch_entities_stats() -> dict[str, Any]:
    return get_engine_client().get("/api/v2/entities/stats")


# ---------------------------------------------------------------------------
# Mutations — plain client calls followed by targeted cache invalidation.
# ---------------------------------------------------------------------------
def invalidate(*, leads: bool = True, checkpoints: bool = False, campaigns: bool = False) -> None:
    if leads:
        fetch_stats.clear()
        fetch_leads.clear()
        fetch_lead.clear()
        fetch_tags.clear()
        fetch_wilayas.clear()
        fetch_geo_overview.clear()
        fetch_entities_stats.clear()
    if checkpoints:
        fetch_checkpoints.clear()
        fetch_wilayas.clear()
        fetch_geo_overview.clear()
    if campaigns:
        fetch_campaigns.clear()


def launch_discovery(query: str, wilaya: Optional[str], limit: int, background: bool = True) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": query,
        "wilaya": wilaya or "",
        "limit": limit,
        "background": background,
    }
    result = get_engine_client().post(
        "/api/v2/discover", json=payload, timeout=180.0 if not background else 30.0
    )
    invalidate(campaigns=True)
    return result


def create_checkpoint(payload: dict[str, Any]) -> dict[str, Any]:
    result = get_engine_client().post("/api/v2/checkpoints", json=payload)
    invalidate(checkpoints=True)
    return result


def update_checkpoint(cp_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    result = get_engine_client().patch(f"/api/v2/checkpoints/{cp_id}", json=payload)
    invalidate(checkpoints=True)
    return result


def delete_checkpoint(cp_id: int) -> dict[str, Any]:
    result = get_engine_client().delete(f"/api/v2/checkpoints/{cp_id}")
    invalidate(checkpoints=True)
    return result


def set_lead_contact(lead_id: int, is_contact: bool) -> dict[str, Any]:
    result = get_engine_client().post(
        f"/api/v2/leads/{lead_id}/contact", json={"is_contact": is_contact}
    )
    invalidate()
    return result


def set_lead_status(lead_id: int, status: str) -> dict[str, Any]:
    result = get_engine_client().post(
        f"/api/v2/leads/{lead_id}/status", json={"status": status}
    )
    invalidate()
    return result


def set_lead_tags(lead_id: int, tags: list[str]) -> dict[str, Any]:
    result = get_engine_client().post(
        f"/api/v2/leads/{lead_id}/tags", json={"tags": tags}
    )
    invalidate()
    return result


def analyze_lead(lead_id: int) -> dict[str, Any]:
    result = get_engine_client().post(f"/api/v2/leads/{lead_id}/analyze")
    invalidate()
    return result


def resolve_entities() -> dict[str, Any]:
    result = get_engine_client().post("/api/v2/entities/resolve", timeout=120.0)
    invalidate()
    return result


def analyze_pending(limit: int = 50) -> dict[str, Any]:
    result = get_engine_client().post(
        f"/api/v2/leads/analyze-pending?limit={limit}"
    )
    invalidate()
    return result
