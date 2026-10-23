"""Quality / risk-of-bias tools for non-RCT designs.

The :mod:`systematic_review.risk_of_bias` module already provides the
Cochrane-family tools (RoB 2, ROBINS-I, QUADAS-2, Newcastle-Ottawa) for
*effect*-oriented study designs. This module complements it with
*reporting-and-methodology-quality* instruments for the broader set of
designs encountered in mixed-discipline reviews:

* :class:`MMAT` — Mixed Methods Appraisal Tool (Hong et al. 2018), 25
  items across 5 categories (qualitative, quantitative-randomised,
  quantitative-nonrandomised, quantitative-descriptive, mixed methods).
* :class:`STROBEChecklist` — 22 items for observational studies.
* :class:`CONSORTChecklist` — 25 items for RCTs.
* :class:`PRISMAComplianceChecklist` — 27 items.
* :class:`CAREChecklist` — 13 items for case reports.
* :class:`CAREPlusChecklist` — extended CARE.
* :class:`SRQRChecklist` — Standards for Reporting Qualitative Research
  (21 items).
* :class:`ENTREQChecklist` — Enhancing transparency in reporting the
  synthesis of qualitative research.
* :class:`CASPChecklist` — Critical Appraisal Skills Programme (RCT,
  cohort, case-control, qualitative, systematic-review variants).

All checklists share a common :class:`QualityAssessmentTool` ABC and
return a :class:`QualityResult` dataclass. ``study_data`` is a free-form
dict — each tool documents which keys it consults (typically boolean
``"item_1"`` ... ``"item_N"`` flags or a per-item ``"yes"/"no"/"unclear"``
string). Unknown keys are treated as ``"no"`` so the tools degrade
gracefully on partial input.
"""
#
# MIT License — Academic Research Suite
# Copyright (c) 2026 — see /LICENSE for full text.
#
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------
@dataclass
class QualityResult:
    """Outcome of a quality / RoB assessment.

    Attributes:
        tool_name: Name of the assessing tool.
        study_id: Optional identifier for the assessed study.
        items: Mapping of item-id -> response
            (``"yes" | "no" | "unclear" | "not_applicable"`` or bool).
        total_score: Numeric score in [0, 1] — fraction of "yes".
        quality_grade: ``"high" | "moderate" | "low" | "very low"``.
        notes: Free-form notes.
    """

    tool_name: str = ""
    study_id: Optional[str] = None
    items: Dict[str, str] = field(default_factory=dict)
    total_score: float = 0.0
    quality_grade: str = "very low"
    notes: str = ""

    def to_dict(self) -> Dict[str, object]:
        """Return a JSON-serialisable dict of this result."""
        return {
            "tool_name": self.tool_name,
            "study_id": self.study_id,
            "items": dict(self.items),
            "total_score": self.total_score,
            "quality_grade": self.quality_grade,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# ABC
# ---------------------------------------------------------------------------
class QualityAssessmentTool(ABC):
    """Abstract base class for all quality-assessment tools.

    Subclasses must:

    1. Declare ``NAME`` (class attribute).
    2. Declare ``ITEMS`` as a list of ``(item_id, description)`` tuples.
    3. Implement :meth:`assess` to populate a :class:`QualityResult`.
    """

    NAME: str = ""
    ITEMS: List[tuple] = []

    @abstractmethod
    def assess(self, study_data: Dict[str, object]) -> QualityResult:
        """Assess ``study_data`` and return a :class:`QualityResult`."""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Helpers shared by concrete checklists
    # ------------------------------------------------------------------
    @staticmethod
    def _normalise_response(value: object) -> str:
        """Normalise a raw item response to a canonical token."""
        if value is None:
            return "no"
        if isinstance(value, bool):
            return "yes" if value else "no"
        s = str(value).strip().lower()
        aliases = {
            "y": "yes", "yes": "yes", "true": "yes", "1": "yes", "pass": "yes",
            "n": "no", "no": "no", "false": "no", "0": "no", "fail": "no",
            "u": "unclear", "unclear": "unclear", "?": "unclear", "maybe": "unclear",
            "na": "not_applicable", "n/a": "not_applicable",
            "not_applicable": "not_applicable", "not applicable": "not_applicable",
        }
        return aliases.get(s, s)

    def _build_result(
        self,
        study_data: Dict[str, object],
        study_id: Optional[str] = None,
    ) -> QualityResult:
        """Populate a :class:`QualityResult` with per-item responses + score."""
        items: Dict[str, str] = {}
        n_yes = 0
        n_scoring = 0  # excludes "not_applicable"
        for item_id, _desc in self.ITEMS:
            raw = study_data.get(item_id, study_data.get(item_id.lower()))
            token = self._normalise_response(raw)
            items[item_id] = token
            if token != "not_applicable":
                n_scoring += 1
                if token == "yes":
                    n_yes += 1
        score = (n_yes / n_scoring) if n_scoring else 0.0
        if score >= 0.75:
            grade = "high"
        elif score >= 0.5:
            grade = "moderate"
        elif score >= 0.25:
            grade = "low"
        else:
            grade = "very low"
        return QualityResult(
            tool_name=self.NAME,
            study_id=study_id or str(study_data.get("study_id") or ""),
            items=items,
            total_score=round(score, 3),
            quality_grade=grade,
        )


# ---------------------------------------------------------------------------
# MMAT — Mixed Methods Appraisal Tool (Hong et al. 2018)
# ---------------------------------------------------------------------------
class MMAT(QualityAssessmentTool):
    """Mixed Methods Appraisal Tool (Hong et al., 2018).

    The MMAT contains 25 items across 5 categories:

    * **Qualitative** (5 items) — appropriateness of approach, design,
      data collection, analysis, interpretation.
    * **Quantitative randomized** (5 items) — randomisation, allocation
      concealment, baseline comparability, blinding, completeness.
    * **Quantitative nonrandomized** (5 items) — selection, measurement,
      comparability of groups, completeness, accounting for confounders.
    * **Quantitative descriptive** (5 items) — sampling strategy,
      representativeness, measurement appropriateness, response rate,
      data analysis.
    * **Mixed methods** (5 items) — design appropriateness, integration,
      limitations, coherence, data adequacy.

    Each item is scored ``yes``/``no``/``unclear``/``not_applicable``.
    Returns a categorical confidence (high/medium/low) on top of the
    numeric score.
    """

    NAME = "MMAT"
    ITEMS: List[tuple] = [
        # Category 1: Qualitative
        ("mmat_1_qual_approach", "Is the qualitative approach appropriate to answer the research question?"),
        ("mmat_2_qual_design", "Are the qualitative data collection methods adequate to address the research question?"),
        ("mmat_3_qual_data", "Are the findings adequately derived from the data?"),
        ("mmat_4_qual_analysis", "Is the analysis of qualitative data adequately rigorous?"),
        ("mmat_5_qual_interp", "Is there coherence between qualitative data sources, collection, analysis and interpretation?"),
        # Category 2: Quantitative randomized
        ("mmat_6_rand_random", "Is there a clear description of the randomization process?"),
        ("mmat_7_rand_concealment", "Was allocation adequately concealed?"),
        ("mmat_8_rand_baseline", "Were groups comparable at baseline?"),
        ("mmat_9_rand_blinding", "Were participants and personnel blinded?"),
        ("mmat_10_rand_complete", "Were incomplete outcome data adequately addressed?"),
        # Category 3: Quantitative nonrandomized
        ("mmat_11_nr_selection", "Were the participants representative of the target population?"),
        ("mmat_12_nr_measurement", "Were measurements appropriate for both exposure and outcome?"),
        ("mmat_13_nr_confounding", "Were confounders accounted for in the design and/or analysis?"),
        ("mmat_14_nr_complete", "Was complete follow-up achieved?"),
        ("mmat_15_nr_assessment", "Were outcome assessors blinded?"),
        # Category 4: Quantitative descriptive
        ("mmat_16_desc_sampling", "Was the sampling strategy appropriate?"),
        ("mmat_17_desc_representative", "Was the sample representative of the target population?"),
        ("mmat_18_desc_measurement", "Were measurements appropriate?"),
        ("mmat_19_desc_response", "Was the response rate adequate?"),
        ("mmat_20_desc_analysis", "Was the statistical analysis appropriate?"),
        # Category 5: Mixed methods
        ("mmat_21_mm_design", "Is there an adequate rationale for using a mixed methods design?"),
        ("mmat_22_mm_integration", "Are the different components effectively integrated?"),
        ("mmat_23_mm_limitations", "Are the limitations of each component adequately addressed?"),
        ("mmat_24_mm_coherence", "Is there coherence between the qualitative and quantitative components?"),
        ("mmat_25_mm_data", "Were data sources adequately triangulated?"),
    ]

    # Category prefix → index slice (used for per-category scoring).
    CATEGORIES = {
        "qualitative": slice(0, 5),
        "quantitative_randomized": slice(5, 10),
        "quantitative_nonrandomized": slice(10, 15),
        "quantitative_descriptive": slice(15, 20),
        "mixed_methods": slice(20, 25),
    }

    def assess(self, study_data: Dict[str, object]) -> QualityResult:
        """Assess ``study_data`` with the MMAT and return a :class:`QualityResult`.

        The result's ``notes`` field contains the per-category confidence
        breakdown (``high`` if all 5 items in a category are ``yes``;
        ``medium`` if ≥3; ``low`` otherwise).
        """
        result = self._build_result(study_data)
        # Per-category confidence.
        cat_scores: Dict[str, str] = {}
        for cat, sl in self.CATEGORIES.items():
            keys = [self.ITEMS[i][0] for i in range(*sl.indices(len(self.ITEMS)))]
            responses = [result.items.get(k, "no") for k in keys]
            n_yes = sum(1 for r in responses if r == "yes")
            if n_yes == 5:
                cat_scores[cat] = "high"
            elif n_yes >= 3:
                cat_scores[cat] = "medium"
            else:
                cat_scores[cat] = "low"
        overall = (
            "high" if all(v == "high" for v in cat_scores.values())
            else "medium" if any(v in ("high", "medium") for v in cat_scores.values())
            else "low"
        )
        result.notes = (
            f"Overall MMAT confidence: {overall}. "
            f"Per-category: {cat_scores}."
        )
        return result


# ---------------------------------------------------------------------------
# STROBE checklist (22 items)
# ---------------------------------------------------------------------------
class STROBEChecklist(QualityAssessmentTool):
    """STROBE checklist — 22 items for observational studies."""

    NAME = "STROBE"
    ITEMS: List[tuple] = [
        ("strobe_1_title_abstract", "Title and abstract indicate study design (cohort/case-control/cross-sectional)."),
        ("strobe_2_background", "Background / rationale provided."),
        ("strobe_3_objectives", "Objectives / hypotheses stated."),
        ("strobe_4_methods_design", "Study design stated."),
        ("strobe_5_methods_setting", "Setting described."),
        ("strobe_6_methods_participants", "Participants described."),
        ("strobe_7_methods_variables", "Variables defined."),
        ("strobe_8_methods_sources", "Data sources described."),
        ("strobe_9_methods_bias", "Bias addressed."),
        ("strobe_10_methods_study_size", "Study size justified."),
        ("strobe_11_methods_quantitative", "Quantitative variables described."),
        ("strobe_12_methods_statistics", "Statistical methods described."),
        ("strobe_13_results_participants", "Participant flow described."),
        ("strobe_14_results_descriptive", "Descriptive data reported."),
        ("strobe_15_results_outcome", "Outcome data reported."),
        ("strobe_16_results_main", "Main results reported."),
        ("strobe_17_results_other", "Other analyses reported."),
        ("strobe_18_discussion_key", "Key results summarised."),
        ("strobe_19_discussion_limitations", "Limitations discussed."),
        ("strobe_20_discussion_interpretation", "Interpretation cautious."),
        ("strobe_21_discussion_generalisability", "Generalisability discussed."),
        ("strobe_22_other", "Funding sources disclosed."),
    ]

    def assess(self, study_data: Dict[str, object]) -> QualityResult:
        return self._build_result(study_data)


# ---------------------------------------------------------------------------
# CONSORT checklist (25 items)
# ---------------------------------------------------------------------------
class CONSORTChecklist(QualityAssessmentTool):
    """CONSORT 2010 checklist — 25 items for RCTs."""

    NAME = "CONSORT"
    ITEMS: List[tuple] = [
        ("consort_1_title", "Title identifies as RCT."),
        ("consort_2_abstract", "Structured abstract (trial design, methods, results, conclusions)."),
        ("consort_3_background", "Background and rationale."),
        ("consort_4_objectives", "Specific objectives / hypotheses."),
        ("consort_5_trial_design", "Description of trial design."),
        ("consort_6_participants", "Eligibility criteria and settings."),
        ("consort_7_interventions", "Interventions described."),
        ("consort_8_outcomes", "Primary and secondary outcomes defined."),
        ("consort_9_sample_size", "Sample size calculation."),
        ("consort_10_randomisation_sequence", "Method of random sequence generation."),
        ("consort_11_randomisation_type", "Type of randomisation."),
        ("consort_12_allocation_concealment", "Allocation concealment mechanism."),
        ("consort_13_implementation", "Who generated, enrolled, assigned."),
        ("consort_14_blinding", "Blinding (participants, personnel, outcome assessors)."),
        ("consort_15_statistical_methods", "Statistical methods for primary/secondary outcomes."),
        ("consort_16_participant_flow", "Participant flow diagram."),
        ("consort_17_recruitment", "Recruitment dates and follow-up."),
        ("consort_18_baseline", "Baseline data."),
        ("consort_19_numbers_analysed", "Numbers analysed."),
        ("consort_20_outcomes_estimation", "Outcome estimation and effect size."),
        ("consort_21_auxiliary", "Ancillary analyses."),
        ("consort_22_harms", "Harms and adverse events."),
        ("consort_23_limitations", "Limitations."),
        ("consort_24_generalisability", "Generalisability."),
        ("consort_25_registration", "Registration number."),
    ]

    def assess(self, study_data: Dict[str, object]) -> QualityResult:
        return self._build_result(study_data)


# ---------------------------------------------------------------------------
# PRISMA compliance (27 items, PRISMA 2020)
# ---------------------------------------------------------------------------
class PRISMAComplianceChecklist(QualityAssessmentTool):
    """PRISMA 2020 compliance checklist — 27 items for systematic reviews."""

    NAME = "PRISMA"
    ITEMS: List[tuple] = [
        ("prisma_1_title", "Title identifies as systematic review."),
        ("prisma_2_abstract", "Structured abstract using PRISMA abstract checklist."),
        ("prisma_3_rationale", "Rationale for review in context of existing knowledge."),
        ("prisma_4_objectives", "Objectives using PICO."),
        ("prisma_5_eligibility", "Eligibility criteria."),
        ("prisma_6_information_sources", "Information sources including dates."),
        ("prisma_7_search_strategy", "Full search strategies for ≥1 database."),
        ("prisma_8_selection_process", "Selection process including number of reviewers."),
        ("prisma_9_data_collection", "Data collection process."),
        ("prisma_10_data_items", "Data items and assumptions."),
        ("prisma_11_bias_study", "Risk-of-bias methods per study design."),
        ("prisma_12_effect_measures", "Effect measures specified."),
        ("prisma_13_synthesis_preparation", "Synthesis preparation steps."),
        ("prisma_14_synthesis_methods", "Synthesis methods (meta-analysis or narrative)."),
        ("prisma_15_heterogeneity", "Heterogeneity assessment."),
        ("prisma_16_reporting_bias", "Reporting-bias assessment."),
        ("prisma_17_certainty", "Certainty assessment (GRADE)."),
        ("prisma_18_study_selection", "Study selection results with PRISMA flow diagram."),
        ("prisma_19_study_characteristics", "Study characteristics."),
        ("prisma_20_risk_bias_results", "Risk-of-bias results."),
        ("prisma_21_individual_results", "Individual study results."),
        ("prisma_22_synthesis_results", "Synthesis results."),
        ("prisma_23_reporting_bias_results", "Reporting-bias results."),
        ("prisma_24_certainty_results", "Certainty of evidence results."),
        ("prisma_25_discussion_interpretation", "Interpretation of results."),
        ("prisma_26_discussion_limitations", "Limitations of evidence and review."),
        ("prisma_27_other", "Registration, protocol access, funding, competing interests."),
    ]

    def assess(self, study_data: Dict[str, object]) -> QualityResult:
        return self._build_result(study_data)


# ---------------------------------------------------------------------------
# CARE checklist (13 items, base)
# ---------------------------------------------------------------------------
class CAREChecklist(QualityAssessmentTool):
    """CARE checklist — 13 items for case reports."""

    NAME = "CARE"
    ITEMS: List[tuple] = [
        ("care_1_title", "Title includes 'case report' and key words."),
        ("care_2_keywords", "Keywords represent the case."),
        ("care_3_abstract", "Structured abstract."),
        ("care_4_background", "Background with scientific context."),
        ("care_5_patient_info", "Patient demographic information."),
        ("care_6_history", "Medical and family history."),
        ("care_7_clinical_findings", "Clinical findings described."),
        ("care_8_timeline", "Timeline of the case."),
        ("care_9_diagnostic_tests", "Diagnostic tests and results."),
        ("care_10_interventions", "Interventions and outcomes."),
        ("care_11_follow_up", "Follow-up and outcomes."),
        ("care_12_discussion", "Discussion of strengths/limitations."),
        ("care_13_perspective", "Patient perspective included."),
    ]

    def assess(self, study_data: Dict[str, object]) -> QualityResult:
        return self._build_result(study_data)


# ---------------------------------------------------------------------------
# CARE+ checklist (extended CARE)
# ---------------------------------------------------------------------------
class CAREPlusChecklist(QualityAssessmentTool):
    """CARE+ — extended CARE checklist (18 items).

    Adds five items over the base CARE: informed consent statement,
    ethics approval, data sharing statement, contribution statement,
    funding disclosure.
    """

    NAME = "CARE+"
    ITEMS: List[tuple] = CAREChecklist.ITEMS + [
        ("care_plus_14_consent", "Informed consent obtained and stated."),
        ("care_plus_15_ethics", "Ethics approval documented."),
        ("care_plus_16_data_sharing", "Data sharing statement."),
        ("care_plus_17_contributions", "Author contributions statement."),
        ("care_plus_18_funding", "Funding and competing interests disclosed."),
    ]

    def assess(self, study_data: Dict[str, object]) -> QualityResult:
        return self._build_result(study_data)


# ---------------------------------------------------------------------------
# SRQR — Standards for Reporting Qualitative Research (21 items)
# ---------------------------------------------------------------------------
class SRQRChecklist(QualityAssessmentTool):
    """SRQR — 21 items for qualitative research reporting."""

    NAME = "SRQR"
    ITEMS: List[tuple] = [
        ("srqr_1_title", "Title conveys qualitative nature."),
        ("srqr_2_abstract", "Abstract summarises problem, methods, findings."),
        ("srqr_3_problem", "Problem formulation and significance."),
        ("srqr_4_purpose", "Purpose or research question."),
        ("srqr_5_qualitative_approach", "Qualitative approach and paradigm."),
        ("srqr_6_researcher", "Researcher characteristics and assumptions."),
        ("srqr_7_context", "Context / setting described."),
        ("srqr_8_sampling", "Sampling strategy."),
        ("srqr_9_ethical_issues", "Ethical issues addressed."),
        ("srqr_10_data_collection", "Data collection methods."),
        ("srqr_11_units", "Units of study described."),
        ("srqr_12_data_processing", "Data processing described."),
        ("srqr_13_data_analysis", "Data analysis described."),
        ("srqr_14_techniques", "Techniques to enhance trustworthiness."),
        ("srqr_15_synthesis", "Synthesis and interpretation."),
        ("srqr_16_findings", "Findings reported with quotes."),
        ("srqr_17_links", "Links to empirical data and theory."),
        ("srqr_18_integration", "Integration with prior work."),
        ("srqr_19_limitations", "Limitations stated."),
        ("srqr_20_implications", "Implications and significance."),
        ("srqr_21_funding", "Funding and conflicts disclosed."),
    ]

    def assess(self, study_data: Dict[str, object]) -> QualityResult:
        return self._build_result(study_data)


# ---------------------------------------------------------------------------
# ENTREQ — synthesis of qualitative research (21 items)
# ---------------------------------------------------------------------------
class ENTREQChecklist(QualityAssessmentTool):
    """ENTREQ — Enhancing transparency in reporting the synthesis of
    qualitative research (21 items)."""

    NAME = "ENTREQ"
    ITEMS: List[tuple] = [
        ("entreq_1_aim", "Aim and research question stated."),
        ("entreq_2_synthesis_method", "Synthesis method identified."),
        ("entreq_3_approach", "Approach to synthesis described."),
        ("entreq_4_search_strategy", "Search strategy described."),
        ("entreq_5_inclusion", "Inclusion criteria."),
        ("entreq_6_data_sources", "Data sources detailed."),
        ("entreq_7_search_outcomes", "Search outcomes documented."),
        ("entreq_8_screening", "Screening process."),
        ("entreq_9_appraisal", "Quality appraisal methods."),
        ("entreq_10_data_extraction", "Data extraction methods."),
        ("entreq_11_modifications", "Modifications to data extraction."),
        ("entreq_12_coding", "Coding process described."),
        ("entreq_13_analysis", "Analysis process described."),
        ("entreq_14_categories", "Descriptive / analytical categories."),
        ("entreq_15_synthesis_output", "Synthesis output described."),
        ("entreq_16_quotes", "Quotes/illustrations provided."),
        ("entreq_17_findings", "Findings presented."),
        ("entreq_18_limitations", "Limitations of synthesis."),
        ("entreq_19_credibility", "Credibility of synthesis."),
        ("entreq_20_integration", "Integration with prior work."),
        ("entreq_21_funding", "Funding and conflicts disclosed."),
    ]

    def assess(self, study_data: Dict[str, object]) -> QualityResult:
        return self._build_result(study_data)


# ---------------------------------------------------------------------------
# CASP — Critical Appraisal Skills Programme (multiple variants)
# ---------------------------------------------------------------------------
class CASPChecklist(QualityAssessmentTool):
    """Critical Appraisal Skills Programme (CASP) checklists.

    CASP ships variants for different study designs; pass the variant
    name to the constructor:

    * ``"rct"`` (11 items) — randomised controlled trial.
    * ``"cohort"`` (12 items) — cohort study.
    * * ``"case_control"`` (11 items) — case-control study.
    * ``"qualitative"`` (10 items) — qualitative research.
    * ``"systematic_review"`` (10 items) — systematic review.

    The ``assess`` method scores only the items that are part of the
    selected variant.
    """

    NAME = "CASP"

    VARIANTS: Dict[str, List[tuple]] = {
        "rct": [
            ("casp_rct_1_question", "Did the trial address a clearly focused question?"),
            ("casp_rct_2_randomisation", "Was assignment to treatment randomised?"),
            ("casp_rct_3_concealment", "Was allocation concealed?"),
            ("casp_rct_4_baseline", "Were groups similar at baseline?"),
            ("casp_rct_5_blinding", "Were participants / personnel blinded?"),
            ("casp_rct_6_blinding_outcome", "Were outcome assessors blinded?"),
            ("casp_rct_7_dropout", "Was dropout rate acceptable?"),
            ("casp_rct_8_it", "Was intention-to-treat analysis used?"),
            ("casp_rct_9_effect", "Were effect sizes and CI reported?"),
            ("casp_rct_10_precision", "Was the estimate precise?"),
            ("casp_rct_11_applicable", "Are results applicable to your population?"),
        ],
        "cohort": [
            ("casp_cohort_1_question", "Did the study address a clearly focused question?"),
            ("casp_cohort_2_recruit", "Was the cohort recruited acceptably?"),
            ("casp_cohort_3_exposure", "Was exposure accurately measured?"),
            ("casp_cohort_4_outcome", "Was outcome accurately measured?"),
            ("casp_cohort_5_confounding", "Were confounders identified?"),
            ("casp_cohort_6_followup", "Was follow-up complete and long enough?"),
            ("casp_cohort_7_results", "Are the results clear?"),
            ("casp_cohort_8_precision", "How precise are the results?"),
            ("casp_cohort_9_credible", "Do you believe the results?"),
            ("casp_cohort_10_applicable", "Are results applicable to local population?"),
            ("casp_cohort_11_intervention", "Do results fit with other evidence?"),
            ("casp_cohort_12_implications", "What are the implications?"),
        ],
        "case_control": [
            ("casp_cc_1_question", "Did the study address a clearly focused question?"),
            ("casp_cc_2_cases", "Were cases recruited acceptably?"),
            ("casp_cc_3_controls", "Were controls selected appropriately?"),
            ("casp_cc_4_exposure", "Was exposure accurately measured?"),
            ("casp_cc_5_confounding", "Were confounders identified?"),
            ("casp_cc_6_same", "Were cases and controls measured identically?"),
            ("casp_cc_7_response", "Was response rate adequate?"),
            ("casp_cc_8_results", "Are results clear?"),
            ("casp_cc_9_precision", "How precise are the results?"),
            ("casp_cc_10_credible", "Do you believe the results?"),
            ("casp_cc_11_applicable", "Are results applicable?"),
        ],
        "qualitative": [
            ("casp_qual_1_aim", "Was there a clear statement of the aims?"),
            ("casp_qual_2_qual", "Is qualitative methodology appropriate?"),
            ("casp_qual_3_design", "Was the research design appropriate?"),
            ("casp_qual_4_recruit", "Was recruitment strategy appropriate?"),
            ("casp_qual_5_data", "Was data collection appropriate?"),
            ("casp_qual_6_reflexivity", "Has researcher-participant relationship been considered?"),
            ("casp_qual_7_ethics", "Were ethical issues considered?"),
            ("casp_qual_8_rigour", "Was data analysis sufficiently rigorous?"),
            ("casp_qual_9_findings", "Is there a clear statement of findings?"),
            ("casp_qual_10_value", "Is the research valuable?"),
        ],
        "systematic_review": [
            ("casp_sr_1_question", "Did the review address a clearly focused question?"),
            ("casp_sr_2_search", "Did the authors look for the right type of papers?"),
            ("casp_sr_3_quality", "Did the authors assess study quality?"),
            ("casp_sr_4_inclusion", "Were inclusion criteria appropriate?"),
            ("casp_sr_5_combine", "Was it reasonable to combine the studies?"),
            ("casp_sr_6_results", "What are the overall results?"),
            ("casp_sr_7_precision", "How precise are the results?"),
            ("casp_sr_8_applicable", "Can results be applied to local population?"),
            ("casp_sr_9_all", "Were all important outcomes considered?"),
            ("casp_sr_10_value", "Are the benefits worth the harms/costs?"),
        ],
    }

    def __init__(self, variant: str = "rct") -> None:
        """Initialise CASP for a given variant.

        Args:
            variant: One of ``"rct"``, ``"cohort"``, ``"case_control"``,
                ``"qualitative"``, ``"systematic_review"``.
        """
        key = variant.strip().lower()
        if key not in self.VARIANTS:
            raise ValueError(
                f"Unknown CASP variant: {variant!r}. "
                f"Available: {list(self.VARIANTS)}"
            )
        self.variant = key
        self.ITEMS = list(self.VARIANTS[key])
        self.NAME = f"CASP ({variant})"

    def assess(self, study_data: Dict[str, object]) -> QualityResult:
        return self._build_result(study_data)


__all__ = [
    "QualityResult",
    "QualityAssessmentTool",
    "MMAT",
    "STROBEChecklist",
    "CONSORTChecklist",
    "PRISMAComplianceChecklist",
    "CAREChecklist",
    "CAREPlusChecklist",
    "SRQRChecklist",
    "ENTREQChecklist",
    "CASPChecklist",
]
