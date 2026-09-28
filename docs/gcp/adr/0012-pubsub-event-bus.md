# ADR-0012: Use Pub/Sub as the event bus in the deployed environment

- **Status:** Accepted
- **Date:** 2026-09-28
- **Amends:** ADR-0003 (Kafka/Redpanda stays for local dev and as fallback; Flink remains deferred)

## Context

Kafka/Redpanda was never deployed (Phase 10 kept it local-only because it needed an always-on broker). Pub/Sub is serverless, scales to zero, and has a 10 GB/month free tier.

## Decision

- Topics: `market-events`, `margin-call-events`, `notifications`, `audit-events`, plus a dead-letter topic per subscription.
- **Ordering keys** per `counterparty_id`, so events for one counterparty are processed in order.
- **Push subscriptions** to Cloud Run endpoints (Event Agent, notifier) — no always-on consumer process.
- **At-least-once delivery** is accepted: the existing idempotency key (event id + counterparty id) already prevents double-raising a call. Dead-letter after 5 attempts.
- **BigQuery subscriptions** on `margin-call-events` and `audit-events` stream straight into BigQuery with no code (ADR-0013).
- Replay uses Pub/Sub **seek** to a snapshot or timestamp instead of Kafka offset resets.
- Code talks to an `EventBus` interface with `pubsub` and `kafka` adapters (`EVENT_BUS=pubsub|kafka`).

## Consequences

- `src/streaming/producer.py` / `consumer.py` refactored behind the `EventBus` interface.
- Local dev: Pub/Sub emulator (or Redpanda via the kafka adapter).
- This also unblocks the live-feed poller in the deployed env: it becomes a Cloud Scheduler job publishing to `market-events` instead of a 60-second always-on loop.
