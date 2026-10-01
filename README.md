# GenAI news aggregator

An independent implementation of Dave Ebbelaar's [end-to-end AI news project](https://www.youtube.com/watch?v=E8zpgNPx8jE): collect YouTube, OpenAI, and Anthropic news; store and deduplicate it in PostgreSQL; enrich articles; generate structured summaries; rank by a reader profile; and create a daily email digest.

The creator's private repository was unavailable without registration. This project implements the publicly demonstrated behavior without copying private code. [REFERENCE.md](REFERENCE.md) records inspected material, timestamps, verified details, and differences. There is no dashboard: the product is a scheduled Python pipeline and its email output.

![Authored fixture email, not live news](examples/fixture-digest.png)

## What runs

1. Matthew Berman's YouTube RSS channel, OpenAI's RSS feed, and the three Olshansk Anthropic RSS feeds are in `config/sources.json`.
2. Article URLs and source IDs deduplicate collection. PostgreSQL retains original publication time separately from ingestion time.
3. YouTube uses `youtube-transcript-api`; Anthropic uses the optional Docling HTML-to-Markdown adapter. OpenAI keeps RSS descriptions, matching the tutorial's final response to blocked article scraping. Missing enrichment is recorded explicitly and falls back to the feed description.
4. OpenAI **Responses API** `gpt-4.1-mini` produces a title, 2–3 sentence summary, and category. `gpt-4o-mini` scores every current-window summary against `config/profile.json`, then selects the top 10 by default. A separate introduction call uses `gpt-4o-mini`; that email model choice could not be verified from private code.
5. The digest writes HTML, Markdown, JSON, and a MIME `.eml` preview. Delivery defaults to files. Mailpit is a local email sink; Gmail SMTP with STARTTLS is available only with explicit real-delivery configuration.

Fixture mode uses **original authored examples and a deterministic test double**, never OpenAI or live collection. Both records and visible outputs identify it. Live and fixture articles have different database identities and cannot mix in a digest.

## Prerequisites and architecture

- Python **3.13.5**, uv **0.11.18**; the lock supports Python 3.11–3.13. `uv sync` creates a local isolated `.venv` and can install the pinned interpreter.
- Docker Desktop with Linux containers for PostgreSQL/Mailpit and the optional app container. On Windows use its WSL2 backend; the Python CLI still runs natively in PowerShell. A compatible local Docker engine also works.
- Core native Python supports Windows amd64, macOS Apple Silicon/Intel, and Linux. Docker images select native Linux arm64 on Apple Silicon or Linux amd64 on Intel/Windows; do not force amd64 on Apple Silicon unless you intentionally want emulation.
- Docling has larger Torch dependencies. Full native extraction is intended for Apple Silicon, Windows amd64, and Linux; on Intel macOS use the Linux Docker image with `WITH_DOCUMENTS=true` if Torch wheels are unavailable. Windows ARM and native Intel Docling are not claimed as verified.
- No paid credentials are needed for fixture tests, public feed collection, transcript retrieval, PostgreSQL, or Mailpit. OpenAI usage and Render hosting require separate spending authorization.

## macOS quick start: zsh/bash

Run from the repository root:

```sh
uv sync --locked
uv run --no-sync pytest -q -m 'not integration and not document'
uv run --no-sync news demo
open examples/fixture-digest.html

cp .env.example .env
docker compose up -d postgres mailpit
uv run --no-sync news run --mode fixture --send sink
uv run --no-sync news inspect
open http://localhost:8025
```

`news demo` is completely local and uses SQLite `data/demo.db` to make the first run immediate. The subsequent `news run` uses **PostgreSQL**, as in the tutorial. The expected fixture flow inserts 4 articles, summarizes the 3 inside the 24-hour window, generates 3 selected stories, and reports `sent_sink`. The old fourth article proves filtering uses publication time. A second identical run reports 4 duplicates, 0 new summaries, the reused digest, and no duplicate email.

## Windows quick start: PowerShell

```powershell
$env:PYTHONUTF8 = '1'
uv sync --locked
uv run --no-sync pytest -q -m 'not integration and not document'
uv run --no-sync news demo
Start-Process examples/fixture-digest.html

Copy-Item .env.example .env
docker compose up -d postgres mailpit
uv run --no-sync news run --mode fixture --send sink
uv run --no-sync news inspect
Start-Process http://localhost:8025
```

