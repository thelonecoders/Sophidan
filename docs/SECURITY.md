# Security Policy

## Supported Versions

Academic Research Suite is in active development. The following
versions receive security updates:

| Version | Supported | Notes |
|---|---|---|
| `v1.0.x` | ✅ | Current release line. |
| `v1.1.x` (planned) | ✅ | Once released. |
| `< v1.0` (pre-release alphas, betas) | ❌ | Upgrade to v1.0.x. |
| `develop` branch HEAD | ⚠️ | Best-effort; not a release. |

We backport security fixes to the latest `v1.0.x` tag within **7
days** of disclosure. Older release lines are not supported —
upgrade to the latest minor release.

## Reporting a Vulnerability

**DO NOT open a public GitHub issue for security vulnerabilities.**

Instead, please report vulnerabilities privately:

1. Email **<security@academic-research-suite.org>** with:
   - A description of the issue and its impact.
   - The minimum reproduction steps (commands, config, payload).
   - The version of ARS you tested against (`python main.py
     --version`).
   - The OS / Python version.
2. You will receive an acknowledgement within **48 hours**.
3. We will assess severity within **7 days** and propose a fix
   timeline (critical: 7 days; high: 30 days; medium: 90 days;
   low: next release).
4. Once a fix is shipped, we will publish a security advisory on
   GitHub and credit you (unless you prefer to remain anonymous).

### Coordinated disclosure

We follow coordinated disclosure: we will not publish details of
the vulnerability until a fix is available, and we ask that you
do the same. If you intend to publish a write-up after the fix is
released, please coordinate timing with us.

### Out-of-scope

The following are NOT considered ARS security vulnerabilities:

- Bugs in upstream dependencies (PyQt5, Flask, SQLAlchemy, ChromaDB,
  OpenAI SDK, Anthropic SDK, Ollama, etc.) — report those upstream.
- Issues that require the attacker to have local code execution
  on your machine (you should not run untrusted ARS plugins
  from sources you don't control — see below).
- Issues that arise from running ARS with `--host 0.0.0.0 --debug`
  on a hostile network — that's a documented misuse; the default
  is `--host 127.0.0.1`.

## Security Best Practices for Users

### API key storage

ARS stores API keys in two places:

1. **`config/secrets.yaml`** (file on disk, gitignored).
2. **Environment variables** (`ARS_AI_API_KEY`, `OPENAI_API_KEY`,
   `ANTHROPIC_API_KEY`, `SEMANTIC_SCHOLAR_API_KEY`).

Both are subject to filesystem permissions. We recommend:

```bash
chmod 600 config/secrets.yaml
# Or use a secret manager that materializes the env var at runtime:
eval "$(op signin)"  # 1Password CLI example
export ARS_AI_API_KEY="$(op read 'op://Private/openai-key')"
```

**Never** commit `secrets.yaml` to git — the file is in
`.gitignore` by default, but verify:

```bash
git check-ignore -v config/secrets.yaml
# Should print: .gitignore:42:config/secrets.yaml
```

### Proxy trust

ARS's proxy suite routes HTTP traffic through third-party proxies
scraped from free lists. **These proxies can see and modify your
traffic** unless you use HTTPS (TLS). Mitigations:

1. **Always use HTTPS endpoints when scraping** — the
   `BaseScraper._make_request` helper TLS-wraps HTTPS targets
   via `ssl.create_default_context`.
2. **Prefer your own paid proxies** — import them via the Proxy
   panel's **Import** button (TXT / JSON / CSV).
3. **Never authenticate to a non-HTTPS service through a free
   proxy** — credentials will leak.
4. **Disable the proxy suite entirely** if you don't need it:
   set `ARS_PROXY_ENABLED=false` in `config/secrets.yaml`.

### Scraping rate limits

ARS enforces per-source rate limits via `BaseScraper`'s
`_TokenBucket` (default 1 req/s, configurable via the
`rate_limit` constructor arg). However:

- **arXiv** asks for ≤0.33 req/s (≤1 req/3s). The arXiv scraper
  defaults to this; don't override unless you have a reason.
- **PubMed** allows 3 req/s without an API key, 10 req/s with
  one (set `NCBI_EMAIL`).
- **Crossref**'s polite pool allows 50 req/s — set
  `CROSSREF_MAILTO` to your email.
- **Semantic Scholar** allows 1 req/s without a key, 100 req/s
  with `SEMANTIC_SCHOLAR_API_KEY`.
- **Google Scholar** has no published limit and captchas
  aggressively — the built-in scraper rotates proxies and
  backs off, but expect partial failures.

If you exceed these limits, the upstream may ban your IP. ARS's
rate limiter prevents accidental abuse; do not bypass it.

### Web server exposure

The web server binds to `127.0.0.1:8765` by default — local only,
no authentication. If you expose it to a network:

```bash
python main.py --web --host 0.0.0.0  # DANGEROUS
```

then:

1. **Put it behind a reverse proxy** (nginx, Caddy) with TLS.
2. **Add an authentication layer** (Basic Auth at the proxy,
   or wait for v1.1.0's built-in API token auth).
3. **Restrict CORS** — set `CORS_ORIGINS` in
   `web/server.py::create_app` to your domain.

Until v1.1.0 ships token auth, the web server should be treated
as **single-user, local-only**.

### Local LLM (privacy)

When you use `ai_provider: "ollama"`, the LLM runs locally on your
machine. Your paper abstracts, prompts, and chat history never
leave your machine — ideal for sensitive research data.

When you use `ai_provider: "openai"` or `"anthropic"`, your
prompts and any paper content you paste into the chat are sent to
the provider's API. Review the provider's data retention policy
before pasting unpublished research.

### Database backups

`data/ars.db` contains your entire paper corpus, project metadata,
and snapshots. Back it up regularly:

```bash
# Hot backup via VACUUM INTO (atomic, online)
sqlite3 data/ars.db "VACUUM INTO 'backups/ars-$(date +%Y%m%d).db'"

# Or via the ARS UI: Settings → Database → Backup
```

The ChromaDB vector store at `data/chroma/` should also be
included in your backup rotation.

### Plugin safety (future)

ARS v1.2.0 will introduce a plugin system. Plugins run with the
same permissions as the ARS process — **only install plugins
from sources you trust**. We will publish a curated plugin
registry at that time.

## Contact

- **Security email:** <security@academic-research-suite.org>
- **PGP key:** available at <https://keys.openpgp.org> (search for
  the security email).
- **General issues:** <https://github.com/academic-research-suite/academic_research_suite/issues>

---

*This policy is reviewed at every minor release. Last updated:
2026-08-25 for v1.0.0.*
