"""URL helpers — parsing, cleaning, and DuckDuckGo unwrapping.

All functions are pure and defensive: they never raise on malformed input.
"""

from __future__ import annotations

from urllib.parse import parse_qs, unquote, urljoin, urlparse


def clean_url(url: str) -> str:
    """Strip whitespace, drop fragments, and normalise the scheme.

    Returns an empty string for invalid input. Fragments are dropped
    because they are client-side only and never affect scraping.
    """
    if not url:
        return ""
    url = url.strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        # Don't guess — many SERP links are relative or protocol-relative.
        if url.startswith("//"):
            url = "https:" + url
        else:
            return ""
    parsed = urlparse(url)
    # Rebuild without the fragment.
    return parsed._replace(fragment="").geturl()


def domain_of(url: str) -> str:
    """Return the lowercased netloc, without the ``www.`` prefix."""
    if not url:
        return ""
    parsed = urlparse(url.lower())
    host = parsed.netloc
    if host.startswith("www."):
        host = host[4:]
    return host


def is_same_domain(url_a: str, url_b: str) -> bool:
    """True if both URLs share the same registrable host (after ``www.`` drop)."""
    return domain_of(url_a) == domain_of(url_b) and bool(domain_of(url_a))


def resolve_relative(base: str, href: str) -> str:
    """Resolve ``href`` against ``base``, returning a clean absolute URL."""
    if not href or not base:
        return ""
    return clean_url(urljoin(base, href))


def unwrap_ddg_url(raw_url: str) -> str:
    """Extract the real target URL from a DuckDuckGo redirect.

    DDG wraps external links like:
    ``//duckduckgo.com/l/?uddg=<URL>&rut=...`` or relative link `/l/?uddg=...`
    — we pull the ``uddg`` parameter and URL-decode it.
    """
    if not raw_url:
        return ""
    
    # Handle protocol-relative and path-relative URLs
    if raw_url.startswith("//"):
        raw_url = "https:" + raw_url
    elif raw_url.startswith("/"):
        raw_url = "https://duckduckgo.com" + raw_url
        
    parsed = urlparse(raw_url)
    if "duckduckgo.com" not in parsed.netloc:
        return clean_url(raw_url)
        
    qs = parse_qs(parsed.query)
    if "uddg" in qs and qs["uddg"]:
        return clean_url(unquote(qs["uddg"][0]))
    return clean_url(raw_url)