No shell activation, PowerShell execution-policy change, or Unix script is needed. The `.env` file is ignored by Git and read using `python-dotenv`; environment variables take precedence. Local database credentials in `.env.example` are intentionally public development values, and ports bind to loopback only.

## Live sources without paid model calls

These identical commands work in either shell after PostgreSQL starts:

```sh
uv run --no-sync news collect --mode live --hours 168
uv run --no-sync news enrich --mode live --description-only-articles
uv run --no-sync news inspect
```

The first command collects actual articles from the past seven days; changing news means counts vary. The second retrieves actual YouTube transcripts while preserving feed descriptions for articles. It makes no model requests. For the demonstrated Anthropic document extraction, install the extra and retry enrichment:

```sh
uv sync --locked --extra documents
uv run --no-sync news enrich --mode live --retry-enrichment
```

Enrichment failure is persisted as `unavailable` with a safe reason; routine runs do not repeatedly fetch a known unavailable transcript. `--retry-enrichment` explicitly retries missing content. Successful enrichment invalidates the earlier description-based summary, records its provenance, and refreshes an unsent digest after resummarization. A previously sent digest remains an immutable record.

Feeds use bounded HTTP timeouts and size limits. Failed sources are reported individually; collected articles from successful sources remain stored, but a partial daily email is not sent until collection succeeds. Invalid/undated entries are reported as warnings and skipped. Original article HTML is treated as data, and digest HTML escapes all external/model text.

## Live summaries and ranking

First edit `config/profile.json`. After API spending is authorized, configure `OPENAI_API_KEY` locally and set `ALLOW_PAID_API=true` in `.env`. Never commit the real key. The default models preserve the tutorial; overrides are `SUMMARY_MODEL`, `CURATOR_MODEL`, and `EMAIL_MODEL`.

```sh
uv run --no-sync news check-openai
uv run --no-sync news run --mode live --hours 24 --send preview
```

`check-openai` is a **real billable** structured-output check, not part of automated tests. The pipeline requests structured Pydantic outputs with bounded retries/timeouts. It rejects refusals, incomplete outputs, invented/missing/duplicate ranking IDs, and invalid scores. Summary failures leave work retryable and prevent a partial digest. Nothing silently switches live mode to fixture mode.

The model sees at most 100,000 characters per article, with truncation explicitly marked. All summaries within the publication window go to the curator. Very large feeds can exceed provider limits; that fails clearly and requires reducing sources or the window, rather than silently dropping candidates. Article content and profile strings are provided as untrusted data, with no tool execution.

## Email delivery

