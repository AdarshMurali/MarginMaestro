# MarginMaestro — Data Sources

Two data planes. Keep them separate — it's a core architectural point.

- **Structured / numeric → Azure SQL** (+ Kafka in flight). Drives the deterministic math.
- **Unstructured / documents → ChromaDB** (via the RAG pipeline). Drives the LLM reasoning.

All data is **free or synthetic**. No proprietary or employer data is ever used.

---

## 1. Structured data (numbers)

| Data | Source | Cost | Store | Used by |
|---|---|---|---|---|
| **Live/EOD security prices** | `yfinance` (Yahoo), Stooq, Alpha Vantage / Twelve Data / Tiingo (free tiers) | Free | Kafka → SQL | Calculation, Event |
| **Volatile intraday prices (demo)** | Crypto APIs — Binance / Coinbase / CoinGecko | Free | Kafka → SQL | Calculation, Event |
| **Rates / yields / VIX / macro** | **FRED** (St. Louis Fed) API; US Treasury API | Free | SQL | Calculation (IM/haircuts) |
| **Portfolio / positions** | **Synthetic** (generated JSON/CSV) | Free | SQL | Calculation |
| **Collateral inventory** | **Synthetic** | Free | SQL | Collateral Optimizer |
| **Counterparty credit ratings** | **Synthetic** (so downgrades can be simulated) | Free | SQL | Event (rating triggers) |
| **Settlement / holiday calendars** | Synthetic or open calendar libs | Free | SQL | SLA / settlement timing |
| **Audit log & ticket state** | Generated at runtime (system output) | Free | SQL | Audit, Escalation |

### 1a. Securities universe (curated, real — decided Phase 1 planning, 2026-07-25)

30 real, liquid tickers — deliberately curated per the golden-rule-#7 "small fixed set," not open-world:

