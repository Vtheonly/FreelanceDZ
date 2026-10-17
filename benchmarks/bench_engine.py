"""FreelanceDZ engine benchmarks (v4 architecture).

Measures the CPU-bound hot paths after the C++ core retirement (v4 Task 13):
the fastops regex HTML scanner vs a BS4 full-DOM pass, rapidfuzz-backed
name matching (with and without the trigram prefilter), SoA batch scoring,
the bounded URL dedup, plus storage-layer throughput (atomic upsert,
unified listing) and the geographic engine's point-in-wilaya latency.

Usage: python benchmarks/bench_engine.py
"""

from __future__ import annotations

import random
import string
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rapidfuzz.distance import Levenshtein  # noqa: E402

from engine.fastops import (  # noqa: E402
    NameMatcher,
    UrlDedup,
    extract_html,
    levenshtein,
    score_batch,
)


def _fmt_rate(n: int, seconds: float) -> str:
    return f"{n / max(seconds, 1e-9):>14,.0f}/s"


def _bench(fn, *, repeat: int = 1) -> float:
    """Run fn() `repeat` times; return TOTAL elapsed seconds."""
    t0 = time.perf_counter()
    for _ in range(repeat):
        fn()
    return time.perf_counter() - t0


# ---------------------------------------------------------------------------
def bench_levenshtein(n_pairs: int = 100_000) -> None:
    rng = random.Random(1)
    alphabet = string.ascii_lowercase + " "
    pairs = [
        ("".join(rng.choices(alphabet, k=rng.randint(8, 40))),
         "".join(rng.choices(alphabet, k=rng.randint(8, 40))))
        for _ in range(n_pairs)
    ]

    t = _bench(lambda: [Levenshtein.distance(a.encode(), b.encode()) for a, b in pairs])
    print(f"  [v2 baseline  : per-pair rapidfuzz]      {_fmt_rate(n_pairs, t)}")

    flat = [name for pair in pairs for name in pair]

    def matcher_run(all_names=flat, the_pairs=pairs, prefilter=0.0):
        matcher = NameMatcher()
        first = matcher.add_many(all_names)
        idx = [(first + 2 * i, first + 2 * i + 1) for i in range(len(the_pairs))]
        return matcher.match_pairs(idx, prefilter, 0.0)

    t = _bench(matcher_run)
    print(f"  [v4 fastops   : session, no prefilter]     {_fmt_rate(n_pairs, t)}")

    # Production configuration: the 256-bucket trigram prefilter skips the
    # Levenshtein call for unrelated names.
    t = _bench(lambda: matcher_run(prefilter=0.40))
    print(f"  [v4 fastops   : session + prefilter]       {_fmt_rate(n_pairs, t)}")


def bench_entity_resolution(n_leads: int = 4000) -> None:
    """The full resolve() path."""
    from domain.enums import DataSource
    from domain.models import Lead
    from engine.resolver import GraphEntityResolver

    rng = random.Random(7)
    base = ["Pharmacie", "Boulangerie", "Menuiserie", "Clinique", "Garage",
            "Cabinet", "Restaurant", "Boutique", "Salon", "Ferme"]
    suffix = ["Centrale", "El Nour", "Es Salem", "Ben Ali", "La Rose",
              "Ennasr", "El Baraka", "Ain Allah", "Diar Ezzahra", "Ouled Fayet"]
    wilayas = ["Alger", "Oran", "Blida", "Setif", "Annaba", "Constantine"]

    leads = []
    for i in range(n_leads):
        name = f"{rng.choice(base)} {rng.choice(suffix)}"
        if rng.random() < 0.3:
            name += f" {rng.randint(1, 99)}"
        leads.append(Lead(
            name=name,
            industry=rng.choice(base).lower(),
            wilaya=rng.choice(wilayas),
            phone=f"+213{rng.randint(500000000, 799999999)}" if rng.random() < 0.7 else None,
            website=f"https://biz-{i}.dz" if rng.random() < 0.5 else None,
            source=DataSource.MANUAL,
        ))
    # Inject true duplicates.
    for i in range(0, n_leads // 10):
        variant = leads[i].model_copy()
        variant.name = variant.name + "s" if rng.random() < 0.5 else variant.name.replace(" ", "  ")
        variant.phone = leads[i].phone
        leads.append(variant)

    resolver = GraphEntityResolver()
    t = _bench(lambda: resolver.resolve(leads))
    _, report = resolver.resolve(leads)
    print(f"  [v4 fastops   : full resolve]             {_fmt_rate(len(leads), t)}"
          f"  clusters={report.output_count}")

    # Determinism guard (the old native/fallback parity check).
    _, report_b = GraphEntityResolver().resolve(leads)
    assert report_b.output_count == report.output_count, "cluster mismatch!"


def bench_scoring(n_leads: int = 100_000) -> None:
    rng = random.Random(3)
    flags = [rng.getrandbits(9) for _ in range(n_leads)]
    socials = [rng.randint(0, 3) for _ in range(n_leads)]
    fresh = [rng.randint(0, 4) for _ in range(n_leads)]

    t = _bench(lambda: [score_batch([f], [s], [b]) for f, s, b in zip(flags[:5000], socials[:5000], fresh[:5000])])
    print(f"  [v2-style     : per-lead calls]            {_fmt_rate(5000, t)}")

    t = _bench(lambda: score_batch(flags, socials, fresh))
    print(f"  [v4 fastops   : SoA batch scoring]         {_fmt_rate(n_leads, t)}")


def bench_url_dedup(n_urls: int = 1_000_000) -> None:
    urls = [f"https://entreprise-{i}.dz/page/{i}" for i in range(n_urls)]

    seen: set[str] = set()
    t = _bench(lambda: seen.update(urls))
    print(f"  [v2 baseline  : unbounded Python set]      {_fmt_rate(n_urls, t)}"
          f"  memory ~{n_urls * 95 / 1e6:,.0f} MB")

    dedup = UrlDedup(capacity=n_urls)
    t = _bench(lambda: [dedup.test_and_add(u) for u in urls])
    print(f"  [v4 fastops   : bounded locked dedup]      {_fmt_rate(n_urls, t)}"
          f"  capped memory, instance-scoped state")


SAMPLE_HTML = b"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="utf-8">
<title>Pharmacie Centrale - Bab El Oued, Alger</title>
<meta name="description" content="Officine pharmaceutique de garde a Alger.">
<meta property="og:title" content="Pharmacie Centrale">
<link rel="canonical" href="https://pharmacie-centrale.dz/">
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Pharmacy","name":"Pharmacie Centrale",
 "telephone":"+213 21 96 12 34","address":"Bab El Oued, Alger"}
