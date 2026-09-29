"""Interfaces (ports) for external dependencies that have more than one
implementation during the AWS -> GCP migration (MM-102, ADR-0017).

Only dependencies with a real second implementation get a port -- OpenAI vs
Gemini, Chroma vs pgvector, Kafka vs Pub/Sub, Slack vs WhatsApp. Single-vendor
calls (Model Armor, BigQuery, ...) call their API directly.
Adapters live in `src/adapters/`; `adapters.factory` picks one per env flag.
"""
