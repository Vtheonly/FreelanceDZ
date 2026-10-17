"""Canonical record generation: one consolidated representation per entity.

The golden record is *derived*, never destructive: every member lead row
keeps its own values, and the canonical view records which member (and
which source) each field value came from.

Field selection policy (per field, independently):

1. Source trust — manual curation beats structured registries beats
   search snippets beats self-described social profiles.
2. Recency — newer updates win ties (values decay: phones get ported,
   addresses change).
3. Completeness — a value with more substance (longer address, more
   digits, fuller name) wins remaining ties.

Conflicts are *recorded, not overwritten*: when members disagree on a
field, the canonical value keeps its provenance and the losing values
survive as ``alternatives`` with their own provenance, so a human
reviewing the entity can see the disagreement and its sources.

Aliases: every distinct normalized name variant among the members
(display form kept), so "Café Atlas", "Cafe Atlas" and "Café Atlas
Restaurant" all remain searchable on the canonical entity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from domain.enums import DataSource
from domain.models import Lead
from engine.resolution.features import name_key

# Source reliability for factual fields. Manual curation (a human typed
# it) > OSM registry (community-verified structure) > SERP titles from
# the business's own site > social self-descriptions.
_SOURCE_TRUST: dict[DataSource, int] = {
    DataSource.MANUAL: 5,
    DataSource.OVERPASS: 4,
    DataSource.DUCKDUCKGO: 3,
    DataSource.SEARXNG: 3,
    DataSource.INFINITE: 3,
    DataSource.SOCIAL: 2,
    DataSource.MOCK: 1,
}

_FIELDS = ("name", "industry", "wilaya", "address", "website", "phone",
           "email", "latitude", "longitude")

_AGGREGATED = ("social_links", "phones", "aliases")


@dataclass
class SourceTrust:
    """Ranking helper exposed for tests."""

    @staticmethod
    def trust(source: DataSource) -> int:
        return _SOURCE_TRUST.get(source, 1)


def _field_value(lead: Lead, field: str) -> Any:
    return getattr(lead, field, None)


def _substance(field: str, value: Any) -> int:
    if value is None:
        return 0
    if field in ("latitude", "longitude"):
        return 1
    return len(str(value))


class CanonicalBuilder:
    """Builds the consolidated representation of one confirmed entity."""

    @staticmethod
    def build(leads: list[Lead], evidence: Optional[dict] = None) -> dict[str, Any]:
        """Return the cluster record for ClusterRepository persistence.

        ``evidence`` is the cluster's resolution summary (identity
        statistics, merge count) produced by the resolver; it is stored
        verbatim so the entity carries its own why.
        """
        if not leads:
            return {}

        canonical_fields: dict[str, dict[str, Any]] = {}
        for field in _FIELDS:
            winner: Optional[Lead] = None
            if field == "name":
                winner = CanonicalBuilder._majority_name(leads)
            if winner is None:
                best: Optional[tuple[tuple[int, str, int], Lead]] = None
                for lead in leads:
                    value = _field_value(lead, field)
                    if value is None or value == "":
                        continue
                    rank = (
                        _SOURCE_TRUST.get(lead.source, 1),
                        lead.updated_at.isoformat(),
                        _substance(field, value),
                    )
                    if best is None or rank > best[0]:
                        best = (rank, lead)
                winner = best[1] if best else None
            if winner is None:
                continue
            winning_value = _field_value(winner, field)
            alternatives = []
            seen = {name_key(str(winning_value))}
            for lead in leads:
                value = _field_value(lead, field)
                if value is None or value == "" or lead.id == winner.id:
                    continue
                if name_key(str(value)) in seen:
                    continue
                seen.add(name_key(str(value)))
                alternatives.append({
                    "value": value,
                    "lead_id": lead.id,
                    "source": lead.source.value,
                })
            canonical_fields[field] = {
                "value": winning_value,
                "lead_id": winner.id,
                "source": winner.source.value,
                "conflict": bool(alternatives),
                "alternatives": alternatives,
            }

        # Aggregated collections: union with provenance counts.
        social_seen: dict[str, int] = {}
        for lead in leads:
            for link in lead.social_links:
                social_seen[link] = social_seen.get(link, 0) + 1

        # Aliases: distinct display names over distinct normalized keys.
        alias_by_key: dict[str, str] = {}
        for lead in sorted(leads, key=lambda l: _completeness(l), reverse=True):
            key = name_key(lead.name or "")
            if key and key not in alias_by_key:
                alias_by_key[key] = (lead.name or "").strip()
        canonical_name = canonical_fields.get("name", {}).get("value")
        aliases = [a for k, a in alias_by_key.items()
                   if canonical_name is None or name_key(str(canonical_name)) != k]

        canonical_lead = _canonical_member(leads)
        member_count = len(leads)
        confidence = CanonicalBuilder.confidence(member_count, evidence)

        return {
            "canonical_lead_id": canonical_lead.id,
            "name": canonical_fields.get("name", {}).get("value")
                    or (leads[0].name if leads else ""),
            "industry": canonical_fields.get("industry", {}).get("value") or "",
            "wilaya": canonical_fields.get("wilaya", {}).get("value") or "",
            "confidence": confidence,
            "strategy": "graph_merge" if member_count > 1 else "single",
            "members": [l.id for l in leads if l.id is not None],
            "reasons": CanonicalBuilder.reasons(evidence),
            "aliases": aliases,
            "canonical_fields": canonical_fields,
            "social_links": sorted(social_seen),
            "evidence": evidence or {},
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _majority_name(leads: list[Lead]) -> Optional[Lead]:
        """The name most members agree on (majority over normalized keys).

        Four channels calling the business "Café Atlas" outrank one
        directory suffixing it with "Restaurant" — names are voted, not
        trusted, because the display name is the field every source
        renders differently. Ties and singles fall through to the
        trust/recency ranking.
        """
        groups: dict[str, list[Lead]] = {}
        for lead in leads:
            key = name_key(lead.name or "")
            if key:
                groups.setdefault(key, []).append(lead)
        if not groups:
            return None
        top_count = max(len(v) for v in groups.values())
        if top_count < 2:
            return None  # every variant is unique — use trust ranking
        winners = [v for v in groups.values() if len(v) == top_count]
        if len(winners) > 1:
            return None  # tie between variants — trust ranking decides
        group = winners[0]
        # Second-level vote on the display string: "Café Atlas" x3 beats
        # "cafe_atlas" x1 even though both normalize to the same key.
        display_counts: dict[str, list[Lead]] = {}
        for lead in group:
            display_counts.setdefault(lead.name.strip(), []).append(lead)
        top_display = max(len(v) for v in display_counts.values())
        if top_display >= 2:
            display_winners = [l for v in display_counts.values()
                               if len(v) == top_display for l in v]
            return max(
                display_winners,
                key=lambda l: (_SOURCE_TRUST.get(l.source, 1), l.updated_at.isoformat()),
            )
        # Every display unique: prefer the most readable form (mixed case
        # with word separators) over snake_case / lowercase exports.
        def readability(name: str) -> tuple[int, int]:
            return (
                1 if any(ch.isupper() for ch in name) else 0,
                1 if (" " in name and "_" not in name) else 0,
            )
        return max(
            group,
            key=lambda l: (readability(l.name), _SOURCE_TRUST.get(l.source, 1),
                           l.updated_at.isoformat()),
        )

    @staticmethod
    def confidence(member_count: int, evidence: Optional[dict]) -> float:
        """Cluster confidence from merge evidence, not member count alone.

        v3.0's `0.70 + 0.10 * len(leads)` rewarded big clusters even when
        they were stitched from weak edges. v3.1 anchors on the weakest
        link: the minimum identity score among the merge edges, with a
        count bonus capped so volume alone cannot fake certainty.
        """
        if member_count <= 1:
            return 1.0
        min_identity = 0.70
        if evidence and evidence.get("min_edge_identity") is not None:
            min_identity = float(evidence["min_edge_identity"])
        count_bonus = min(0.05 * (member_count - 1), 0.10)
        return round(min(0.99, 0.55 + 0.35 * min_identity + count_bonus), 3)

    @staticmethod
    def reasons(evidence: Optional[dict]) -> list[str]:
        if not evidence:
            return []
        top = evidence.get("top_signals") or []
        return list(top[:4])

    @staticmethod
    def restore_source_records(leads: list[Lead]) -> list[dict[str, Any]]:
        """Provenance view for the API: the original records behind an
        entity, untouched — used by split/merge endpoints to show what
        would be restored."""
        return [
            {
                "lead_id": l.id,
                "name": l.name,
                "source": l.source.value,
                "source_url": l.source_url,
                "discovered_at": l.discovered_at.isoformat(),
            }
            for l in leads
        ]


def _completeness(lead: Lead) -> int:
    return (
        sum(1 for v in (lead.address, lead.website, lead.phone, lead.email) if v)
        + len(lead.social_links)
        + len(lead.phone_details)
    )


def _canonical_member(leads: list[Lead]) -> Lead:
    """The member that best represents the entity (trust, then completeness)."""
    return max(
        leads,
        key=lambda l: (_SOURCE_TRUST.get(l.source, 1), _completeness(l)),
    )
