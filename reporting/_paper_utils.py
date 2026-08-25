"""Internal helpers for the reporting package: duck-typed Paper field access.

The reporting modules accept ``List[Paper]`` where ``Paper`` is the project's
canonical dataclass (defined later in ``database/models.py``).  To keep every
reporting module independently importable and resilient to schema drift, we
treat ``Paper`` as a structural protocol: any object (dataclass, ORM model,
``dict``, ``TypedDict`` or ``SimpleNamespace``) that exposes the relevant
attributes works.  This module centralises the lookup logic so that each
reporting module can stay focused on its rendering concern.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

from typing import Any, Iterable, List, Optional, Sequence


# Canonical field name aliases.  Keys are the "canonical" field name used
# internally; values are the ordered list of attribute / dict keys to try
# when extracting that field from a Paper-like object.
_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "doi": ("doi", "DOI", "doi_str", "doi_id"),
    "title": ("title", "name", "display_name"),
    "authors": ("authors", "author", "author_list", "creators"),
    "year": ("year", "publication_year", "published_year", "pub_year"),
    "journal": ("journal", "journal_name", "container_title"),
    "booktitle": ("booktitle", "venue", "proceedings", "conference"),
    "volume": ("volume", "vol"),
    "number": ("number", "issue", "no"),
    "pages": ("pages", "page_range"),
    "publisher": ("publisher", "publisher_name"),
    "url": ("url", "link", "uri"),
    "abstract": ("abstract", "summary"),
    "keywords": ("keywords", "keyword_list", "tags"),
    "citations": ("citations", "citation_count", "citation_count_by_year"),
    "entry_type": ("entry_type", "type", "publication_type", "work_type"),
    "affiliations": ("affiliations", "affiliation", "author_affiliations"),
    "cited_by": ("cited_by", "cited_dois", "references_doi"),
    "fields_of_study": ("fields_of_study", "fos", "fields", "concepts"),
}

# A reasonable default citation counter signature for h-index computation.
CITATION_FALLBACK = 0


def _lookup(obj: Any, keys: Sequence[str]) -> Any:
    """Try attribute access first, then dict-style access, for each key.

    Args:
        obj: The Paper-like object (any namespace, dataclass, ORM row, or dict).
        keys: Ordered iterable of attribute / dict keys to try.

    Returns:
        The first non-``None`` value found, or ``None`` if none match.
    """
    for k in keys:
        # Attribute access first (works for dataclasses, ORM objects, namespaces).
        try:
            v = getattr(obj, k)
        except AttributeError:
            v = None
        if v is None and isinstance(obj, dict):
            v = obj.get(k)
        if v is not None:
            return v
    return None


def get_field(paper: Any, name: str, default: Any = None) -> Any:
    """Extract a canonical field from a Paper-like object.

    Args:
        paper: The Paper-like object.
        name: Canonical field name (must be a key of ``_FIELD_ALIASES``).
        default: Value to return if the field is missing/empty.

    Returns:
        The extracted value, or ``default``.
    """
    keys = _FIELD_ALIASES.get(name, (name,))
    v = _lookup(paper, keys)
    if v is None or v == "":
        return default
    return v


def get_str(paper: Any, name: str, default: str = "") -> str:
    """Extract a string field; coerces to ``str`` and strips."""
    v = get_field(paper, name)
    if v is None:
        return default
    return str(v).strip()


def get_int(paper: Any, name: str, default: int = 0) -> int:
    """Extract an int field, tolerating ``"42"``-style strings."""
    v = get_field(paper, name)
    if v is None or v == "":
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        # Sometimes citations come in as a list of per-year counts.
        if isinstance(v, (list, tuple)) and v:
            try:
                return int(v[0])
            except (TypeError, ValueError):
                return default
        return default


def get_authors(paper: Any) -> List[str]:
    """Return a list of author display strings.

    Handles:
        * ``["Last, First", "Last2, First2"]`` — list of strings.
        * ``[{"name": "First Last", ...}, ...]`` — list of dicts.
        * ``"Last, First and Last2, First2"`` — raw string with separators.
        * ``None`` -> ``[]``.
    """
    raw = get_field(paper, "authors", default=[])
    return _normalise_authors(raw)


def _normalise_authors(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        # Common separators: ';', '|', ' and ', ' & '.
        s = raw.replace("|", ";").replace(" and ", ";").replace(" & ", ";")
        parts = [p.strip() for p in s.split(";") if p.strip()]
        # If still no parts, try comma splitting but keep "Last, First" intact.
        if len(parts) <= 1 and "," in raw:
            parts = [p.strip() for p in raw.split(",") if p.strip()]
        return parts
    if isinstance(raw, dict):
        # Single author dict.
        name = raw.get("name") or raw.get("display_name") or raw.get("raw")
        return [str(name).strip()] if name else []
    if isinstance(raw, Iterable):
        out: List[str] = []
        for item in raw:
            if item is None:
                continue
            if isinstance(item, str):
                if item.strip():
                    out.append(item.strip())
            elif isinstance(item, dict):
                name = item.get("name") or item.get("display_name") or item.get("raw")
                if name:
                    out.append(str(name).strip())
            else:
                # Object with .name attribute.
                name = getattr(item, "name", None) or getattr(item, "display_name", None)
                if name:
                    out.append(str(name).strip())
        return out
    return []


def get_keywords(paper: Any) -> List[str]:
    """Return a list of keywords; tolerates string, list-of-str, list-of-dict."""
    raw = get_field(paper, "keywords", default=[])
    if raw is None:
        return []
    if isinstance(raw, str):
        parts = raw.replace("|", ";").replace(",", ";").split(";")
        return [p.strip() for p in parts if p.strip()]
    if isinstance(raw, dict):
        return [str(raw.get("name", raw.get("display_name", ""))).strip()]
    if isinstance(raw, Iterable):
        out: List[str] = []
        for item in raw:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
            elif isinstance(item, dict):
                n = item.get("name") or item.get("display_name")
                if n:
                    out.append(str(n).strip())
        return out
    return []


def get_citation_count(paper: Any) -> int:
    """Return a single int citation count, tolerating per-year lists."""
    v = get_field(paper, "citations")
    if v is None or v == "":
        return CITATION_FALLBACK
    if isinstance(v, int):
        return v
    if isinstance(v, (list, tuple)):
        # Sum yearly counts if they look like {'year': y, 'count': c} dicts.
        total = 0
        for item in v:
            if isinstance(item, dict):
                c = item.get("count") or item.get("cited_by_count") or 0
                try:
                    total += int(c)
                except (TypeError, ValueError):
                    pass
            else:
                try:
                    total += int(item)
                except (TypeError, ValueError):
                    pass
        return total
    try:
        return int(v)
    except (TypeError, ValueError):
        return CITATION_FALLBACK


def get_year(paper: Any) -> Optional[int]:
    """Return the publication year as int, or ``None`` if missing/unparseable."""
    v = get_field(paper, "year")
    if v is None or v == "":
        return None
    if isinstance(v, int):
        return v
    s = str(v)
    # Tolerate ISO date strings like "2024-03-01".
    if "-" in s and len(s) >= 4:
        s = s.split("-")[0]
    try:
        y = int(s)
        if 1500 <= y <= 2100:
            return y
    except ValueError:
        pass
    return None


def get_doi(paper: Any) -> str:
    """Return the normalised DOI (lowercased, no ``doi.org/`` prefix)."""
    doi = get_str(paper, "doi")
    if not doi:
        return ""
    doi = doi.strip()
    # Strip URL prefix if present.
    for prefix in ("https://doi.org/", "http://doi.org/", "doi.org/", "doi:"):
        if doi.lower().startswith(prefix.lower()):
            doi = doi[len(prefix):]
            break
    return doi.lower().strip()


def get_citekey(paper: Any, idx: int) -> str:
    """Build a deterministic BibTeX citekey for a paper.

    Format: ``firstauthorlastnameYearShortTitle`` e.g. ``smith2024quantum``.
    Falls back to ``paper{idx}`` if no author / title / year.
    """
    authors = get_authors(paper)
    year = get_year(paper)
    title = get_str(paper, "title")
    surname = "anon"
    if authors:
        first = authors[0]
        # Last, First -> Last ; "First Last" -> Last
        if "," in first:
            surname = first.split(",")[0].strip()
        else:
            parts = first.split()
            surname = parts[-1] if parts else first
    # Keep only ASCII letters for the citekey (BibTeX citekeys must be
    # ASCII-safe to avoid parser issues with bibtex/biber on some systems).
    surname_ascii = "".join(
        ch for ch in surname.lower() if ch.isascii() and ch.isalpha()
    )
    if not surname_ascii:
        surname_ascii = "anon"
    year_part = str(year) if year else "nd"
    # Title words: split on non-ASCII-letter boundaries, keep ASCII letters only.
    title_clean_chars = []
    for ch in title.lower():
        if ch.isascii() and (ch.isalpha() or ch == " "):
            title_clean_chars.append(ch)
        else:
            title_clean_chars.append(" ")
    title_words = [
        w for w in "".join(title_clean_chars).split()
        if w not in {"the", "a", "an", "of", "for", "and", "on", "in", "to"}
    ]
    title_part = "".join(title_words[:3])
    if not title_part:
        title_part = f"paper{idx}"
    key = f"{surname_ascii}{year_part}{title_part}"
    return key


def normalise_authors_bibtex(authors: List[str]) -> str:
    """Format a list of author display strings for BibTeX ``author = {...}``.

    Each author is converted to ``Last, First`` form if it contains a comma,
    or left as-is otherwise.  Multiple authors are joined with `` and ``.
    """
    parts = []
    for a in authors:
        a = a.strip().rstrip(".")
        if not a:
            continue
        parts.append(a)
    return " and ".join(parts)


def calculate_h_index(citation_counts: Iterable[int]) -> int:
    """Compute the h-index from an iterable of citation counts.

    The h-index is the largest ``h`` such that ``h`` papers each have at
    least ``h`` citations.
    """
    sorted_c = sorted((int(c) for c in citation_counts if c is not None), reverse=True)
    h = 0
    for i, c in enumerate(sorted_c):
        if i + 1 <= c:
            h = i + 1
        else:
            break
    return h


def get_affiliation_countries(paper: Any) -> List[str]:
    """Return a flat list of country names from author affiliations if present.

    Affiliations may be ``[{"country": "China"}, ...]`` or
    ``[{"author": ..., "countries": ["US", "CN"]}, ...]``.
    """
    raw = get_field(paper, "affiliations", default=[])
    out: List[str] = []
    if raw is None:
        return out
    if isinstance(raw, dict):
        raw = [raw]
    if isinstance(raw, Iterable):
        for item in raw:
            if isinstance(item, str):
                if item.strip():
                    out.append(item.strip())
            elif isinstance(item, dict):
                c = item.get("country") or item.get("country_name")
                if c:
                    out.append(str(c).strip())
                for k in ("countries", "country_codes"):
                    if k in item and isinstance(item[k], (list, tuple)):
                        for cc in item[k]:
                            if isinstance(cc, str) and cc.strip():
                                out.append(cc.strip())
    return out


__all__ = [
    "get_field",
    "get_str",
    "get_int",
    "get_authors",
    "get_keywords",
    "get_citation_count",
    "get_year",
    "get_doi",
    "get_citekey",
    "normalise_authors_bibtex",
    "calculate_h_index",
    "get_affiliation_countries",
]
