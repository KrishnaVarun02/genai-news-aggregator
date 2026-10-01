# Verification record

Checks performed on **2026-10-01**. Host: **macOS 26.6.2, Apple Silicon arm64**, native **CPython 3.13.5**, **uv 0.11.18**, isolated `.venv`. Local Docker engine reported **Linux aarch64**. Container integration is reported separately from native execution.

| Actual check | Observed result |
|---|---|
| `uv lock`; `uv sync --locked`; optional `uv sync --locked --extra documents` | 141 packages resolved in lock; core and Docling isolated installs completed |
| `uv run --no-sync pytest -q -m 'not integration and not document'` | **27 passed**, 2 deselected; final run 1.89 seconds |
| `RUN_SERVICE_TESTS=1 TEST_DATABASE_URL=.../news_test uv run --no-sync pytest -q -m integration` | **1 passed**, 28 deselected; real PostgreSQL 17 and Mailpit, 3.32 seconds |
| `RUN_DOCLING_TESTS=1 uv run --no-sync pytest -q -m document` | **1 passed**, 28 deselected; real Docling conversion of authored HTML, 55.24 seconds including first import |
| `uv run --no-sync news demo` | 4 authored fixture rows, 3 current-window summaries, 3 selected stories, four preview files; no network/model/email |
| Native `news run --mode fixture --send sink`, then `news inspect` | `sent_sink`; PostgreSQL counts **articles=4, summaries=3, digests=1** |
| Public `news collect --mode live --hours 168 --database-url sqlite:///data/live-check.db` | **21 collected/inserted**, no errors or warnings; **6 YouTube, 11 OpenAI, 4 Anthropic research**. All five configured feeds fetched; Anthropic news/engineering contributed no matching items in that window |
| `news enrich --mode live --description-only-articles --database-url sqlite:///data/live-check.db` | **6 actual YouTube transcripts**, 15 descriptions; no errors |
| `news enrich --mode live --retry-enrichment --database-url sqlite:///data/live-check.db` after Docling install | Final provenance **6 transcripts, 4 Markdown articles, 11 OpenAI descriptions**; no errors |
| `docker build -t genai-news-aggregator:local .` | Final base application image built successfully for Linux arm64 |
| `docker run --rm genai-news-aggregator:local uv run --no-sync news demo` | Container fixture demo completed, 4/3/3 and preview created |
| Final image against fresh `news_container_test` PostgreSQL DB and Mailpit on Compose network | 4 inserted, 3 summarized, 3 selected; **sent_sink**, no errors |
| Render Blueprint against downloaded official `https://render.com/schema/render.yaml.json` using Draft7Validator | **PASS**, zero schema errors; valid cron and PostgreSQL plan names |
| Browser rendering of generated fixture HTML | Captured `examples/fixture-digest.png` with temporary Chrome headless profile; image inspected visually, all three sections readable without clipping |

The source counts and content are point-in-time observations, not fixed expected live outputs. Public articles/transcripts were stored only in ignored local data, never committed. Preview examples contain only original invented fixture text. The temporary preview browser was closed after capture.

One malformed-feed test initially found that feedparser can accept an HTML error page without setting `bozo`. The parser now also requires a recognized RSS/Atom version. The deterministic suite passed after the fix. Feedparser emits a Python 3.13 deprecation warning about its own positional regex argument; it does not affect test outcomes.

An independent code review also led to verified fixes: SMTP configuration is validated before claiming delivery; corrected enrichment regenerates stale summaries/unsent previews; old failed items cannot block a later publication window; skipped-entry warnings no longer suppress successful collection. Tests cover these regressions.

## Observed GitHub Actions results

The published implementation commit [`7c25aea7e3140a04dec2df27e16287cabf607bd6`](https://github.com/KrishnaVarun02/genai-news-aggregator/commit/7c25aea7e3140a04dec2df27e16287cabf607bd6) passed **all four jobs** in [run 36821941430](https://github.com/KrishnaVarun02/genai-news-aggregator/actions/runs/36821941430), completed on 2026-10-01. Job logs, test counts, platform images, and actual demo steps were inspected. Every job installed the locked dependencies with CPython 3.13.5.

| Actual CI platform | Evidence | Observed behavior |
|---|---|---|
| Windows Server 2025, 10.0.26100, x86_64; PowerShell | [Native Windows job](https://github.com/KrishnaVarun02/genai-news-aggregator/actions/runs/36821941430/job/110239204520) | **27 passed** in 10.60s; fixture CLI demo and preview-artifact upload succeeded |
| macOS 26.6.2 (25G83), arm64 | [Native macOS job](https://github.com/KrishnaVarun02/genai-news-aggregator/actions/runs/36821941430/job/110239204613) | **27 passed** in 2.21s; fixture CLI demo and preview-artifact upload succeeded |
| Ubuntu 24.04.5, x86_64 | [Native Linux job](https://github.com/KrishnaVarun02/genai-news-aggregator/actions/runs/36821941430/job/110239204571) | **27 passed** in 2.91s; fixture CLI demo and preview-artifact upload succeeded |
| Ubuntu 24.04.5, x86_64; PostgreSQL 17.6 and Mailpit services | [Database/email/container job](https://github.com/KrishnaVarun02/genai-news-aggregator/actions/runs/36821941430/job/110239204370) | **1 integration test passed** in 1.21s; application Docker image built and container fixture demo succeeded |

This proves native application setup and deterministic behavior on those specific hosted platforms. It does not prove installation of Docker Desktop/WSL2 on a Windows workstation, Windows 10/11 desktop behavior, native Intel macOS Docling support, or real paid integrations. Docling and live public-source checks were performed on local macOS as recorded above, not in the native CI matrix. Subsequent commit results are available in [the repository's Actions history](https://github.com/KrishnaVarun02/genai-news-aggregator/actions).

After local verification, `docker compose down` stopped and removed only this project's PostgreSQL/Mailpit containers and network. The named PostgreSQL volume was preserved; `docker compose ps` showed no running project containers. Restart with `docker compose up -d postgres mailpit`.

## Exactly what remains external

- **Additional platforms:** native CI results are established above. Windows ARM, Windows 10/11 desktop machines, Docker Desktop/WSL2 installation on Windows, and native Intel macOS Docling remain unverified.
- **Live OpenAI:** no paid API request was made. The actual OpenAI Python SDK's Responses parser was exercised against an HTTP mock and structured schemas. This validates request/response handling, not account access, model availability for the user's account, live summary quality, or stochastic ranking. `news check-openai` and `news run --mode live --send preview` are the explicit real-service checks after credentials and spending authorization.
- **Real recipient email:** no Gmail or external recipient was contacted. Local SMTP and MIME delivery were verified against Mailpit. Gmail app-password authentication and real delivery require the user's explicit recipient instruction.
- **Render:** public schema validation passed; account authorization, resource creation, billing, scheduling, deployed database networking, production memory footprint, and actual cloud execution are untested. See README's concrete deployment steps.
- **Private tutorial source:** unavailable without registration; exact prompts/schema/UI template cannot be compared. See REFERENCE.md for independently chosen details.

## Reproduce key checks

Run from the repository root using the shell-specific setup in README:

```sh
uv sync --locked
uv run --no-sync pytest -q -m 'not integration and not document'
uv run --no-sync news demo
docker compose up -d postgres mailpit
uv run --no-sync news run --mode fixture --send sink
uv run --no-sync news inspect
```

The service and Docling test environment variables are documented for both PowerShell and zsh/bash in README. `docker compose down` stops the local services; `docker compose down -v` additionally deletes only this project's local PostgreSQL volume.
