# Compliance and licensing notes

Maintainer notes, not legal advice. Items marked VERIFY were not confirmed
against the upstream sources when this file was written.

## 1. Qt bindings
- `requirements.txt` lists `PyQt5` (distributed by Riverbank under GPLv3 or a
  commercial licence - VERIFY). Distributing a closed-source build that links
  PyQt5 requires a commercial licence.
- The code imports Qt through `qtpy`, which can target PySide6 (LGPL - VERIFY).
  Migrating is a recommended step before any closed-source or commercial
  distribution; it has NOT been tested here (no Qt available in the patch
  environment).

## 2. Data sources and terms of service
Scrapers that call official APIs (arXiv, PubMed E-utilities, OpenAlex,
Crossref, Semantic Scholar, ORCID, DBLP, OpenCitations, Unpaywall, CORE,
Springer, IEEE, BASE) must follow each provider's terms and rate limits.
Scrapers that parse HTML pages or drive a browser (`google_scholar`, `acm`,
`sciopen`) and the free-proxy pool in `proxy/` can conflict with provider terms.
Use them only where you have the right to do so. They are not suitable for a
hosted service offered to institutions without written permission.

## 3. Journal- and author-level indicators
`bibliometrics/journal_metrics.py` computes proxies from the supplied corpus.
Values are not the official Clarivate, Elsevier or SCImago figures and must not
be presented as such.

## 4. Web server defaults
- CORS defaults to the local origins for the configured port. Override with
  `ARS_CORS_ORIGINS` (comma-separated; `*` restores open CORS).
- `ARS_SECRET_KEY` sets the Flask secret; otherwise a random per-process key
  is generated.
- The web API has no authentication. Bind it to localhost only, or place it
  behind an authenticating reverse proxy.

## 5. EU regulation (VERIFY with counsel)
GDPR (author names and ORCID iDs are personal data), EU AI Act (LLM features),
Cyber Resilience Act (if distributed as a product), copyright text-and-data-mining
rules for each data source.

## 6. Licence of this repository
MIT. Existing MIT-licensed code remains available under MIT.