- **Mega-cap equities:** `AAPL`, `MSFT`, `GOOGL`, `AMZN`, `TSLA`, `NVDA`, `META`, `HPE`, `JPM`, `WFC`, `SPCX`
- **2026-buzzing (verified via live search, not assumed from stale knowledge):** `PLTR`, `AMD`, `MU`, `SMCI`, `NFLX`, `INTC`
- **S&P 500 proxy:** `SPY` (the ETF — the raw index isn't a holdable position)
- **Sector rounding:** `XOM` (energy), `JNJ` (healthcare), `BRK-B`, `V`, `DIS`
- **Government securities:** `IEF`, `TLT`, `SHY` (US Treasury bond ETFs) — substituting for Indian G-Secs, which have **no free API/ticker access** (they trade via RBI/NSE bond platforms, not `yfinance` or any free retail feed)
- **Crypto:** `BTC-USD`, `ETH-USD`, `SOL-USD`, `XRP-USD`

Synthetic portfolios (MM-11) sample positions from this pool, so `yfinance`/CoinGecko only ever fetch prices for these 30 tickers, not per-position.

### 1b. Azure SQL: local vs. real (decided 2026-07-25)

The user has a real Azure SQL free-tier instance but has used this month's free quota. Dev/CI uses a local `azure-sql-edge` container (`docker-compose.yml`, added in MM-12) instead — same engine family as real Azure SQL. Connection config (`DB_HOST`/`DB_PORT`/`DB_NAME`/`DB_USER`/`DB_PASSWORD`, already in `.env.example`) is the *only* thing that changes to point at the real instance later; no code path differs between local and Azure.

## 2. Unstructured data (documents → RAG)

These feed the vector store and are what the RAG agents reason over. Each document type is built in the phase that actually consumes it — building a document nobody queries yet produces untested, unverified corpus, so **Phase 3 builds only what CSA-RAG needs** (see 2a); the rest are built alongside Phase 6/7.

| Document | Role | Source for demo | Consumed by | Built in |
|---|---|---|---|---|
| **CSA / Credit Support Annex** (part of the client agreement family) | Threshold, MTA, eligible collateral, haircuts, rating triggers | Seeded generator, one per counterparty (varies — not a template) | CSA-RAG | Phase 3 (MM-23) |
| **Client / master agreement** | Governing terms (CSA sits within this — treat as one family, don't double-count) | Folded into the CSA document itself | CSA-RAG | Phase 3 (MM-23) |
| **Margin policy docs** | Internal policy: timing, valuation, thresholds — firm-wide, not counterparty-specific | Synthetic (hand-authored for the project) | Orchestrator, CSA-RAG | Phase 3 (MM-23) |
| **Eligible collateral & haircut schedule** | Source of truth for optimizer | Folded into the per-counterparty CSA document | Collateral Optimizer | Phase 3 (MM-23) |
| **Exception rules** | How to handle edge cases / dispute exceptions — firm-wide policy | Synthetic | Reconciliation | Phase 7 |
| **Escalation procedures** | When/how to escalate non-response — firm-wide policy | Synthetic | SLA / Escalation | Phase 6 |
| **Historical margin dispute notes** | Precedent for resolving disputes (retrieve similar past cases) — tied to specific past events, not 1:1 per counterparty | Synthetic corpus | Reconciliation | Phase 7 |
| **SIMM / IM methodology** | Reference notes on the IM proxy's methodology — not currently queried by any agent | ISDA SIMM public methodology + synthetic notes | (deferred — no consumer yet) | Deferred |

### 2a. Document corpus & storage (decided Phase 3 planning, 2026-07-26)

- **9 documents total for Phase 3:** 8 per-counterparty CSA docs (`src/rag/csa_corpus.py`, seeded/reproducible — threshold, MTA, eligible collateral, haircuts, and rating triggers all *vary* per counterparty, so retrieval is a real test, not a lookup table in disguise) + 1 shared, hand-authored margin policy doc.
- **Storage: S3**, not just local disk — a new bucket (`infra/s3.tf`: private, versioned, SSE-encrypted) is the durable source of truth for citations and re-ingestion. ChromaDB only ever holds a derived, rebuildable index (chunks + vectors) of what's in S3 — it is never the source of truth for the raw document text.
- **Embeddings: OpenAI `text-embedding-3-small`**, not local BGE — see ADR-0006 (supersedes ADR-0004's local-embeddings rationale). Query and document embeddings must come from the same model for similarity search to be meaningful at all, and this machine's RAM constraints (see the WSL2 memory-cap troubleshooting from Phase 1) make a locally-hosted embedding model an added burden that a cheap hosted API avoids.
- **LLM reasoning: OpenAI `gpt-4o-mini`**, not Ollama — Ollama isn't installed and this machine (8GB RAM) isn't a good fit for running a local LLM alongside everything else already competing for memory.

## 3. Events (triggers)

| Event source | Real | Simulated | Notes |
|---|---|---|---|
| Price ticks | free feeds during market hours | **market simulator** publishes scripted ticks | Simulator is the default for demo/test determinism |
| News / macro events | GDELT (free), RSS, NewsAPI free tier, SEC EDGAR full-text | **synthetic event injector** | Mapped to curated universe only |
| Rating downgrades | — | synthetic rating event | Drives CSA rating triggers |

In live mode, publishing onto `market.prices` is done by a fixed-interval poller (`streaming/live_feed_poller.py`, `LIVE_FEED_POLL_INTERVAL_SECONDS`, MM-59) — never per-request. `/exposure` and the price chart only ever read the `latest_prices`/`price_history` SQL tables that poller (via the Event Agent's unconditional upsert) and the daily batch loader keep fresh.

The **market simulator** and the **live feed adapter** implement one `MarketFeed` interface; `MARKET_FEED_MODE` (`simulated`/`live`) selects. Same Kafka topic either way.

## 4. Vector store design (ChromaDB)

- **Chunking:** semantic/section-based for legal docs; keep clauses intact where possible.
- **Embeddings:** OpenAI `text-embedding-3-small` (see ADR-0006 — superseded local `BAAI/bge-small-en-v1.5`; negligible cost at this corpus size, avoids a local model's memory footprint, and keeps query/document embeddings in the same vector space by construction since there's only one embedding call path).
- **Metadata per chunk:** `counterparty_id`, `doc_type`, `effective_date`, `source_file`, `section`.
- **Retrieval:** filter by `counterparty_id` + `doc_type` before similarity search → precise, cited answers.
- **Why Chroma:** free, container-friendly, ample for this document volume. `pgvector` is the alternative if co-locating vectors with relational data is preferred (ADR-0004).

## 5. What is NOT streamed

Daily-only reference data (EOD backfill prices, ratings snapshots, calendars) is loaded by a **scheduled batch job** (EventBridge → Lambda), not Kafka. Only intraday ticks/events flow through the stream. Using streaming for daily data would be over-engineering.

## 6. Data governance notes (for the "production-grade" story)

- Clear separation of numeric vs document planes.
- All external inputs validated with Pydantic at ingestion.
- Synthetic data generators are versioned and seeded → reproducible datasets.
- Citations retained on every RAG answer for auditability.
- No secrets in data configs; connection strings via Parameter Store.
