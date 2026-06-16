# Architecture

Layered structure for the 52wmb Pro 2026 transaction scraper. Each layer has a
single concern and depends only on layers below it.

```
┌─────────────────────────────────────────────────────────────────────────┐
│ cli/                       Entry points: `python run.py`, recon, bench  │
└─────────────────────────────────────────────────────────────────────────┘
                                       │ invokes
┌─────────────────────────────────────────────────────────────────────────┐
│ pipeline/                  Orchestration + recovery + segment handling  │
│   detail_pipeline.py       run_transaction_pipeline — top-level loop    │
│   daily_pipeline.py        Day-by-day variant                           │
│   segment_handler.py       10k-record segment boundaries                │
│   recovery.py              soft / deep recovery flows                   │
└─────────────────────────────────────────────────────────────────────────┘
                                       │ uses
┌─────────────────────────────────────────────────────────────────────────┐
│ extract/                   Data extraction — UI click + CDP capture     │
│   detail_capture.py        click_details_and_capture + drawer           │
│   http_fetcher.py          Direct API via httpx (experimental)          │
│   async_fetcher.py         Parallel asyncio fetcher                     │
└─────────────────────────────────────────────────────────────────────────┘
                                       │ uses
┌─────────────────────────────────────────────────────────────────────────┐
│ nav/                       UI navigation                                │
│   navigator.py             login flow, page navigation                  │
│   search_form.py           fill + submit search                         │
│   pagination.py            go_to_page, next/prev                        │
└─────────────────────────────────────────────────────────────────────────┘
                                       │ uses
┌─────────────────────────────────────────────────────────────────────────┐
│ parsing/                   Field normalization + server-title mapping   │
│   field_mapping.py         FIELD_MAPPING, ALIASES                       │
│   normalizer.py            date, currency, string cleanup               │
│                                                                         │
│ storage/                   Output writers + checkpoint                  │
│   csv_sink.py              append_to_csv + dedupe by bill_id            │
│   excel_sink.py            Final xlsx export                            │
│   checkpoint_store.py      detect_resume_point (segment/page/stt)       │
└─────────────────────────────────────────────────────────────────────────┘
                                       │ uses
┌─────────────────────────────────────────────────────────────────────────┐
│ core/                      Infrastructure — Chrome/CDP/auth             │
│   browser.py               get_driver, Chrome version auto-detect       │
│   cdp.py                   Network capture helpers                      │
│   auth.py                  login, manual fallback                       │
│   tokens.py                localStorage extraction (access-token)       │
└─────────────────────────────────────────────────────────────────────────┘
                                       │ uses
┌─────────────────────────────────────────────────────────────────────────┐
│ models/                    Typed data models (Transaction, ListItem)    │
│                                                                         │
│ config/                    Pydantic Settings, env-driven                │
│   settings.py              Base config                                  │
│   scrape_filters.py        Country/HS/date/buyer filters                │
│   proxy.py                 Brightdata config                            │
│                                                                         │
│ observability/             Logging + metrics (shared by every layer)    │
│   logger.py                log() + level icons                          │
│   metrics.py               RateMeter, Timer, SessionExpired, ApiError   │
└─────────────────────────────────────────────────────────────────────────┘
```

## Dependency Rule

A module imports only from **lower** layers (rows below). Never sideways, never
up. This keeps refactors local and prevents cycles.

`observability/` is an exception — it is dependency-free and may be imported by
any layer.

## Data Flow

```
Selenium browser ──► CDP performance log ──► extract/ ──► parsing/ ──► storage/
        ▲                                         │
        │                                         ▼
    nav/ (login + form + pagination)     models.Transaction (typed)
```

Each scraped page produces a batch of `Transaction` records. The pipeline layer
writes them to CSV (bronze), and a separate finalize step converts to xlsx
(gold) with column ordering + dedup.

## Configuration

All config comes from **environment variables** (read by `config/`), with
sensible defaults. No secrets in code. Copy `src/config.example.py` to
`src/config.py` and fill locally (gitignored). Env vars override file values so
the same code runs unchanged in dev/staging/prod.

## Current status

This document describes the **target** layout. The codebase is incrementally
migrating toward it in small PRs so `python run.py` keeps working at every
step. See `OPERATIONS.md` for runtime behaviour.
