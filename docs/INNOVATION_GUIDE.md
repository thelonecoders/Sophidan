# Innovation Module Guide

> **Audience:** researchers, research-group leaders, R&D strategists,
> bibliometricians.
> **Companion docs:** [META_ANALYSIS_GUIDE.md](META_ANALYSIS_GUIDE.md)
> for downstream evidence synthesis,
> [Q1_FIGURES_GUIDE.md](Q1_FIGURES_GUIDE.md) for rendering
> publication-grade visualisations of innovation outputs.

This guide describes how Academic Research Suite (ARS) v2.0.0's
`innovation/` package helps you **discover what's next** in a research
field — citation bursts, knowledge frontiers, trend forecasts, paper
recommendations, collaborator recommendations, novelty scoring, and
research-direction recommendations.

---

## Table of Contents

1. [Citation burst detection](#citation-burst-detection)
2. [Knowledge frontier mapping](#knowledge-frontier-mapping)
3. [Trend forecasting](#trend-forecasting)
4. [Paper recommendation](#paper-recommendation)
5. [Collaboration recommendation](#collaboration-recommendation)
6. [Novelty scoring](#novelty-scoring)
7. [Research direction recommendations](#research-direction-recommendations)
8. [Example: Identifying the next big research topic](#example-identifying-the-next-big-research-topic)

---

## Citation burst detection

**Kleinberg's burst-detection algorithm** (Kleinberg J. *Bursty and
hierarchical structure in streams.* Data Min Knowl Discov 2003;7:373–397)
finds intervals of time during which an entity (paper, author, keyword,
journal, topic) receives citations at a rate significantly higher than
its baseline. The algorithm models citation arrivals as a two-state
hidden Markov model (low-rate baseline state q₀ vs high-rate burst
state q₁) and uses an automaton-based Viterbi-style decoder to find the
most likely state sequence. The transition cost between states is
controlled by `gamma`, and the burst-rate scaling by `s`.

ARS implements Kleinberg's algorithm in
`innovation.citation_bursts.CitationBurstDetector`. The detector
operates on five entity types via separate methods:

| Method | Detects | Input field |
|---|---|---|
| `detect_papers(papers, time_window=1, threshold=2.0)` | Bursting individual papers | `paper.citations_count`, `paper.year` |
| `detect_authors(papers, ...)` | Bursting authors | `paper.authors[]`, aggregated |
| `detect_keywords(papers, field='keywords', ...)` | Bursting keywords | `paper.keywords[]` (or `title`/`abstract`) |
| `detect_journals(papers, ...)` | Bursting journals | `paper.journal` |
| `detect_topics(papers, topic_model, ...)` | Bursting topics | pre-fitted topic model |

```python
from innovation.citation_bursts import CitationBurstDetector

detector = CitationBurstDetector(s=2.0, gamma=1.0)
bursts = detector.detect_papers(papers, time_window=1, threshold=2.0)
for b in bursts[:5]:
    print(f"{b.entity_name}: burst {b.start_year}–{b.end_year} "
          f"(peak {b.peak_year}, strength {b.strength:.2f}, "
          f"duration {b.duration}y)")

# Author-level bursts:
author_bursts = detector.detect_authors(papers, time_window=1, threshold=2.0)

# Keyword bursts (use 'title' or 'abstract' if keywords are missing):
keyword_bursts = detector.detect_keywords(papers, field="keywords",
                                          time_window=1, threshold=2.0)

# Aggregate to a DataFrame for export:
df = detector.to_dataframe(bursts)
df.to_csv("outputs/bursts.csv", index=False)

# Or visualise as a Gantt-style timeline:
fig = detector.visualize(bursts, figsize=(12, 8))
```

Each `Burst` dataclass carries: `entity_id`, `entity_name`,
`entity_type` (`"paper"` / `"author"` / `"keyword"` / `"journal"` /
`"topic"`), `start_year`, `end_year`, `peak_year`, `strength` (peak
burst-state level), `duration`, and `total_burst_score` (summed over
the burst interval — useful for ranking bursts of different lengths).

### Interpretation

- **Strength > 5** — strong, sustained burst.
- **Duration > 3 years** — a long-lived shift in attention, not a spike.
- **Peak_year ≥ current_year − 2** — an active, emerging burst worth
  investigating now.

---

## Knowledge frontier mapping

A **knowledge frontier** is a region of the research-embedding space
that is sparse (few papers) but rapidly growing (high citation velocity
or publication-rate acceleration). ARS implements three complementary
detection approaches in `innovation.frontier_mapping.KnowledgeFrontier`:

| Approach | Method | Idea |
|---|---|---|
| Embedding density | `embedding_density_approach(n_clusters=8, boundary_quantile=0.1, min_papers=2)` | Cluster papers in embedding space; identify sparse boundary regions between dense clusters. |
| Topic-model boundary | `topic_model_boundary_approach(n_topics=12, min_prevalence=0.02, max_prevalence=0.15, lookback_years=3, method='nmf')` | Fit a topic model; find topics with low prevalence but high growth. |
| Citation velocity | `citation_velocity_approach(recent_years=3, min_papers_per_year=3, top_n=10)` | Compute the 2nd derivative of citation counts per paper; high 2nd-derivative ⇒ frontier. |

The convenience method `compute_frontier(method='embedding_density',
top_n=10, **kwargs)` dispatches to any of the three.

```python
from innovation.frontier_mapping import KnowledgeFrontier, FrontierTracker

# Build a corpus of 500+ papers (from scraping or local DB):
kf = KnowledgeFrontier(papers)
frontiers = kf.compute_frontier(method="embedding_density", top_n=10)
for fr in frontiers:
    print(f"{fr.id}: novelty={fr.novelty_score:.2f}, "
          f"growth={fr.growth_rate:.0%}, "
          f"keywords={fr.keywords[:5]}")

# Visualise the frontier regions in 2D (t-SNE / UMAP):
fig = kf.visualize(method="tsne", figsize=(12, 10), regions=frontiers)

# Or pick a specific approach with custom params:
fr_emb = kf.embedding_density_approach(n_clusters=8, boundary_quantile=0.1)
fr_top = kf.topic_model_boundary_approach(
    n_topics=12, min_prevalence=0.02, max_prevalence=0.15,
    lookback_years=3, method="nmf",
)
fr_vel = kf.citation_velocity_approach(
    recent_years=3, min_papers_per_year=3, top_n=10,
)
```

Each `FrontierRegion` carries: `id`, `centroid_embedding` (the
embedding-space centroid), `representative_papers` (≤5 exemplar
papers), `novelty_score` ∈ [0, 1] (1 = very novel), `growth_rate`
(annual fractional growth), `neighbor_topics` (indices of nearby
dense topics), and `keywords` (top terms).

### Tracking frontiers over time

`FrontierTracker` takes a `papers_per_year: Dict[int, List[Paper]]`
mapping and produces a longitudinal view of how frontiers emerge,
grow, and fade:

```python
from innovation.frontier_mapping import FrontierTracker

tracker = FrontierTracker(papers_per_year={
    2018: papers_2018, 2019: papers_2019, 2020: papers_2020,
    2021: papers_2021, 2022: papers_2022,
})
emerging = tracker.emerging_topics(year=2022, lookback=3)
fading = tracker.fading_topics(year=2022, lookback=3)
df = tracker.track_over_time()    # returns a tidy DataFrame
```

---

## Trend forecasting

`innovation.trend_forecasting.TrendForecaster` projects future
publication counts, citation growth, and keyword prevalence using one
of four models:

| Model | Method arg | Library | Best for |
|---|---|---|---|
| ARIMA | `"arima"` (default) | `statsmodels.tsa.arima.model.ARIMA` | Short-term (1–3 yr) forecasts of stationary series |
| Prophet | `"prophet"` | `prophet` (optional, lazy import) | Long-term (3–5 yr) forecasts with seasonality |
| Linear | `"linear"` | `numpy.polyfit` | Linear growth / decline |
| Exponential | `"exponential"` | `scipy.optimize.curve_fit` | Doubling-time scenarios |

```python
from innovation.trend_forecasting import TrendForecaster

forecaster = TrendForecaster(papers)

# Forecast a whole field (5 years ahead, ARIMA):
field_fc = forecaster.forecast_field("machine learning",
                                      years_ahead=5, method="arima")
print(f"Predicted papers in 2028: {field_fc.values[-1]:.0f}")
fig = forecaster.visualize(field_fc, figsize=(10, 6))

# Per-topic forecast (top-10 topics):
topic_fcs = forecaster.forecast_all_topics(years_ahead=3, top_n=10,
                                            method="arima")
batch_fig = forecaster.batch_forecast_visualization(topic_fcs, cols=2)

# Author productivity forecast:
author_fc = forecaster.forecast_author_productivity(
    "0000-0001-2345-6789", years_ahead=3, method="arima",
)

# Emerging / fading keywords:
emerging_kw = forecaster.emerging_keywords(years_ahead=2, top_n=20)
fading_kw = forecaster.fading_keywords(years_ahead=2, top_n=20)
```

When `prophet` is not installed, the forecaster falls back to ARIMA
automatically (lazy import). Each `Forecast` dataclass carries
`historical_values`, `forecast_values`, `ci_lower`, `ci_upper`,
`model_name`, `method`, and `metric` (the name of what was forecast).

---

## Paper recommendation

`innovation.paper_recommendation.PaperRecommender` provides six
recommendation modes over a corpus, all built on top of paper embeddings
(default: `data_science.embeddings.EmbeddingsModel`):

| Method | Use case |
|---|---|
| `recommend_similar(paper, top_k=10)` | "Papers like this one" |
| `recommend_for_query(query_str, top_k=10)` | Semantic search by free-text query |
| `recommend_for_topic(topic, top_k=10)` | Top-k papers in a topic cluster |
| `recommend_for_user(user_history, top_k=10)` | Personalised: based on user's read papers |
| `recommend_bridge_papers(paper_a, paper_b, top_k=5)` | Papers connecting two otherwise-distant papers |
| `recommend_trending(top_k=20, days=30)` | Most-cited in the last 30 days |

```python
from innovation.paper_recommendation import PaperRecommender

rec = PaperRecommender(papers)        # builds the embedding index lazily
rec.index_papers()                    # or build eagerly

# Find papers similar to one you liked:
results = rec.recommend_similar(seed_paper, top_k=10)
for paper, score in results:
    print(f"  {score:.3f}  {paper.title}")

# Semantic search:
results = rec.recommend_for_query("graph neural networks for drug discovery",
                                  top_k=10)

# Diversify (Maximal Marginal Relevance, carbonell-goldstein 1998):
diverse = rec.diversify(results, lambda_param=0.5)

# Bridge papers (intersection of two literatures):
bridges = rec.recommend_bridge_papers(paper_a, paper_b, top_k=5)

# Why this recommendation? Explanability:
explanation = rec.explain(query_paper, recommended_paper)
print(explanation)
# "Recommended because both papers share 5 key terms (graph, neural, ...)
#  and have Jaccard=0.34 keyword overlap; cosine embedding similarity=0.78."

# Evaluate retrieval quality (offline):
ndcg = rec.evaluate(test_set=[(query, relevant_paper), ...],
                    metric="ndcg", k=10)
```

The recommender uses **faiss-cpu** for fast cosine similarity when
installed (lazy import), falling back to NumPy's matmul-based cosine
otherwise. The MMR diversification (carbonell & goldstein 1998) trades
off relevance against redundancy — `lambda_param=0.5` is the standard
default; lower values diversify more aggressively.

---

## Collaboration recommendation

`innovation.collaboration_recommendation.CollaborationRecommender`
suggests future co-authors by combining **complementary expertise**
(author A knows things author B doesn't) with **weak-ties scoring**
(author A and author B don't already have a strong direct connection).

```python
from innovation.collaboration_recommendation import CollaborationRecommender

rec = CollaborationRecommender(papers)

# Recommend top-10 collaborators for an author:
collabs = rec.recommend_collaborators("Alice Smith", top_k=10,
                                       exclude_existing=True)
for author, score in collabs:
    print(f"  {score:.3f}  {author}")

# Pairwise collaboration strength (existing or hypothetical):
strength = rec.compute_strength("Alice Smith", "Bob Jones")

# Bridge authors between two fields:
bridges = rec.bridge_authors("machine_learning", "biomedicine", top_k=5)

# Emerging collaborations (recent years only):
emerging = rec.emerging_collaborations(year_threshold=2020, top_k=20)

# Institution recommendations (where to send a postdoc):
institutions = rec.recommend_institutions("Alice Smith", top_k=5)

# Visualise the collaboration sub-network:
fig = rec.visualize_collaboration_network(author="Alice Smith",
                                          top_n=50, figsize=(12, 10))
```

The complementary-expertise score uses the Jaccard distance between
two authors' topic distributions (1 − Jaccard). The weak-ties score
penalises existing co-authors and rewards second-degree connections.
The final ranking is the product of the two.

---

## Novelty scoring

`innovation.novelty_scoring.NoveltyScorer` implements two of the most
widely-cited novelty indices:

| Index | Method | Reference | Range |
|---|---|---|---|
| Atypicality | `atypicality_score(paper, all_papers=None)` | Uzzi B et al. *Atypical combinations and scientific impact.* Science 2013;342:467–472 | z-score mapped to [0, 1] |
| Disruption index (CD index) | `disruption_index(paper, citing_papers)` | Funk RJ, Owen-Smith J. *A dynamic network measure of technological change.* Manage Sci 2017;63:791–817 | [−1, +1] (positive = disruptive) |

```python
from innovation.novelty_scoring import NoveltyScorer

scorer = NoveltyScorer(papers)

# Score a single paper:
score = scorer.score_paper(focal_paper)
print(f"Novelty = {score.novelty_score:.3f}")
print(f"Atypicality (Uzzi) = {score.atypicality_score:.3f}")
print(f"Disruption index (Funk-Owen-Smith) = {score.disruption_index:+.3f}")
print(f"Percentile = {score.percentile:.1f}")
print(f"Closest neighbours:")
for nbr, sim in score.closest_neighbors[:5]:
    print(f"  {sim:.3f}  {nbr.title}")

# Atypicality in isolation:
atyp = scorer.atypicality_score(focal_paper)

# Disruption index in isolation:
di = scorer.disruption_index(focal_paper, citing_papers)

# Rank the most-novel / most-disruptive papers:
novel_papers = scorer.rank_novel_papers(top_n=100)
disruptive = scorer.rank_disruptive_papers(top_n=100)

# Score a topic (aggregate over the topic's papers):
topic_score = scorer.score_topic("graph_neural_networks")

# Visualise the distribution and a radar plot of one paper:
fig1 = scorer.visualize_distribution(figsize=(10, 6))
fig2 = scorer.visualize_paper(paper_id="10.1234/xxx", figsize=(8, 8))
```

The `NoveltyScore` dataclass carries `paper_id`, `paper_title`,
`novelty_score` (overall, [0, 1]), `atypicality_score` (Uzzi z-score
mapped to [0, 1]), `disruption_index` (CD index in [−1, +1]),
`related_papers`, `closest_neighbors`, and `percentile` (novelty
percentile in [0, 100]).

### When to use which

- **Atypicality** measures whether a paper's reference combination is
  unusual (high pairwise journal-route distances). Best for *ex-ante*
  novelty prediction.
- **Disruption index** measures whether a paper's citing papers cite
  the focal paper's references less than expected (i.e. the focal
  paper disrupts the citation flow). Best for *ex-post* impact
  assessment, ≥ 5 years post-publication.

---

## Research direction recommendations

`innovation.research_directions.ResearchDirectionRecommender` is the
"top of the funnel" — it combines gaps (from a gap-analysis), frontiers
(from `KnowledgeFrontier`), and trends (from `TrendForecaster`) into
concrete, ranked research-direction suggestions.

```python
from innovation.research_directions import ResearchDirectionRecommender
from innovation.frontier_mapping import KnowledgeFrontier
from innovation.trend_forecasting import TrendForecaster

recommender = ResearchDirectionRecommender(papers, llm_client=None)

# Generate directions from a single signal:
dirs_from_gaps     = recommender.from_gaps(gap_list)
dirs_from_frontiers = recommender.from_frontier(frontier_list)
dirs_from_trends    = recommender.from_trends(trend_list)

# Or combine all three signals (recommended):
combined = recommender.combine_signals(
    gaps=gap_list,
    frontiers=frontier_list,
    trends=trend_list,
    top_n=10,
)

# Or by topic:
directions = recommender.recommend_directions(
    topic="graph neural networks for drug discovery", count=5,
)

for d in directions:
    print(f"# {d.title}")
    print(f"  Novelty: {d.novelty_score:.2f}  "
          f"Feasibility: {d.feasibility_score:.2f}")
    print(f"  Motivation: {d.motivation}")
    print(f"  Suggested collaborators: {d.suggested_collaborators}")
    print(f"  Estimated duration: {d.estimated_duration_months} months")

# Custom-weighted scoring:
scored = recommender.score(
    directions[0],
    criteria={"novelty": 0.6, "feasibility": 0.3, "impact": 0.1},
)

# Visualise the research roadmap (Gantt-style timeline):
fig = recommender.visualize_roadmap(directions, figsize=(14, 8))
```

Each `ResearchDirection` carries: `title`, `description`, `motivation`,
`expected_impact`, `novelty_score` ([0, 1]), `feasibility_score`
([0, 1]), `supporting_papers`, `keywords`, `estimated_duration_months`,
and `suggested_collaborators`.

When an `llm_client` (any object with a `complete(prompt) -> str` or
`chat(messages) -> str` API) is supplied, the recommender uses it to
draft the description / motivation / impact text. When `None`
(default), it uses deterministic template-based generation — useful for
reproducible pipelines.

---

## Example: Identifying the next big research topic

Putting it all together — a complete workflow to find the next hot
research topic in a field:

```python
from data_acquisition.scraping_engine import ScrapingEngine
from innovation.citation_bursts import CitationBurstDetector
from innovation.frontier_mapping import KnowledgeFrontier
from innovation.trend_forecasting import TrendForecaster
from innovation.novelty_scoring import NoveltyScorer
from innovation.research_directions import ResearchDirectionRecommender

# 1. Scrape the last 10 years of papers in the field.
engine = ScrapingEngine()
papers = engine.search_all("graph neural network drug discovery",
                           sources=["arxiv", "pubmed", "openalex"],
                           year_from=2014)

# 2. Detect citation bursts (papers / authors / keywords).
detector = CitationBurstDetector(s=2.0, gamma=1.0)
paper_bursts   = detector.detect_papers(papers)
author_bursts  = detector.detect_authors(papers)
keyword_bursts = detector.detect_keywords(papers, field="keywords")

# 3. Map knowledge frontiers (3 approaches, take the union).
kf = KnowledgeFrontier(papers)
frontiers = (kf.embedding_density_approach(n_clusters=8) +
             kf.topic_model_boundary_approach(n_topics=12) +
             kf.citation_velocity_approach(recent_years=3))

# 4. Forecast trends (next 5 years).
forecaster = TrendForecaster(papers)
field_forecast = forecaster.forecast_field("drug_discovery",
                                            years_ahead=5, method="arima")
emerging_kw = forecaster.emerging_keywords(years_ahead=2, top_n=20)

# 5. Score each paper's novelty; pick the top-5 most disruptive.
scorer = NoveltyScorer(papers)
disruptive = scorer.rank_disruptive_papers(top_n=5)

# 6. Combine into ranked research directions.
recommender = ResearchDirectionRecommender(papers, llm_client=None)
directions = recommender.combine_signals(
    gaps=disruptive,            # use disruptive papers as "gap" proxies
    frontiers=frontiers,
    trends=[field_forecast],
    top_n=10,
)
for d in directions[:5]:
    print(f"  • {d.title}  (novelty={d.novelty_score:.2f}, "
          f"feasibility={d.feasibility_score:.2f})")

# 7. Visualise the research roadmap.
fig = recommender.visualize_roadmap(directions, figsize=(14, 8))
fig.savefig("outputs/research_roadmap.svg", dpi=300)
```

This produces: (a) a list of citation bursts (papers, authors, keywords
suddenly receiving disproportionate attention), (b) a set of knowledge
frontier regions (sparse but fast-growing pockets of the embedding
space), (c) a 5-year forecast of the field's publication volume and
emerging keywords, (d) a top-5 list of the most disruptive papers, and
(e) a ranked list of 10 concrete research directions with novelty /
feasibility scores and suggested collaborators — plus a visual roadmap.

This is the canonical ARS "what's next" pipeline — use it at the start
of a new grant cycle, when starting a PhD, or when planning a research
group's 3-year strategy.

---

*For the underlying bibliometric analyses that feed these innovation
pipelines (h-index, e-index, journal impact factor, VOSviewer-style
co-citation clusters), see [MODULE_REFERENCE.md](MODULE_REFERENCE.md).
For rendering the visualisations as publication-grade figures, see
[Q1_FIGURES_GUIDE.md](Q1_FIGURES_GUIDE.md).*