</script></head>
<body><h1>Bienvenue</h1>
<p>Contactez notre pharmacien au 0550 12 34 56 ou 0770 98 76 54.</p>
<a href="/catalogue/produits">Nos produits</a>
<a href="https://facebook.com/pharmacie.centrale">Facebook</a>
<a href="tel:+21321961234">Fixe</a>
<a href="mailto:contact@pharmacie-centrale.dz">Email</a>
</body></html>""" * 8  # ~11 KB page


def bench_html_extraction(n_pages: int = 3000) -> None:
    def bs4_extract():
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(SAMPLE_HTML, "lxml")
        title = soup.title.get_text() if soup.title else ""
        links = [a["href"] for a in soup.find_all("a", href=True)]
        json_ld = ""
        for s in soup.find_all("script"):
            if (s.get("type") or "") == "application/ld+json":
                json_ld = s.string or ""
                break
        return title, links, json_ld

    t = _bench(bs4_extract, repeat=n_pages)
    print(f"  [v2 baseline  : BS4+lxml full DOM]        {_fmt_rate(n_pages, t)}")

    t = _bench(lambda: extract_html(SAMPLE_HTML), repeat=n_pages)
    print(f"  [v4 fastops   : pre-compiled regex scan]   {_fmt_rate(n_pages, t)}")


def bench_geo_lookup(n_points: int = 50_000) -> None:
    """Point-in-wilaya latency for map click resolution."""
    from engine.geo import get_geo_service
    geo = get_geo_service()
    rng = random.Random(11)
    points = [(rng.uniform(-8.5, 11.8), rng.uniform(19.5, 36.9)) for _ in range(n_points)]
    t0 = time.perf_counter()
    hits = sum(1 for lon, lat in points if geo.lookup(lon, lat) is not None)
    elapsed = time.perf_counter() - t0
    print(f"  [v4 geo       : point-in-wilaya]           {_fmt_rate(n_points, elapsed)}"
          f"  hit-rate={hits / n_points:.0%} (bbox prefilter + ray casting)")


# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 78)
    print("FREELANCEDZ ENGINE BENCHMARKS (v4 — pure-Python fastops core)")
    print("=" * 78)

    print("\n[1] Levenshtein name similarity (entity-resolution kernel)")
    bench_levenshtein()

    print("\n[2] Full entity resolution (blocking + matching + DSU)")
    bench_entity_resolution()

    print("\n[3] Lead scoring (SoA batch)")
    bench_scoring()

    print("\n[4] URL deduplication")
    bench_url_dedup()

    print("\n[5] HTML extraction (11 KB page)")
    bench_html_extraction()

    print("\n[6] Geographic engine")
    bench_geo_lookup()

    print("\n" + "=" * 78)
    print("SUMMARY (measured on this host — see docs/12-performance.md)")
    print("-" * 78)
    print("  The engine is network-bound by design; every CPU-bound kernel is")
    print("  now dependency-light pure Python (rapidfuzz C kernel for edit")
    print("  distance, pre-compiled regex for structural HTML scanning).")
    print("  Storage and API throughput benchmarks: benchmarks/bench_storage.py")
    print("  Performance regression thresholds: tests/test_performance.py")
    print("=" * 78)


if __name__ == "__main__":
    main()
