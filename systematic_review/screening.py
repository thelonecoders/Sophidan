"""Title/abstract and full-text screening for systematic reviews.

This module provides the screening-lifecycle primitives used by the
Academic Research Suite's systematic-review workflow:

* :class:`ScreeningStage`     — enumeration of the five PRISMA stages
  a record may occupy (IDENTIFICATION → TITLE_ABSTRACT → FULL_TEXT →
  INCLUDED / EXCLUDED).
* :class:`ExclusionReasons`   — controlled vocabulary of exclusion
  reason codes with human-readable descriptions.
* :class:`ScreeningRecord`    — a single paper under screening (paper
  id, DOI, title, authors, year, source, current stage, decision,
  reviewer, exclusion reason, free-text notes, conflict log,
  screening date).
* :class:`ScreeningManager`   — an in-memory store + workflow façade
  that ingests :class:`~data_acquisition.base_scraper.ScraperResult`
  objects, supports per-record screening decisions, dual-reviewer
  assignment, automatic deduplication, inter-rater-agreement
  computation (Cohen's / Fleiss' kappa), conflict detection /
  resolution, and export to CSV / XLSX.

The store is intentionally pure-Python (no SQLite dependency) so it
remains importable in headless / unit-test environments. Heavy deps
(``pandas``, ``numpy``, ``openpyxl``) are imported lazily inside the
methods that require them.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#

from __future__ import annotations

import csv
import logging
import re
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ScreeningStage(Enum):
    """PRISMA screening stages a record may occupy."""

    IDENTIFICATION = "identification"
    TITLE_ABSTRACT = "title_abstract"
    FULL_TEXT = "full_text"
    INCLUDED = "included"
    EXCLUDED = "excluded"

    @classmethod
    def from_value(cls, value: Union[str, "ScreeningStage"]) -> "ScreeningStage":
        """Coerce a string or enum member to a :class:`ScreeningStage`."""
        if isinstance(value, cls):
            return value
        v = str(value).strip().lower()
        for member in cls:
            if member.value == v or member.name.lower() == v:
                return member
        raise ValueError(f"Unknown ScreeningStage: {value!r}")


class ScreeningDecision(Enum):
    """Per-reviewer decision on a record at a screening stage."""

    INCLUDE = "include"
    EXCLUDE = "exclude"
    MAYBE = "maybe"
    PENDING = "pending"

    @classmethod
    def from_value(cls, value: Union[str, "ScreeningDecision"]) -> "ScreeningDecision":
        if isinstance(value, cls):
            return value
        v = str(value).strip().lower()
        for member in cls:
            if member.value == v or member.name.lower() == v:
                return member
        raise ValueError(f"Unknown ScreeningDecision: {value!r}")


class ExclusionReasons(Enum):
    """Controlled vocabulary of exclusion reason codes.

    Each member's value is the short machine-readable code; the
    :attr:`description` property returns a human-readable label.
    """

    NOT_RELEVANT_TOPIC = "not_relevant_topic"
    WRONG_POPULATION = "wrong_population"
    WRONG_INTERVENTION = "wrong_intervention"
    WRONG_OUTCOME = "wrong_outcome"
    WRONG_STUDY_DESIGN = "wrong_study_design"
    NOT_PEER_REVIEWED = "not_peer_reviewed"
    DUPLICATE = "duplicate"
    NON_ENGLISH_LANGUAGE = "non_english_language"
    NO_FULL_TEXT = "no_full_text"
    RETRACTED = "retracted"
    OTHER = "other"

    @property
    def description(self) -> str:
        """Return a human-readable description of this reason code."""
        return _EXCLUSION_DESCRIPTIONS.get(self, self.value)

    @classmethod
    def from_value(cls, value: Union[str, "ExclusionReasons"]) -> "ExclusionReasons":
        if isinstance(value, cls):
            return value
        v = str(value).strip().lower()
        for member in cls:
            if member.value == v or member.name.lower() == v:
                return member
        # tolerate human-readable labels
        for member, desc in _EXCLUSION_DESCRIPTIONS.items():
            if desc.lower() == v:
                return member
        raise ValueError(f"Unknown ExclusionReasons: {value!r}")


_EXCLUSION_DESCRIPTIONS: Dict[ExclusionReasons, str] = {
    ExclusionReasons.NOT_RELEVANT_TOPIC: "Not relevant to the review topic",
    ExclusionReasons.WRONG_POPULATION: "Wrong population",
    ExclusionReasons.WRONG_INTERVENTION: "Wrong intervention / exposure",
    ExclusionReasons.WRONG_OUTCOME: "Wrong outcome measured",
    ExclusionReasons.WRONG_STUDY_DESIGN: "Wrong study design",
    ExclusionReasons.NOT_PEER_REVIEWED: "Not peer-reviewed (e.g. preprint, conference abstract only)",
    ExclusionReasons.DUPLICATE: "Duplicate of another record",
    ExclusionReasons.NON_ENGLISH_LANGUAGE: "Non-English language with no translation available",
    ExclusionReasons.NO_FULL_TEXT: "Full text unavailable",
    ExclusionReasons.RETRACTED: "Article has been retracted",
    ExclusionReasons.OTHER: "Other (see notes)",
}


# ---------------------------------------------------------------------------
# ScreeningRecord
# ---------------------------------------------------------------------------

@dataclass
class ScreeningRecord:
    """A single paper under screening.

    Attributes:
        paper_id: Stable internal identifier. Auto-generated if absent.
        doi: Optional DOI (lower-cased for dedup).
        title: Article title.
        authors: List of author names.
        year: Publication year.
        source: Originating database / scraper name.
        stage: Current :class:`ScreeningStage`.
        decision: Current :class:`ScreeningDecision`.
        reviewer: Name of the most recent reviewer.
        exclusion_reason_code: Optional :class:`ExclusionReasons` code.
        exclusion_reason_text: Free-text explanation for exclusion.
        screening_date: ISO-8601 UTC timestamp of last action.
        notes: Free-text reviewer notes.
        conflicts: List of conflict descriptions (reviewer disagreements).
        reviewer_decisions: Mapping of reviewer_name -> decision value
            (used to detect conflicts and compute inter-rater agreement).
    """

    paper_id: str = ""
    doi: Optional[str] = None
    title: str = ""
    authors: List[str] = field(default_factory=list)
    year: Optional[int] = None
    source: str = ""
    stage: ScreeningStage = ScreeningStage.IDENTIFICATION
    decision: ScreeningDecision = ScreeningDecision.PENDING
    reviewer: str = ""
    exclusion_reason_code: Optional[ExclusionReasons] = None
    exclusion_reason_text: str = ""
    screening_date: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    notes: str = ""
    conflicts: List[str] = field(default_factory=list)
    reviewer_decisions: Dict[str, str] = field(default_factory=dict)
    #: Raw payload from the originating scraper (for forensic use).
    raw: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.paper_id:
            self.paper_id = f"rec-{uuid.uuid4().hex[:10]}"
        if isinstance(self.stage, str):
            self.stage = ScreeningStage.from_value(self.stage)
        if isinstance(self.decision, str):
            self.decision = ScreeningDecision.from_value(self.decision)
        if isinstance(self.exclusion_reason_code, str):
            try:
                self.exclusion_reason_code = ExclusionReasons.from_value(
                    self.exclusion_reason_code
                )
            except ValueError:
                logger.warning(
                    "Unrecognised exclusion_reason_code %r on record %s; "
                    "storing as OTHER", self.exclusion_reason_code, self.paper_id
                )
                self.exclusion_reason_code = ExclusionReasons.OTHER
        # normalise DOI for dedup
        if self.doi:
            self.doi = self.doi.strip().lower().lstrip("https://doi.org/").lstrip(
                "http://doi.org/"
            )

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of this record."""
        return {
            "paper_id": self.paper_id,
            "doi": self.doi,
            "title": self.title,
            "authors": list(self.authors),
            "year": self.year,
            "source": self.source,
            "stage": self.stage.value,
            "decision": self.decision.value,
            "reviewer": self.reviewer,
            "exclusion_reason_code": (
                self.exclusion_reason_code.value
                if self.exclusion_reason_code
                else None
            ),
            "exclusion_reason_text": self.exclusion_reason_text,
            "screening_date": self.screening_date,
            "notes": self.notes,
            "conflicts": list(self.conflicts),
            "reviewer_decisions": dict(self.reviewer_decisions),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScreeningRecord":
        """Reconstruct a :class:`ScreeningRecord` from a dict."""
        d = dict(data)
        if "stage" in d:
            d["stage"] = ScreeningStage.from_value(d["stage"])
        if "decision" in d:
            d["decision"] = ScreeningDecision.from_value(d["decision"])
        if d.get("exclusion_reason_code"):
            d["exclusion_reason_code"] = ExclusionReasons.from_value(
                d["exclusion_reason_code"]
            )
        valid = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in d.items() if k in valid}
        return cls(**filtered)


