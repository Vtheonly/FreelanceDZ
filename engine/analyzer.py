"""Deterministic business analyzer — the canonical audit implementation.

History: iteration 1 removed the external LLM dependency (unaffordable,
unreliable, 30-60s stalls) and introduced a deterministic auditor; iterations
2-3 refined it with the Algerian services catalog (DZD budgets) and FR/AR
call-to-action synthesis; the v2.0.0 rewrite re-introduced an LLM stack whose
practical runtime path was a keyword heuristic anyway (three redundant
fallback layers). v3 makes the deterministic analyzer the ONLY implementation:
zero network, zero cost, sub-millisecond, explainable.

The analyzer computes:
    digital_score (0-100) — weighted channel presence
    digital_tier          — maturity classification
    gaps                  — concrete missing-channel findings (FR)
    recommended_services  — catalog-matched pitches with DZD budgets
    cta_fr / cta_ar       — localized outreach openers
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from config.services_catalog import SERVICES_CATALOG

if TYPE_CHECKING:  # pragma: no cover
    from domain.models import Lead

TIER_MATURE = "Mature / Digitalise"
TIER_PARTIAL = "Partiellement Numerise"
TIER_HIGH_OPPORTUNITY = "Opportunite Forte (Analogique)"


@dataclass
class RecommendedService:
    service_name: str
    category: str
    pitch_title: str
    pitch_argument: str
    estimated_budget_dzd: float
    priority: int

    def to_dict(self) -> dict:
        return {
            "service_name": self.service_name,
            "category": self.category,
            "pitch_title": self.pitch_title,
            "pitch_argument": self.pitch_argument,
            "estimated_budget_dzd": self.estimated_budget_dzd,
            "priority": self.priority,
        }


@dataclass
class BusinessAudit:
    digital_score: int = 0
    digital_tier: str = TIER_HIGH_OPPORTUNITY
    gaps: list[str] = field(default_factory=list)
    recommended_services: list[RecommendedService] = field(default_factory=list)
    cta_fr: str = ""
    cta_ar: str = ""
    analysis_model: str = "deterministic-v3"

    def to_dict(self) -> dict:
        return {
            "digital_score": self.digital_score,
            "digital_tier": self.digital_tier,
            "gaps": self.gaps,
            "recommended_services": [s.to_dict() for s in self.recommended_services],
            "cta_fr": self.cta_fr,
            "cta_ar": self.cta_ar,
            "analysis_model": self.analysis_model,
        }


class BusinessAnalyzer:
    """Stateless, fully deterministic commercial auditor for Algerian SMEs."""

    def audit(self, lead: "Lead") -> BusinessAudit:
        score = self._digital_score(lead)
        gaps: list[str] = []
        pitches: list[RecommendedService] = []

        # --- Web presence -------------------------------------------------
        if not lead.website:
            gaps.append("Aucun site web officiel identifie.")
            pitches.append(RecommendedService(
                service_name="Site Vitrine & Referencecement Local",
                category="Developpement Web",
                pitch_title="Creation de Site Web & Fiche Google Business",
                pitch_argument=(
                    "Vos concurrents captent les recherches locales sur Google. "
                    "Un site vitrine professionnel vous apporte des clients qualifies chaque semaine."
                ),
                estimated_budget_dzd=65000.0,
                priority=10,
            ))
        elif lead.website.startswith("http://"):
            gaps.append("Site web non securise (absence de certificat SSL/HTTPS).")
            pitches.append(RecommendedService(
                service_name="Securisation SSL & Optimisation Mobile",
                category="Maintenance Web",
                pitch_title="Mise en Conformite HTTPS & Acceleration Mobile",
                pitch_argument=(
                    "Votre site affiche un avertissement de securite qui dissuade "
                    "les clients potentiels d'appeler ou de commander."
                ),
                estimated_budget_dzd=25000.0,
                priority=7,
            ))

        # --- Contact channels ---------------------------------------------
        has_mobile = any(p.phone_type.value == "MOBILE" for p in lead.phone_details)
        has_whatsapp = any(getattr(p, "is_whatsapp_capable", False) for p in lead.phone_details)

        if has_mobile or has_whatsapp:
            pitches.append(RecommendedService(
                service_name="Automatisation Commerciale WhatsApp Business",
                category="Automatisation Commerciale",
                pitch_title="Tunnel de Prise de Commande WhatsApp Automatise",
                pitch_argument=(
                    "Ne manquez aucun message client le soir et le week-end "
                    "grace a la prise de commande automatisee."
                ),
                estimated_budget_dzd=35000.0,
                priority=8,
            ))
        elif not lead.phone:
            gaps.append("Aucun numero de telephone professionnel renseigne.")

        if not lead.email:
            gaps.append("Absence d'adresse e-mail professionnelle declarée.")
        if not lead.social_links:
            gaps.append("Absence de profils sociaux commerciaux (Facebook / Instagram).")
            pitches.append(RecommendedService(
                service_name="Setup Reseaux Sociaux Commerciaux",
                category="Marketing Digital",
                pitch_title="Presence de Marque Facebook & Instagram",
                pitch_argument=(
                    "Etablissez une presence commerciale de confiance sur les "
                    "reseaux ou vos clients cherchent deja."
                ),
                estimated_budget_dzd=35000.0,
                priority=7,
            ))

        # --- Industry-matched catalog pitches ------------------------------
        industry_key = (lead.industry or "").lower()
        for cat in SERVICES_CATALOG:
            relevant = [str(r).lower() for r in cat.get("relevant_industries", ())]
            if relevant and any(r and r in industry_key for r in relevant):
                base_usd = float(cat.get("base_value_usd", 0.0))
                pitches.append(RecommendedService(
                    service_name=str(cat["name"]),
                    category=str(cat.get("category", "Solution Metier")),
                    pitch_title=str(cat.get("pitch_title", cat["name"])),
                    pitch_argument=str(cat.get("pitch_angle", "")),
                    estimated_budget_dzd=float(cat.get("base_value_dzd", base_usd * 140.0)),
                    priority=int(cat.get("priority", 6)),
                ))

        # Deduplicate by service name, keep highest priority first.
        seen: set[str] = set()
        unique_pitches: list[RecommendedService] = []
        for p in sorted(pitches, key=lambda x: x.priority, reverse=True):
            if p.service_name not in seen:
                seen.add(p.service_name)
                unique_pitches.append(p)

        if score >= 70:
            tier = TIER_MATURE
        elif score >= 40:
            tier = TIER_PARTIAL
        else:
            tier = TIER_HIGH_OPPORTUNITY

        return BusinessAudit(
            digital_score=score,
            digital_tier=tier,
            gaps=gaps,
            recommended_services=unique_pitches[:4],
            cta_fr=(
                f"Bonjour, suite a l'analyse de la presence en ligne de {lead.name} "
                f"a {lead.wilaya}, nous avons identifie des leviers concrets "
                f"pour augmenter votre acquisition client."
            ),
            cta_ar=(
                f"السلام عليكم، قمنا بدراسة التواجد الرقمي لمؤسستكم {lead.name} "
                f"بولاية {lead.wilaya} ونقترح عليكم حلولا عملية لزيادة زبائنكم."
            ),
        )

    @staticmethod
    def _digital_score(lead: "Lead") -> int:
        """Must stay consistent with NativeEngine._score_batch_py's health column."""
        score = 10
        if lead.website:
            score += 35
            if lead.website.startswith("https://"):
                score += 10
        if lead.phone:
            score += 15
        if lead.email:
            score += 10
        if lead.social_links:
            score += 10 + min(len(lead.social_links), 2) * 5
        if lead.address:
            score += 5
        return min(100, score)
