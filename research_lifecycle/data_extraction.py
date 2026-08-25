"""Structured data-extraction templates and an interactive extraction session.

This module ships ready-to-use extraction forms aligned with major
reporting guidelines and methodology references:

* :meth:`ExtractionTemplateLibrary.cochrane_rct` — full Cochrane RCT
  extraction form (35+ fields) covering bibliographic data, population,
  intervention, comparator, outcomes, analysis, RoB and notes.
* :meth:`ExtractionTemplateLibrary.observational` — generic form for
  cohort / case-control / cross-sectional studies.
* :meth:`ExtractionTemplateLibrary.qualitative` — thematic / framework
  analysis extraction.
* :meth:`ExtractionTemplateLibrary.mixed_methods` — convergent /
  explanatory / exploratory mixed-methods extraction.
* :meth:`ExtractionTemplateLibrary.bibliometric` — author / year /
  citations / affiliations / methods / datasets extraction.
* :meth:`ExtractionTemplateLibrary.content_analysis` — media / textual
  content-analysis extraction.
* :meth:`ExtractionTemplateLibrary.survey_research` — survey items +
  Likert + demographics extraction.

The :class:`ExtractionSession` class wraps a single study's extraction
against a template: it tracks values, validates required fields and
field types, and serialises to YAML / JSON (with lazy imports of
``yaml`` and ``json`` so the module is importable everywhere).
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Union

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Field types
# ---------------------------------------------------------------------------
# A constrained vocabulary of field "types" — kept lowercase so callers
# can lookup by string. Each type drives validation in
# :meth:`ExtractionSession.validate`.
FieldType = str  # alias; values documented below.

VALID_FIELD_TYPES = (
    "text",
    "number",
    "date",
    "select",
    "multiselect",
    "boolean",
    "rating",
    "likert",
    "file",
    "reference",
)


@dataclass
class ExtractionField:
    """A single field in an :class:`ExtractionTemplate`.

    Attributes:
        name: Machine-friendly identifier (snake_case).
        label: Human-readable label.
        type: One of :data:`VALID_FIELD_TYPES`.
        required: Whether the field must be filled.
        options: For ``select`` / ``multiselect`` / ``likert`` types,
            the list of permitted options.
        default_value: Optional default.
        help_text: Inline help text.
    """

    name: str
    label: str
    type: FieldType = "text"
    required: bool = False
    options: List[str] = field(default_factory=list)
    default_value: Any = None
    help_text: str = ""


@dataclass
class ExtractionTemplate:
    """A reusable extraction form definition.

    Attributes:
        name: Template identifier.
        fields: Ordered list of :class:`ExtractionField`.
    """

    name: str
    fields: List[ExtractionField] = field(default_factory=list)

    def field_names(self) -> List[str]:
        """Return the ordered list of field names."""
        return [f.name for f in self.fields]

    def field(self, name: str) -> Optional[ExtractionField]:
        """Return the :class:`ExtractionField` named ``name`` or None."""
        for f in self.fields:
            if f.name == name:
                return f
        return None


# ---------------------------------------------------------------------------
# Template library
# ---------------------------------------------------------------------------
class ExtractionTemplateLibrary:
    """Factory of pre-built extraction templates."""

    # ------------------------------------------------------------------
    # Cochrane RCT (35+ fields)
    # ------------------------------------------------------------------
    @classmethod
    def cochrane_rct(cls) -> ExtractionTemplate:
        """Return the full Cochrane RCT extraction form (35+ fields)."""
        f = ExtractionField
        fields = [
            # Bibliographic
            f("study_id", "Study ID", "text", required=True,
              help_text="Unique identifier for this study in your review."),
            f("title", "Title", "text", required=True),
            f("authors", "Authors", "text", required=True),
            f("year", "Year", "number", required=True),
            f("journal", "Journal", "text"),
            f("doi", "DOI", "text"),
            f("country", "Country", "text"),
            f("language", "Language", "text"),
            # Design
            f("study_design", "Study design", "select", required=True,
              options=["parallel", "crossover", "cluster", "factorial"]),
            f("phase", "Trial phase", "select",
              options=["I", "II", "III", "IV", "pilot"]),
            f("registration_id", "Trial registration ID", "text"),
            # Population
            f("population_description", "Population description", "text",
              required=True),
            f("inclusion_criteria", "Inclusion criteria", "text", required=True),
            f("exclusion_criteria", "Exclusion criteria", "text"),
            f("n_randomized", "N randomised", "number", required=True),
            f("n_analyzed", "N analysed", "number"),
            f("age_mean", "Mean age (years)", "number"),
            f("age_sd", "Age SD", "number"),
            f("female_pct", "Female (%)", "number"),
            # Intervention
            f("intervention_description", "Intervention description", "text",
              required=True),
            f("intervention_dose", "Dose / intensity", "text"),
            f("intervention_duration", "Duration", "text"),
            f("intervention_deliverers", "Deliverers", "text"),
            f("comparator_description", "Comparator description", "text",
              required=True),
            # Outcomes
            f("primary_outcome", "Primary outcome", "text", required=True),
            f("primary_outcome_measure", "Measure", "text"),
            f("primary_outcome_timepoint", "Timepoint", "text"),
            f("intervention_effect_estimate", "Effect estimate", "number"),
            f("effect_measure_type", "Effect measure type", "select",
              options=["MD", "SMD", "RR", "OR", "HR", "RD", "other"]),
            f("ci_lower", "95% CI lower", "number"),
            f("ci_upper", "95% CI upper", "number"),
            f("p_value", "p-value", "number"),
            f("secondary_outcomes", "Secondary outcomes", "text"),
            f("adverse_events", "Adverse events", "text"),
            # Analysis
            f("analysis_type", "Analysis type", "select",
              options=["ITT", "mITT", "per-protocol", "as-treated"]),
            f("missing_data_handling", "Missing-data handling", "text"),
            # Risk of bias (RoB 2)
            f("rob_randomization", "RoB: randomisation", "select", required=True,
              options=["low", "some concerns", "high", "no information"]),
            f("rob_deviations", "RoB: deviations", "select",
              options=["low", "some concerns", "high", "no information"]),
            f("rob_missing", "RoB: missing data", "select",
              options=["low", "some concerns", "high", "no information"]),
            f("rob_measurement", "RoB: measurement", "select",
              options=["low", "some concerns", "high", "no information"]),
            f("rob_selection", "RoB: reported result selection", "select",
              options=["low", "some concerns", "high", "no information"]),
            f("rob_overall", "RoB: overall", "select", required=True,
              options=["low", "some concerns", "high", "no information"]),
            # Notes
            f("extraction_notes", "Notes", "text"),
            f("extraction_date", "Extraction date", "date", required=True),
        ]
        return ExtractionTemplate(name="cochrane_rct", fields=fields)

    # ------------------------------------------------------------------
    # Observational (cohort / case-control / cross-sectional)
    # ------------------------------------------------------------------
    @classmethod
    def observational(cls) -> ExtractionTemplate:
        """Return a generic observational-study extraction form."""
        f = ExtractionField
        fields = [
            f("study_id", "Study ID", "text", required=True),
            f("title", "Title", "text", required=True),
            f("authors", "Authors", "text", required=True),
            f("year", "Year", "number", required=True),
            f("journal", "Journal", "text"),
            f("doi", "DOI", "text"),
            f("country", "Country", "text"),
            f("study_design", "Study design", "select", required=True,
              options=["cohort", "case-control", "cross-sectional",
                       "longitudinal", "panel"]),
            f("setting", "Setting", "text", required=True),
            f("population", "Population", "text", required=True),
            f("n_total", "N total", "number", required=True),
            f("n_exposed", "N exposed", "number"),
            f("n_unexposed", "N unexposed", "number"),
            f("exposure", "Exposure definition", "text", required=True),
            f("exposure_measurement", "Exposure measurement", "text"),
            f("outcome", "Outcome definition", "text", required=True),
            f("outcome_measurement", "Outcome measurement", "text"),
            f("followup_duration", "Follow-up duration", "text"),
            f("confounders_adjusted", "Confounders adjusted", "text"),
            f("effect_estimate", "Effect estimate", "number"),
            f("effect_measure_type", "Effect measure type", "select",
              options=["RR", "OR", "HR", "IRR", "SMD", "MD", "beta", "other"]),
            f("ci_lower", "95% CI lower", "number"),
            f("ci_upper", "95% CI upper", "number"),
            f("p_value", "p-value", "number"),
            f("rob_selection", "Selection bias", "select",
              options=["low", "moderate", "high", "unclear"]),
            f("rob_confounding", "Confounding", "select",
              options=["low", "moderate", "high", "unclear"]),
            f("rob_measurement", "Measurement bias", "select",
              options=["low", "moderate", "high", "unclear"]),
            f("rob_attrition", "Attrition bias", "select",
              options=["low", "moderate", "high", "unclear"]),
            f("rob_reporting", "Reporting bias", "select",
              options=["low", "moderate", "high", "unclear"]),
            f("extraction_notes", "Notes", "text"),
            f("extraction_date", "Extraction date", "date", required=True),
        ]
        return ExtractionTemplate(name="observational", fields=fields)

    # ------------------------------------------------------------------
    # Qualitative (thematic / framework analysis)
    # ------------------------------------------------------------------
    @classmethod
    def qualitative(cls) -> ExtractionTemplate:
        """Return a qualitative-study extraction form."""
        f = ExtractionField
        fields = [
            f("study_id", "Study ID", "text", required=True),
            f("title", "Title", "text", required=True),
            f("authors", "Authors", "text", required=True),
            f("year", "Year", "number", required=True),
            f("methodology", "Methodology", "select", required=True,
              options=["phenomenology", "grounded theory", "ethnography",
                       "framework analysis", "case study", "narrative",
                       "thematic analysis", "other"]),
            f("paradigm", "Paradigm", "select",
              options=["interpretivist", "constructivist", "critical",
                       "pragmatic", "post-positivist", "other"]),
            f("research_questions", "Research questions", "text", required=True),
            f("participants_n", "N participants", "number", required=True),
            f("sampling_strategy", "Sampling strategy", "select",
              options=["purposive", "theoretical", "snowball",
                       "convenience", "maximum variation", "other"]),
            f("data_collection", "Data collection methods", "multiselect",
              options=["in-depth interviews", "semi-structured interviews",
                       "focus groups", "participant observation",
                       "document analysis", "diaries", "visual methods"]),
            f("interviewer_relationship", "Interviewer-interviewee relationship",
              "text"),
            f("analysis_method", "Analysis method", "select",
              options=["thematic", "framework", "grounded theory",
                       "constant comparison", "template analysis",
                       "interpretive phenomenological analysis", "other"]),
            f("software_used", "Software used", "text"),
            f("saturation", "Saturation criteria", "text"),
            f("trustworthiness", "Trustworthiness measures", "text"),
            f("reflexivity", "Reflexivity statement", "text"),
            f("themes_identified", "Themes identified", "text", required=True),
            f("key_quotes", "Key quotes", "text"),
            f("extraction_notes", "Notes", "text"),
            f("extraction_date", "Extraction date", "date", required=True),
        ]
        return ExtractionTemplate(name="qualitative", fields=fields)

    # ------------------------------------------------------------------
    # Mixed methods
    # ------------------------------------------------------------------
    @classmethod
    def mixed_methods(cls) -> ExtractionTemplate:
        """Return a mixed-methods extraction form."""
        f = ExtractionField
        fields = [
            f("study_id", "Study ID", "text", required=True),
            f("title", "Title", "text", required=True),
            f("authors", "Authors", "text", required=True),
            f("year", "Year", "number", required=True),
            f("mm_design", "Mixed-methods design", "select", required=True,
              options=["convergent", "explanatory sequential",
                       "exploratory sequential", "embedded", "multiphase"]),
            f("rationale_for_mixing", "Rationale for mixing", "text", required=True),
            f("quant_design", "Quantitative design", "text"),
            f("quant_sample", "Quantitative sample size", "number"),
            f("quant_measures", "Quantitative measures", "text"),
            f("qual_design", "Qualitative design", "text"),
            f("qual_sample", "Qualitative sample size", "number"),
            f("qual_methods", "Qualitative methods", "text"),
            f("integration_point", "Point of integration", "select",
              options=["design", "methods", "interpretation", "reporting"]),
            f("joint_display", "Joint display used", "boolean"),
            f("key_findings_quant", "Key quantitative findings", "text"),
            f("key_findings_qual", "Key qualitative findings", "text"),
            f("integrated_findings", "Integrated findings", "text", required=True),
            f("legitimation", "Legitimation criteria addressed", "text"),
            f("mmat_quality", "MMAT quality rating", "select",
              options=["high", "medium", "low"]),
            f("extraction_notes", "Notes", "text"),
            f("extraction_date", "Extraction date", "date", required=True),
        ]
        return ExtractionTemplate(name="mixed_methods", fields=fields)

    # ------------------------------------------------------------------
    # Bibliometric
    # ------------------------------------------------------------------
    @classmethod
    def bibliometric(cls) -> ExtractionTemplate:
        """Return a bibliometric-extraction form."""
        f = ExtractionField
        fields = [
            f("title", "Title", "text", required=True),
            f("authors", "Authors", "text", required=True),
            f("year", "Year", "number", required=True),
            f("doi", "DOI", "text"),
            f("journal", "Journal", "text", required=True),
            f("issn", "ISSN", "text"),
            f("publisher", "Publisher", "text"),
            f("affiliations", "Affiliations", "text"),
            f("countries", "Countries", "text"),
            f("language", "Language", "text"),
            f("paper_type", "Document type", "select",
              options=["article", "review", "conference paper", "book chapter",
                       "editorial", "letter", "preprint"]),
            f("keywords", "Keywords", "text"),
            f("abstract", "Abstract", "text"),
            f("citations_count", "Citation count", "number"),
            f("references_count", "Number of references", "number"),
            f("methods", "Methods used", "text"),
            f("datasets", "Datasets used", "text"),
            f("funders", "Funders", "text"),
            f("open_access", "Open access", "boolean"),
            f("extraction_date", "Extraction date", "date", required=True),
        ]
        return ExtractionTemplate(name="bibliometric", fields=fields)

    # ------------------------------------------------------------------
    # Content analysis (media / textual)
    # ------------------------------------------------------------------
    @classmethod
    def content_analysis(cls) -> ExtractionTemplate:
        """Return a content-analysis extraction form."""
        f = ExtractionField
        fields = [
            f("source_id", "Source ID", "text", required=True),
            f("source_title", "Source title", "text", required=True),
            f("source_type", "Source type", "select", required=True,
              options=["newspaper", "TV segment", "radio", "social media post",
                       "press release", "blog", "video", "podcast", "other"]),
            f("source_url", "Source URL", "text"),
            f("publication_date", "Publication date", "date", required=True),
            f("author", "Author / byline", "text"),
            f("outlet", "Outlet / publisher", "text"),
            f("country", "Country", "text"),
            f("language", "Language", "text"),
            f("length_words", "Length (words)", "number"),
            f("topic", "Topic", "text", required=True),
            f("framing", "Framing", "select",
              options=["positive", "neutral", "negative", "mixed"]),
            f("primary_source", "Source attribution", "select",
              options=["official", "expert", "witness", "anecdotal",
                       "no source"]),
            f("key_actors", "Key actors mentioned", "text"),
            f("key_quotes", "Key quotes", "text"),
            f("coding_categories", "Coding categories", "multiselect",
              options=["economic", "political", "social", "technological",
                       "legal", "ethical", "environmental"]),
            f("tone_score", "Tone score (-1 to +1)", "rating"),
            f("extraction_notes", "Notes", "text"),
            f("extraction_date", "Extraction date", "date", required=True),
        ]
        return ExtractionTemplate(name="content_analysis", fields=fields)

    # ------------------------------------------------------------------
    # Survey research
    # ------------------------------------------------------------------
    @classmethod
    def survey_research(cls) -> ExtractionTemplate:
        """Return a survey-research extraction form (items + Likert + demographics)."""
        f = ExtractionField
        fields = [
            f("study_id", "Study ID", "text", required=True),
            f("title", "Title", "text", required=True),
            f("authors", "Authors", "text", required=True),
            f("year", "Year", "number", required=True),
            f("survey_mode", "Survey mode", "select", required=True,
              options=["online", "telephone", "face-to-face", "mail",
                       "mixed"]),
            f("population", "Target population", "text", required=True),
            f("sampling_frame", "Sampling frame", "text"),
            f("sampling_method", "Sampling method", "select", required=True,
              options=["simple random", "stratified", "cluster",
                       "quota", "convenience", "snowball"]),
            f("n_sampled", "N sampled", "number", required=True),
            f("n_responded", "N responded", "number"),
            f("response_rate", "Response rate (%)", "number"),
            f("weighting", "Weighting applied", "boolean"),
            f("demographics_age", "Mean age (years)", "number"),
            f("demographics_gender", "Gender distribution", "text"),
            f("demographics_education", "Education distribution", "text"),
            f("demographics_income", "Income distribution", "text"),
            f("instrument_name", "Instrument name", "text", required=True),
            f("instrument_validated", "Instrument validated", "boolean"),
            f("n_items", "Number of items", "number"),
            f("likert_points", "Likert scale points", "select",
              options=["3", "4", "5", "7", "9", "11", "0-100 VAS"]),
            f("reliability_alpha", "Cronbach's alpha", "number"),
            f("key_findings", "Key findings", "text", required=True),
            f("extraction_notes", "Notes", "text"),
            f("extraction_date", "Extraction date", "date", required=True),
        ]
        return ExtractionTemplate(name="survey_research", fields=fields)

    # ------------------------------------------------------------------
    # Library accessor API
    # ------------------------------------------------------------------
    @classmethod
    def available(cls) -> List[str]:
        """Return the names of every available template."""
        return [
            "cochrane_rct",
            "observational",
            "qualitative",
            "mixed_methods",
            "bibliometric",
            "content_analysis",
            "survey_research",
        ]

    @classmethod
    def get(cls, name: str) -> ExtractionTemplate:
        """Look up a template by name (case-insensitive)."""
        key = (name or "").strip().lower()
        mapping = {
            "cochrane_rct": cls.cochrane_rct,
            "observational": cls.observational,
            "qualitative": cls.qualitative,
            "mixed_methods": cls.mixed_methods,
            "bibliometric": cls.bibliometric,
            "content_analysis": cls.content_analysis,
            "survey_research": cls.survey_research,
        }
        if key not in mapping:
            raise KeyError(
                f"Unknown extraction template: {name!r}. "
                f"Available: {cls.available()}"
            )
        return mapping[key]()


# ---------------------------------------------------------------------------
# Extraction session
# ---------------------------------------------------------------------------
class ExtractionSession:
    """Interactive per-study extraction against an :class:`ExtractionTemplate`.

    A session tracks the values for a single study against a template,
    supports per-field validation, and can be serialised to / from
    YAML or JSON.
    """

    def __init__(
        self,
        template: ExtractionTemplate,
        study_id: Optional[str] = None,
    ) -> None:
        """Initialise the session.

        Args:
            template: The :class:`ExtractionTemplate` to extract against.
            study_id: Optional identifier for the study being extracted.
                If provided, the ``study_id`` template field (if any) is
                pre-populated with this value.
        """
        self.template = template
        self.study_id = study_id
        self._values: Dict[str, Any] = {}
        # Pre-populate defaults.
        for f in template.fields:
            if f.default_value is not None:
                self._values[f.name] = f.default_value
        if study_id and template.field("study_id"):
            self._values["study_id"] = study_id

    # ------------------------------------------------------------------
    # Field access
    # ------------------------------------------------------------------
    def set_field(self, name: str, value: Any) -> "ExtractionSession":
        """Set the value of field ``name``.

        Returns:
            The same session (for chaining).
        """
        fld = self.template.field(name)
        if fld is None:
            raise KeyError(f"Field {name!r} not in template {self.template.name!r}")
        self._values[name] = self._coerce(fld, value)
        return self

    def get_field(self, name: str) -> Any:
        """Return the current value for ``name`` (or ``None`` if unset)."""
        return self._values.get(name)

    def as_dict(self) -> Dict[str, Any]:
        """Return a flat dict of ``{field_name: value}``."""
        return dict(self._values)

    # Alias for API parity with the spec's `to_dict`.
    def to_dict(self) -> Dict[str, Any]:
        """Return the same dict as :meth:`as_dict`."""
        return self.as_dict()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    def validate(self) -> List[str]:
        """Return a list of validation error strings (empty = valid)."""
        errors: List[str] = []
        for fld in self.template.fields:
            val = self._values.get(fld.name, None)
            # Required check
            if fld.required and self._is_empty(val):
                errors.append(f"{fld.name}: required field is empty")
                continue
            if self._is_empty(val):
                continue  # optional + empty = skip type checks
            err = self._validate_value(fld, val)
            if err:
                errors.append(f"{fld.name}: {err}")
        return errors

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------
    def to_json(self, path: str) -> str:
        """Serialise the session to a JSON file (lazy ``json`` import)."""
        import json
        import os

        payload = {
            "template": self.template.name,
            "study_id": self.study_id,
            "values": self._values,
        }
        abs_path = os.path.abspath(path)
        with open(abs_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False, default=str)
        return abs_path

    def to_yaml(self, path: str) -> str:
        """Serialise the session to a YAML file (lazy ``yaml`` import)."""
        try:
            import yaml  # type: ignore[import]
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "PyYAML is required for ExtractionSession.to_yaml; "
                "install with: pip install PyYAML"
            ) from exc
        import os

        payload = {
            "template": self.template.name,
            "study_id": self.study_id,
            "values": self._values,
        }
        abs_path = os.path.abspath(path)
        with open(abs_path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(payload, fh, sort_keys=False, allow_unicode=True)
        return abs_path

    @classmethod
    def from_dict(
        cls,
        template: ExtractionTemplate,
        data: Dict[str, Any],
    ) -> "ExtractionSession":
        """Re-construct a session from a previously serialised dict.

        Args:
            template: The template to bind to.
            data: A ``{"study_id": ..., "values": {...}}`` mapping such
                as produced by :meth:`to_dict` / :meth:`to_json`.

        Returns:
            A populated :class:`ExtractionSession`.
        """
        sess = cls(template, study_id=data.get("study_id"))
        for k, v in (data.get("values") or {}).items():
            if template.field(k) is not None:
                sess._values[k] = v
        return sess

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    @staticmethod
    def _is_empty(v: Any) -> bool:
        if v is None:
            return True
        if isinstance(v, str):
            return v.strip() == ""
        if isinstance(v, (list, tuple, dict)):
            return len(v) == 0
        return False

    def _coerce(self, fld: ExtractionField, value: Any) -> Any:
        """Best-effort type coercion for ``value`` based on ``fld.type``."""
        t = fld.type
        if value is None:
            return None
        try:
            if t == "number":
                if isinstance(value, str) and not value.strip():
                    return None
                if isinstance(value, bool):
                    return int(value)
                f = float(value)
                return int(f) if f.is_integer() else f
            if t == "boolean":
                if isinstance(value, str):
                    return value.strip().lower() in ("1", "true", "yes", "y", "t")
                return bool(value)
            if t == "select":
                s = str(value).strip()
                if fld.options and s not in fld.options:
                    logger.warning(
                        "Value %r not in options %s for field %r — kept as-is.",
                        s, fld.options, fld.name,
                    )
                return s
            if t == "multiselect":
                if isinstance(value, str):
                    parts = [p.strip() for p in value.split(",") if p.strip()]
                else:
                    parts = list(value)
                if fld.options:
                    invalid = [p for p in parts if p not in fld.options]
                    if invalid:
                        logger.warning(
                            "Multiselect values %r not in options for %r.",
                            invalid, fld.name,
                        )
                return parts
            if t in ("rating", "likert"):
                if isinstance(value, str) and not value.strip():
                    return None
                return float(value)
            if t == "text":
                return str(value)
            if t == "date":
                return str(value)  # ISO format recommended; not parsed here.
            if t == "file":
                return str(value)
            if t == "reference":
                return str(value)
        except (TypeError, ValueError) as exc:
            logger.warning("Could not coerce %r to %s: %s", value, t, exc)
        return value

    def _validate_value(self, fld: ExtractionField, val: Any) -> Optional[str]:
        """Type-specific validation for a non-empty value."""
        t = fld.type
        if t == "number":
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                return f"expected number, got {type(val).__name__}"
            return None
        if t == "boolean":
            if not isinstance(val, bool):
                return f"expected boolean, got {type(val).__name__}"
            return None
        if t == "select":
            if fld.options and val not in fld.options:
                return f"value {val!r} not in {fld.options}"
            return None
        if t == "multiselect":
            if not isinstance(val, (list, tuple)):
                return "expected list/tuple"
            if fld.options:
                bad = [v for v in val if v not in fld.options]
                if bad:
                    return f"values {bad!r} not in {fld.options}"
            return None
        if t in ("rating", "likert"):
            try:
                fv = float(val)
            except (TypeError, ValueError):
                return f"expected numeric rating, got {type(val).__name__}"
            if not (0.0 <= fv or -1.0 <= fv <= 1.0):
                return f"rating {fv} outside expected range"
            return None
        return None


__all__ = [
    "ExtractionField",
    "ExtractionTemplate",
    "ExtractionTemplateLibrary",
    "ExtractionSession",
    "VALID_FIELD_TYPES",
]