# ---------------------------------------------------------------------------
# ScreeningManager
# ---------------------------------------------------------------------------

class ScreeningManager:
    """In-memory store + workflow façade for screening records.

    The manager supports dual-reviewer screening, automatic
    deduplication (by DOI and title similarity), inter-rater agreement
    computation (Cohen's kappa for two reviewers, Fleiss' kappa for
    three or more), conflict detection / resolution, and export to
    CSV / XLSX.
    """

    def __init__(self) -> None:
        self._records: Dict[str, ScreeningRecord] = {}
        # index for dedup: lowercased doi -> paper_id ; title fingerprint -> paper_id
        self._doi_index: Dict[str, str] = {}
        self._title_index: Dict[str, str] = {}
        self._lock_holder: Optional[str] = None  # placeholder for future locking

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def load_from_search(self, results: Any) -> int:
        """Bulk-import papers from a :class:`ScraperResult`-like object.

        The argument is duck-typed: any object exposing a ``papers``
        attribute whose items expose ``title`` / ``authors`` / ``doi`` /
        ``year`` / ``source`` attributes (or keys, if dict-like) is
        accepted. A list of papers is also accepted directly.

        Args:
            results: A :class:`~data_acquisition.base_scraper.ScraperResult`,
                an iterable of ``Paper`` objects, or a list of dicts.

        Returns:
            Number of records actually inserted (after dedup).
        """
        papers = self._coerce_papers(results)
        inserted = 0
        for paper in papers:
            title = self._get(paper, "title", "") or ""
            doi = self._get(paper, "doi", None)
            authors = self._get(paper, "authors", []) or []
            year = self._get(paper, "year", None)
            source = self._get(paper, "source", "") or ""
            raw = self._get(paper, "raw", {}) or {}
            if not isinstance(raw, dict):
                raw = {"_value": raw}
            if not title and not doi:
                # nothing to identify the record by
                continue
            # dedup check
            if doi and doi.strip().lower() in self._doi_index:
                logger.debug("Skipping duplicate DOI: %s", doi)
                continue
            title_fp = self._title_fingerprint(title)
            if title_fp and title_fp in self._title_index:
                logger.debug("Skipping duplicate title: %s", title)
                continue
            record = ScreeningRecord(
                doi=doi,
                title=title,
                authors=list(authors),
                year=year,
                source=source,
                stage=ScreeningStage.IDENTIFICATION,
                decision=ScreeningDecision.PENDING,
                raw=raw,
            )
            self._records[record.paper_id] = record
            if doi:
                self._doi_index[doi.strip().lower()] = record.paper_id
            if title_fp:
                self._title_index[title_fp] = record.paper_id
            inserted += 1
        logger.info("Loaded %d new records (of %d provided)", inserted, len(papers))
        return inserted

    @staticmethod
    def _coerce_papers(results: Any) -> List[Any]:
        """Coerce a ``ScraperResult`` / iterable / dict into a list of papers."""
        if results is None:
            return []
        if hasattr(results, "papers"):
            return list(results.papers or [])
        if isinstance(results, list):
            return results
        if isinstance(results, dict) and "papers" in results:
            return list(results.get("papers") or [])
        # single paper-like object
        if hasattr(results, "title") or isinstance(results, dict):
            return [results]
        return []

    @staticmethod
    def _get(obj: Any, key: str, default: Any = None) -> Any:
        """Get attribute or dict key from a paper-like object."""
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    @staticmethod
    def _title_fingerprint(title: str) -> str:
        """Return a normalised fingerprint of a title for dedup."""
        if not title:
            return ""
        # strip punctuation, collapse whitespace, lowercase
        cleaned = re.sub(r"[^\w\s]", " ", title.lower())
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    # ------------------------------------------------------------------
    # Record access
    # ------------------------------------------------------------------

    @property
    def records(self) -> List[ScreeningRecord]:
        """Return a shallow list of all records."""
        return list(self._records.values())

    def get_record(self, record_id: str) -> Optional[ScreeningRecord]:
        """Return a single record by ``paper_id`` (or ``None``)."""
        return self._records.get(record_id)

    def __len__(self) -> int:
        return len(self._records)

    def __contains__(self, record_id: object) -> bool:
        return isinstance(record_id, str) and record_id in self._records

    # ------------------------------------------------------------------
    # Screening actions
    # ------------------------------------------------------------------

    def screen_title_abstract(
        self,
        record_id: str,
        decision: Union[str, ScreeningDecision],
        reviewer: str,
        exclusion_reason: Optional[Union[str, ExclusionReasons]] = None,
        notes: str = "",
    ) -> ScreeningRecord:
        """Record a title/abstract screening decision.

        Promotes the record to :attr:`ScreeningStage.TITLE_ABSTRACT`
        (or :attr:`ScreeningStage.EXCLUDED` / :attr:`ScreeningStage.FULL_TEXT`
        depending on the decision).

        Args:
            record_id: The record's ``paper_id``.
            decision: ``include`` / ``exclude`` / ``maybe`` / ``pending``.
            reviewer: Name of the reviewer.
            exclusion_reason: Required if decision is ``exclude``.
            notes: Free-text reviewer notes.

        Returns:
            The updated :class:`ScreeningRecord`.

        Raises:
            KeyError: If ``record_id`` is unknown.
            ValueError: If exclusion decision is given without a reason.
        """
        record = self._require(record_id)
        decision_enum = ScreeningDecision.from_value(decision)
        reviewer = (reviewer or "").strip()
        if decision_enum == ScreeningDecision.EXCLUDE and not exclusion_reason:
            raise ValueError(
                "An exclusion_reason must be supplied when decision='exclude'"
            )
        # track per-reviewer decision (used for conflict + kappa)
        if reviewer:
            record.reviewer_decisions[reviewer] = decision_enum.value
        record.reviewer = reviewer or record.reviewer
        record.decision = decision_enum
        record.notes = notes or record.notes
        record.screening_date = datetime.now(timezone.utc).isoformat()
        record.stage = ScreeningStage.TITLE_ABSTRACT
        if decision_enum == ScreeningDecision.EXCLUDE:
            record.stage = ScreeningStage.EXCLUDED
            if exclusion_reason:
                record.exclusion_reason_code = ExclusionReasons.from_value(
                    exclusion_reason
                )
            record.exclusion_reason_text = (
                record.exclusion_reason_code.description
                if record.exclusion_reason_code
                else record.exclusion_reason_text
            )
        elif decision_enum == ScreeningDecision.INCLUDE:
            # promote to full-text stage
            record.stage = ScreeningStage.FULL_TEXT
        # conflict detection
        self._maybe_flag_conflict(record)
        return record

    def screen_full_text(
        self,
        record_id: str,
        decision: Union[str, ScreeningDecision],
        reviewer: str,
        exclusion_reason: Optional[Union[str, ExclusionReasons]] = None,
        notes: str = "",
    ) -> ScreeningRecord:
        """Record a full-text screening decision.

        Args:
            record_id: The record's ``paper_id``.
            decision: ``include`` / ``exclude`` / ``maybe`` / ``pending``.
            reviewer: Name of the reviewer.
            exclusion_reason: Required if decision is ``exclude``.
            notes: Free-text reviewer notes.

        Returns:
            The updated :class:`ScreeningRecord`.
        """
        record = self._require(record_id)
        decision_enum = ScreeningDecision.from_value(decision)
        reviewer = (reviewer or "").strip()
        if decision_enum == ScreeningDecision.EXCLUDE and not exclusion_reason:
            raise ValueError(
                "An exclusion_reason must be supplied when decision='exclude'"
            )
        if reviewer:
            record.reviewer_decisions[reviewer] = decision_enum.value
        record.reviewer = reviewer or record.reviewer
        record.decision = decision_enum
        record.notes = notes or record.notes
        record.screening_date = datetime.now(timezone.utc).isoformat()
        record.stage = ScreeningStage.FULL_TEXT
        if decision_enum == ScreeningDecision.INCLUDE:
            record.stage = ScreeningStage.INCLUDED
        elif decision_enum == ScreeningDecision.EXCLUDE:
            record.stage = ScreeningStage.EXCLUDED
            if exclusion_reason:
                record.exclusion_reason_code = ExclusionReasons.from_value(
                    exclusion_reason
                )
            record.exclusion_reason_text = (
                record.exclusion_reason_code.description
                if record.exclusion_reason_code
                else record.exclusion_reason_text
            )
        self._maybe_flag_conflict(record)
        return record

    def assign_reviewer(self, record_id: str, reviewer_name: str) -> ScreeningRecord:
        """Assign / announce a reviewer for a record (no decision recorded).

        Useful for distributing work among reviewers before they make
        a decision. The reviewer is added to ``reviewer_decisions`` with
        the ``pending`` sentinel if they have not yet decided.
        """
        record = self._require(record_id)
        reviewer_name = (reviewer_name or "").strip()
        if not reviewer_name:
            raise ValueError("reviewer_name must not be empty")
        record.reviewer = reviewer_name
        record.reviewer_decisions.setdefault(reviewer_name, ScreeningDecision.PENDING.value)
        return record

    def _require(self, record_id: str) -> ScreeningRecord:
        record = self._records.get(record_id)
        if record is None:
            raise KeyError(f"Unknown record_id: {record_id!r}")
        return record

    def _maybe_flag_conflict(self, record: ScreeningRecord) -> None:
        """Flag a conflict if 2+ reviewers disagree on the same record."""
        decisions = [
            v for v in record.reviewer_decisions.values()
            if v != ScreeningDecision.PENDING.value
        ]
        if len(set(decisions)) >= 2 and len(decisions) >= 2:
            msg = (
                f"Reviewer disagreement on {record.paper_id}: "
                + ", ".join(
                    f"{r}={d}" for r, d in record.reviewer_decisions.items()
                    if d != ScreeningDecision.PENDING.value
                )
            )
            if msg not in record.conflicts:
                record.conflicts.append(msg)
                logger.info("Conflict flagged: %s", msg)

    # ------------------------------------------------------------------
    # Dedup
    # ------------------------------------------------------------------

    def auto_dedup(self) -> int:
        """Find and merge DOI / title duplicates; return number merged.

        Merging keeps the first record encountered and copies over any
        reviewer decisions from the duplicate. The duplicate is then
        removed from the store and its paper_id is left as a tombstone
        in the kept record's ``raw['_merged_from']`` list.
        """
        seen_doi: Dict[str, str] = {}
        seen_title: Dict[str, str] = {}
        merged = 0
        for record in list(self._records.values()):
            keep_id: Optional[str] = None
            if record.doi and record.doi in seen_doi:
                keep_id = seen_doi[record.doi]
            title_fp = self._title_fingerprint(record.title)
            if keep_id is None and title_fp and title_fp in seen_title:
                keep_id = seen_title[title_fp]
            if keep_id is None:
                if record.doi:
                    seen_doi[record.doi] = record.paper_id
                if title_fp:
                    seen_title[title_fp] = record.paper_id
                continue
            # merge into keep
            keeper = self._records[keep_id]
            for r, d in record.reviewer_decisions.items():
                keeper.reviewer_decisions.setdefault(r, d)
            keeper.conflicts.extend(record.conflicts)
            keeper.raw.setdefault("_merged_from", []).append(record.paper_id)
            # remove duplicate
            self._records.pop(record.paper_id, None)
            if record.doi:
                self._doi_index.pop(record.doi, None)
            if title_fp:
                self._title_index.pop(title_fp, None)
            merged += 1
            logger.info(
                "Merged duplicate %s into %s", record.paper_id, keep_id
            )
        return merged

    # ------------------------------------------------------------------
    # Progress + conflicts
    # ------------------------------------------------------------------

    def progress(self) -> Dict[str, int]:
        """Return counts per screening stage."""
        counts: Counter[str] = Counter()
        for r in self._records.values():
            counts[r.stage.value] += 1
        # ensure all stages are present even if zero
        for stage in ScreeningStage:
            counts.setdefault(stage.value, 0)
        counts["total"] = len(self._records)
        return dict(counts)

    def conflict_records(self) -> List[ScreeningRecord]:
        """Return all records flagged with at least one conflict."""
        return [r for r in self._records.values() if r.conflicts]

    def resolve_conflict(
        self,
        record_id: str,
        final_decision: Union[str, ScreeningDecision],
        resolver: str,
        rationale: str = "",
    ) -> ScreeningRecord:
        """Resolve a reviewer conflict with a final decision.

        Args:
            record_id: Record to resolve.
            final_decision: The adjudicated decision.
            resolver: Name of the third-party resolver.
            rationale: Free-text rationale.

        Returns:
            The updated :class:`ScreeningRecord`.
        """
        record = self._require(record_id)
        decision_enum = ScreeningDecision.from_value(final_decision)
        record.decision = decision_enum
        record.reviewer = (resolver or record.reviewer or "resolver").strip()
        record.reviewer_decisions[record.reviewer] = decision_enum.value
        if rationale:
            record.notes = (record.notes + "\n" if record.notes else "") + (
                f"[Conflict resolution by {record.reviewer}]: {rationale}"
            )
        record.conflicts.append(
            f"RESOLVED by {record.reviewer} -> {decision_enum.value}"
        )
        record.screening_date = datetime.now(timezone.utc).isoformat()
        # promote/demote stage based on final decision
        if decision_enum == ScreeningDecision.INCLUDE:
            # if previously at TITLE_ABSTRACT, promote to FULL_TEXT;
            # if at FULL_TEXT, promote to INCLUDED
            if record.stage == ScreeningStage.TITLE_ABSTRACT:
                record.stage = ScreeningStage.FULL_TEXT
            else:
                record.stage = ScreeningStage.INCLUDED
        elif decision_enum == ScreeningDecision.EXCLUDE:
            record.stage = ScreeningStage.EXCLUDED
        return record

    # ------------------------------------------------------------------
    # Inter-rater agreement
    # ------------------------------------------------------------------

    def inter_rater_agreement(
        self, method: str = "cohen_kappa", stage: Optional[Union[str, ScreeningStage]] = None
    ) -> float:
        """Compute inter-rater agreement (kappa) across screened records.

        Args:
            method: ``'cohen_kappa'`` (exactly 2 reviewers) or
                ``'fleiss_kappa'`` (>= 2 reviewers).
            stage: Optional stage filter (default: all reviewed records
                with at least one non-pending decision).

        Returns:
            The kappa statistic in ``[-1, 1]``. Returns ``0.0`` when
            no record has 2+ reviewers (Cohen) or when there are no
            reviewable records (Fleiss).
        """
        method = (method or "cohen_kappa").strip().lower()
        if method not in {"cohen_kappa", "fleiss_kappa"}:
            raise ValueError(
                f"Unsupported method: {method!r}. Use 'cohen_kappa' or 'fleiss_kappa'."
            )
        stage_enum = ScreeningStage.from_value(stage) if stage else None
        # collect per-record reviewer decisions (excluding pending)
        records_decisions: List[Dict[str, str]] = []
        for r in self._records.values():
            if stage_enum and r.stage != stage_enum:
                continue
            d = {
                rv: dv for rv, dv in r.reviewer_decisions.items()
                if dv != ScreeningDecision.PENDING.value
            }
            if len(d) >= 2:
                records_decisions.append(d)
        if not records_decisions:
            return 0.0
        if method == "cohen_kappa":
            return self._cohen_kappa(records_decisions)
        return self._fleiss_kappa(records_decisions)

    @staticmethod
    def _cohen_kappa(records_decisions: List[Dict[str, str]]) -> float:
        """Compute Cohen's kappa across records reviewed by 2+ reviewers.

        For records reviewed by more than 2 reviewers we take the
        first two reviewers encountered (deterministic by insertion
        order). This is a deliberate simplification — for >2 reviewers
        prefer :meth:`_fleiss_kappa`.
        """
        # gather paired decisions
        pairs: List[Tuple[str, str]] = []
        for d in records_decisions:
            vals = list(d.values())
            if len(vals) >= 2:
                pairs.append((vals[0], vals[1]))
        n = len(pairs)
        if n == 0:
            return 0.0
        # observed agreement
        agree = sum(1 for a, b in pairs if a == b)
        po = agree / n
        # marginal probabilities
        a_counter: Counter[str] = Counter(a for a, _ in pairs)
        b_counter: Counter[str] = Counter(b for _, b in pairs)
        categories = set(a_counter) | set(b_counter)
        pe = sum((a_counter[c] / n) * (b_counter[c] / n) for c in categories)
        if pe == 1.0:
            return 1.0
        return (po - pe) / (1.0 - pe)

    @staticmethod
    def _fleiss_kappa(records_decisions: List[Dict[str, str]]) -> float:
        """Compute Fleiss' kappa across records reviewed by >=2 reviewers.

        Each record contributes one row; each cell is the count of
        reviewers who chose that category. The number of raters per
        record may vary; the standard Fleiss formula assumes a fixed
        number of raters per item — we use the **mean number of
        raters** as the per-item n, which is the recommended
        generalisation when rater counts vary (Gwet 2008).
        """
        if not records_decisions:
            return 0.0
        # collect categories
        categories: set[str] = set()
        for d in records_decisions:
            categories.update(d.values())
        categories = sorted(categories)
        cat_idx = {c: i for i, c in enumerate(categories)}
        n_items = len(records_decisions)
        # build count matrix
        rows: List[List[int]] = []
        n_per_item: List[int] = []
        for d in records_decisions:
            counts = [0] * len(categories)
            for v in d.values():
                counts[cat_idx[v]] += 1
            rows.append(counts)
            n_per_item.append(sum(counts))
        n_mean = sum(n_per_item) / n_items
        if n_mean <= 1:
            return 0.0
        # P(i) for each item: (1/(n(n-1))) * sum_j n_ij*(n_ij-1)
        p_i = []
        for counts, ni in zip(rows, n_per_item):
            if ni <= 1:
                p_i.append(0.0)
                continue
            s = sum(c * (c - 1) for c in counts)
            p_i.append(s / (ni * (ni - 1)))
        p_bar = sum(p_i) / n_items
        # category marginal proportions
        n_total = sum(n_per_item)
        p_j = []
        for j in range(len(categories)):
            s = sum(rows[i][j] for i in range(n_items))
            p_j.append(s / n_total if n_total else 0.0)
        pe = sum(p * p for p in p_j)
        if pe == 1.0:
            return 1.0
        if (1.0 - pe) == 0:
            return 1.0
        return (p_bar - pe) / (1.0 - pe)

    @staticmethod
    def kappa_interpretation(kappa: float) -> str:
        """Return a Landis-Koch (1977) band for ``kappa``.

        Bands: poor (<0), slight (0–0.20), fair (0.21–0.40),
        moderate (0.41–0.60), substantial (0.61–0.80),
        almost perfect (0.81–1.00).
        """
        k = float(kappa)
        if k < 0:
            return "poor"
        if k <= 0.20:
            return "slight"
        if k <= 0.40:
            return "fair"
        if k <= 0.60:
            return "moderate"
        if k <= 0.80:
            return "substantial"
        return "almost perfect"

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def to_dataframe(self):
        """Return all records as a :class:`pandas.DataFrame`."""
        try:
            import pandas as pd  # type: ignore
        except ImportError as exc:  # pragma: no cover - pandas is a declared dep
            raise RuntimeError("pandas is required for to_dataframe()") from exc
        rows = [r.to_dict() for r in self._records.values()]
        df = pd.DataFrame(rows)
        if not df.empty:
            # serialise nested fields as JSON strings for CSV friendliness
            for col in ("authors", "conflicts", "reviewer_decisions"):
                if col in df.columns:
                    df[col] = df[col].apply(
                        lambda v: ";".join(v) if isinstance(v, list) else v
                        if not isinstance(v, dict) else ";".join(
                            f"{k}={vv}" for k, vv in v.items()
                        )
                    )
        return df

    def export_decisions(self, path: str, format: str = "csv") -> str:
        """Export all records to ``path`` in CSV or XLSX format.

        Args:
            path: Destination file path.
            format: ``'csv'`` or ``'xlsx'``.

        Returns:
            The ``path`` argument.
        """
        format = (format or "csv").strip().lower()
        df = self.to_dataframe()
        if format == "csv":
            df.to_csv(path, index=False, quoting=csv.QUOTE_MINIMAL)
        elif format in {"xlsx", "xls"}:
            try:
                import openpyxl  # type: ignore  # noqa: F401
            except ImportError as exc:  # pragma: no cover
                raise RuntimeError(
                    "openpyxl is required for XLSX export"
                ) from exc
            df.to_excel(path, index=False, engine="openpyxl")
        else:
            raise ValueError(f"Unsupported export format: {format!r}")
        logger.info("Exported %d records to %s", len(df), path)
        return path