- `--send preview` (default): only writes files under `previews/` and persists the digest JSON in the database.
- `--send sink`: only loopback or the Compose `mailpit` hostname, no SMTP authentication; recipients are always `example.invalid`. Inspect mail at [localhost:8025](http://localhost:8025).
- `--send real`: requires `ALLOW_REAL_EMAIL=true`, authorized real `SMTP_FROM`/`SMTP_TO`, SMTP credentials, and STARTTLS. Fixture messages are rejected. This project has not sent mail to any real recipient.

For the tutorial's Gmail path, configure `SMTP_HOST=smtp.gmail.com`, `SMTP_PORT=587`, `SMTP_STARTTLS=true`, your account as `SMTP_USERNAME`, and an app password as `SMTP_PASSWORD`. Google documents the [app-password prerequisites](https://support.google.com/accounts/answer/185833). Only after explicit recipient authorization, a human operator can run:

```sh
uv run --no-sync news run --mode live --send real
```

Each day/profile/window/mode has one digest identity. Unsent previews refresh if their source catalog changes; sent digests are retained. The database atomically claims delivery. A transport failure leaves `delivery_uncertain` and is never automatically resent: inspect SMTP delivery and the stored digest before manually changing that row's status to `preview`. SMTP cannot provide transactional exactly-once delivery with PostgreSQL, so uncertain delivery requires an operator decision. Invalid configuration is caught before claiming delivery.

## Container workflow

```sh
docker compose up -d postgres mailpit
docker compose build app
docker compose run --rm app uv run --no-sync news run --mode fixture --send sink
```

The base application image includes the core pipeline and YouTube transcripts. For full Anthropic extraction, build with `docker compose build --build-arg WITH_DOCUMENTS=true app`, or `docker build --build-arg WITH_DOCUMENTS=true -t genai-news-aggregator:documents .`. Docling images are larger; no GPU is required for HTML conversion. In the core image use `--description-only-articles` for live runs. The image has a complete `CMD` and no custom `ENTRYPOINT`, so Render's command override works directly.

## Tests and evidence

Deterministic tests use SQLite and authored input plus the **real OpenAI SDK with a mock HTTP transport**; no paid request is made. They verify RSS/Atom dates, malformed feeds, source failures, deduplication, original-date filtering, enrichment retries, provenance, structured-response parsing, profile ranking validation, HTML escaping, delivery gates, and actual CLI execution.

For real PostgreSQL/Mailpit tests, create the dedicated disposable database once:

```sh
docker compose exec -T postgres createdb -U news news_test
```

macOS:

```sh
RUN_SERVICE_TESTS=1 TEST_DATABASE_URL='postgresql+psycopg://news:local-development-only@localhost:55432/news_test' uv run --no-sync pytest -q -m integration
RUN_DOCLING_TESTS=1 uv run --no-sync pytest -q -m document
```

PowerShell:

```powershell
$env:RUN_SERVICE_TESTS = '1'
$env:TEST_DATABASE_URL = 'postgresql+psycopg://news:local-development-only@localhost:55432/news_test'
uv run --no-sync pytest -q -m integration
$env:RUN_DOCLING_TESTS = '1'
uv run --no-sync pytest -q -m document
```

The document test needs the `documents` extra and exercises actual Docling conversion of authored HTML without network/model downloads. The service test drops tables only in an explicitly configured `*_test` database. GitHub Actions runs native deterministic tests/demo on Windows, macOS, and Linux, plus Linux PostgreSQL/Mailpit and container verification. [VERIFICATION.md](VERIFICATION.md) records observed results and remaining external checks. [examples/fixture-digest.eml](examples/fixture-digest.eml) and [HTML preview](examples/fixture-digest.html) are safe, authored examples.

## Render deployment

`render.yaml` defines a daily **07:00 UTC** Docker cron job plus PostgreSQL 17. It was validated against Render's public JSON schema. No resources have been provisioned. Applying it creates paid resources; account access and explicit spending authorization are required.

After authorization, connect this repository in Render, create a Blueprint from `render.yaml`, review its cron/database plans and region, and set secret environment values in Render. The database connection comes from the managed database automatically. Keep `ALLOW_REAL_EMAIL=false` and `--send preview` for the first authorized API run; verify logs and the `digests.payload_json` database record, because cron local files are ephemeral. Then, only after real recipient authorization, set the SMTP variables and real-email flag and change the command to `uv run --no-sync news run --mode live --send real --description-only-articles`.

The shipped Render profile preserves transcript enrichment but uses article descriptions to keep its small memory footprint. For the tutorial's full Docling extraction, change the Docker build argument to `WITH_DOCUMENTS=true`, select adequate memory (for example the documented `1c-2g` plan, after reviewing costs), and remove `--description-only-articles`. Render exposes environment variables as Docker build arguments. The precise memory required depends on the source workload and has not been benchmarked on Render.

Source/schema: [Render Blueprint reference](https://render.com/docs/blueprint-spec), [public schema](https://render.com/schema/render.yaml.json), [Docker behavior](https://render.com/docs/docker). The initial blueprint deliberately has `ALLOW_PAID_API=false`; change it only after spending authorization. Cloud API, Gmail authentication/delivery, and a real Render run are external checks, not claimed successes.

## Shutdown and cleanup

The Python commands exit when done. Preserve local PostgreSQL data with `docker compose down`. To delete only this project's database volume, run `docker compose down -v` (destructive to this project's local articles/digests). No cleanup command touches unrelated containers or databases.

macOS:

```sh
docker compose down
# Optional local reset after saving anything you need:
docker compose down -v
rm -rf .venv data previews .pytest_cache
```

PowerShell:

```powershell
docker compose down
# Optional local reset after saving anything you need:
docker compose down -v
Remove-Item -Recurse -Force .venv, data, previews, .pytest_cache -ErrorAction SilentlyContinue
Remove-Item Env:RUN_SERVICE_TESTS, Env:TEST_DATABASE_URL, Env:RUN_DOCLING_TESTS -ErrorAction SilentlyContinue
```

Tables are created idempotently on startup. This initial independent schema does not claim compatibility with the private tutorial database or provide migrations for an unknown schema. For future application schema changes, back up data and add explicit migrations; `create_all` does not alter existing tables.
