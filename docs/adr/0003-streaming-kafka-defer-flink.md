# ADR-0003: Kafka as event backbone; defer Flink

- **Status:** Accepted
- **Date:** 2026-07-23

## Context

Margin calls must react to price moves during market hours — a real-time concern. There is a temptation to add both Kafka (streaming transport) and Flink (stream processing) because the data is "real-time." These solve different problems.

- **Real-time streaming (Kafka):** move events as they happen; a consumer reacts per event.
- **Stream *processing* (Flink):** stateful, windowed computation over the stream (rolling aggregations, CEP, large keyed state, exactly-once).

Per-tick threshold evaluation is essentially stateless and does **not** require Flink.

## Decision

Adopt **Kafka (Redpanda locally)** as the required event backbone. **Defer Flink** to an optional later phase (ROADMAP Phase 11). Add Flink **only** if we implement a genuine windowed/stateful job — the natural candidate is **rolling realized-volatility → Initial Margin**, or CEP for "N consecutive drops in T minutes." Until then, a plain Kafka consumer (or Faust) handles per-tick evaluation.

Daily/reference data is loaded by a scheduled **batch** job (EventBridge → Lambda), not the stream.

## Rationale

- Adding Flink without a real windowed computation is résumé-driven over-engineering and adds heavy ops burden.
- Kafka alone gives a legitimate, right-sized event-driven architecture.
- Keeping Flink optional means we always have a working system; Flink becomes a deliberate value-add.

## Consequences

- Core lifecycle works on Kafka + consumer.
- If Phase 11 is done, Flink earns its place honestly via a real stateful job.
- Using streaming for daily-only data is explicitly disallowed.
