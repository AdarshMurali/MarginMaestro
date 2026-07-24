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

## 2. Unstructured data (documents → RAG)

These feed the vector store and are what the RAG agents reason over. For the demo, curate **4–6 well-chosen documents per counterparty** — enough to prove the concept without ballooning ingestion.

| Document | Role | Source for demo | Consumed by |
|---|---|---|---|
| **CSA / Credit Support Annex** (part of the client agreement family) | Threshold, MTA, eligible collateral, haircuts, rating triggers | ISDA public CSA templates + synthetic fill-in | CSA-RAG |
| **Client / master agreement** | Governing terms (CSA sits within this — treat as one family, don't double-count) | ISDA templates / SEC EDGAR | CSA-RAG |
| **Margin policy docs** | Internal policy: timing, valuation, thresholds | Synthetic (written for the project) | Orchestrator, CSA-RAG |
| **Eligible collateral & haircut schedule** | Source of truth for optimizer | Synthetic (often inside CSA) | Collateral Optimizer |
| **Exception rules** | How to handle edge cases / dispute exceptions | Synthetic | Reconciliation |
| **Escalation procedures** | When/how to escalate non-response | Synthetic | SLA / Escalation |
| **Historical margin dispute notes** | Precedent for resolving disputes (retrieve similar past cases) | Synthetic corpus | Reconciliation |
| **SIMM / IM methodology** | Grounds the IM computation | ISDA SIMM public methodology + synthetic notes | Calculation (reference) |

## 3. Events (triggers)

| Event source | Real | Simulated | Notes |
|---|---|---|---|
| Price ticks | free feeds during market hours | **market simulator** publishes scripted ticks | Simulator is the default for demo/test determinism |
| News / macro events | GDELT (free), RSS, NewsAPI free tier, SEC EDGAR full-text | **synthetic event injector** | Mapped to curated universe only |
| Rating downgrades | — | synthetic rating event | Drives CSA rating triggers |

The **market simulator** and the **live feed adapter** implement one `MarketFeed` interface; `MARKET_FEED_MODE` (`simulated`/`live`) selects. Same Kafka topic either way.

## 4. Vector store design (ChromaDB)

- **Chunking:** semantic/section-based for legal docs; keep clauses intact where possible.
- **Embeddings:** local `BAAI/bge-small-en-v1.5` (free, no API cost).
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
