"""PRISMA 2020 data extraction forms and search-strategy records.

Provides structured containers for the data items typically extracted from
each included study during a systematic review, plus a record for the
search strategy per database.

The fields follow the recommendations of the Cochrane Handbook
(Chapter 5) and the PRISMA 2020 statement (item 11 — Data items).
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PRISMAExtractionForm.
# ---------------------------------------------------------------------------
@dataclass
class PRISMAExtractionForm:
    """Per-study data extraction form (PRISMA 2020 item 11 — Data items).

    Attributes:
        study_id: Unique identifier (e.g. ``"Smith2020"``).
        citation: Full citation of the included study.
        study_design: Design label (e.g. ``"RCT"``, ``"Cohort"``).
        population: Participants description (e.g. ``"Adults ≥18y with T2DM"``).
        intervention: Intervention(s) tested.
        comparator: Comparator / control arm.
        outcomes: List of outcomes extracted (each may be a dict or string).
        sample_size: Total enrolled / analysed sample size.
        follow_up: Median or mean follow-up duration (string with units).
        funding: Funding sources declared.
        conflicts: Conflicts of interest declared by study authors.
        notes: Free-text notes.
    """

    study_id: str = ""
    citation: str = ""
    study_design: str = ""
    population: str = ""
    intervention: str = ""
    comparator: str = ""
    outcomes: List[Any] = field(default_factory=list)
    sample_size: Optional[int] = None
    follow_up: str = ""
    funding: str = ""
    conflicts: str = ""
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-friendly dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PRISMAExtractionForm":
        """Reconstruct from a dict (tolerant of missing keys)."""
        valid = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        kwargs = {k: v for k, v in d.items() if k in valid}
        return cls(**kwargs)

    def to_yaml(self, path: str) -> str:
        """Write the form to a YAML file."""
        try:
            import yaml  # noqa: WPS433
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("PyYAML is required for to_yaml()") from exc
        out = os.path.abspath(path)
        os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            yaml.safe_dump(self.to_dict(), f, allow_unicode=True, sort_keys=False)
        logger.info("PRISMAExtractionForm YAML written to %s", out)
        return out

    @classmethod
    def from_template(cls) -> "PRISMAExtractionForm":
        """Return a blank form with the standard fields populated as empty strings.

        Useful as a starting point for filling in study data.
        """
        return cls(
            study_id="",
            citation="",
            study_design="",
            population="",
            intervention="",
            comparator="",
            outcomes=[],
            sample_size=None,
            follow_up="",
            funding="",
            conflicts="",
            notes="",
        )

    def to_markdown(self) -> str:
        """Render this single form as a Markdown record."""
        lines = [
            f"## Extraction form: {self.study_id or '(unnamed)'}",
            "",
            f"- **Citation:** {self.citation or '—'}",
            f"- **Study design:** {self.study_design or '—'}",
            f"- **Population:** {self.population or '—'}",
            f"- **Intervention:** {self.intervention or '—'}",
            f"- **Comparator:** {self.comparator or '—'}",
            f"- **Sample size:** "
            f"{self.sample_size if self.sample_size is not None else '—'}",
            f"- **Follow-up:** {self.follow_up or '—'}",
            f"- **Funding:** {self.funding or '—'}",
            f"- **Conflicts of interest:** {self.conflicts or '—'}",
        ]
        if self.outcomes:
            lines.append("- **Outcomes:**")
            for o in self.outcomes:
                lines.append(f"  - {o}")
        if self.notes:
            lines.append("")
            lines.append(f"**Notes:** {self.notes}")
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# PRISMASearchStrategy.
# ---------------------------------------------------------------------------
@dataclass
class PRISMASearchStrategy:
    """Per-database search-strategy record (PRISMA 2020 item 7 — Information
    sources & item 8 — Search strategy).

    Attributes:
        database: Database name (e.g. ``"PubMed"``, ``"Embase"``).
        search_string: Full search string with Boolean operators and field
            tags (e.g. ``"(diabetes[MeSH]) AND (metformin[Title/Abstract])"``).
        search_date: ISO-8601 date string when the search was executed.
        num_results: Number of records returned by the database.
        url: Direct URL to the executed search (where supported).
        notes: Free-text notes (e.g. filters applied, limits).
    """

    database: str = ""
    search_string: str = ""
    search_date: str = ""
    num_results: Optional[int] = None
    url: str = ""
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a JSON-friendly dict."""
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PRISMASearchStrategy":
        """Reconstruct from a dict (tolerant of missing keys)."""
        valid = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        kwargs = {k: v for k, v in d.items() if k in valid}
        return cls(**kwargs)

    @classmethod
    def from_template(cls) -> "PRISMASearchStrategy":
        """Return a blank search-strategy record with the standard fields."""
        return cls(
            database="",
            search_string="",
            search_date="",
            num_results=None,
            url="",
            notes="",
        )

    def to_markdown(self) -> str:
        """Render the search strategy as a Markdown block."""
        n = self.num_results if self.num_results is not None else "—"
        lines = [
            f"### {self.database or '(unnamed database)'}",
            "",
            f"- **Date:** {self.search_date or '—'}",
            f"- **Results:** {n}",
            f"- **URL:** {self.url or '—'}",
            "",
            "```text",
            self.search_string or "",
            "```",
        ]
        if self.notes:
            lines.append("")
            lines.append(f"**Notes:** {self.notes}")
        return "\n".join(lines) + "\n"


__all__ = ["PRISMAExtractionForm", "PRISMASearchStrategy"]
