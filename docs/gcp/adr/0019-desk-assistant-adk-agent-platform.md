# ADR-0019: The desk assistant runs on Agent Platform, built with Google ADK

- **Status:** Accepted
- **Date:** 2026-10-04 (user decisions; stories MM-128 … MM-132)

## Context

Phase G5 planned to move the LangGraph margin-call orchestrator to Vertex AI Agent Engine (now Agent Runtime). A pricing and fit check found:

- **Cost.** Agent Runtime costs $0.085/vCPU-h and $0.009/GiB-h, with 50 vCPU-h and 100 GiB-h free each month. `min_instances` defaults to 1 (a warm instance) but may be 0. The user's rule: no warm instance, a cold start is acceptable, stay as close to $0 as possible.
- **Fit.** The orchestrator is a fixed pipeline. It calls its tools as in-process functions, holds no conversation and lets no LLM choose a tool. Moving it would add a network hop, a second deployment and a cold start to every approval, and gain nothing. That would be a forced fit.
- **Hackathon goal.** Use Google Cloud's agent services where each one is genuinely needed.

## Decision

1. **The orchestrator stays LangGraph on Cloud Run** (ADR-0002 unchanged).
2. **A new conversational agent, the "Ask the margin desk" assistant, runs on Agent Platform.** Each feature solves a need the orchestrator doesn't have:

   | Need | Agent Platform feature |
   |---|---|
   | Multi-turn chat that survives scale-to-zero | Agent Runtime + **Sessions** |
   | Memory per analyst and per counterparty | **Memory Bank** (MM-130) |
   | An audit trail of the agent's own tool calls | **Agent Identity** (MM-131): *off, see the 2026-10-05 amendment* |
   | Checking that tool choice and grounding stay correct | **Gen AI evaluation** (MM-132) |

3. **The assistant is built with Google ADK** (`google-adk` 2.11.0). ADK has built-in MCP toolsets with per-call headers, Sessions and Memory Bank services, and the `AdkApp` wrapper Agent Runtime deploys. All Agent Identity documentation is written for it.
4. **Tools are the read-only MCP servers on Cloud Run** (MM-128), one service each. Cloud Run IAM makes the agent's identity the only invoker. The analyst travels as `X-MM-User`, set from the session's `user_id`, which only our API sets after its own JWT check. The MCP services read the role and scope from the database and apply row-level security. No MCP service can write or notify.
5. **Deployment settings:** deployed from source (no pickling, no staging bucket); `min_instances=0`, `max_instances=2`, 1 vCPU / 2 GiB; run as `mm-agent-sa` until Agent Identity (MM-131). Guardrails (Model Armor + in-code, ADR-0014) screen each analyst message before the model sees it, and each answer before the analyst does, failing closed.
6. **Agent Gateway is not used.** It uses alpha APIs, needs organization-level IAM (this project has no organization) and a VPC + Cloud NAT + PSC (about $30/month). Native Cloud Run IAM gives the same deny-by-default tool access at $0.

## Consequences

- There are two agent frameworks. LangGraph handles the deterministic workflow, ADK the conversational agent; each is used where it fits.
- The API calls Agent Runtime over REST (`:query`, `:streamQuery`), so the app image needs no ADK/Vertex SDK. The agent ships only the packages it imports (`desk_assistant`, `config`, `ports`, the guardrail adapters); a unit test fails if it starts importing anything else.
- A source deploy has to pass the class-method specs itself, so it uses a private helper of the pinned `google-cloud-aiplatform` (1.x). Re-check this on SDK upgrades.
- Cost: about $0 idle; per-turn Gemini tokens and Model Armor calls cost fractions of a cent. A billing check is due 24 hours after the first deploy (user rule).
- Post-trial fallback (ADR-0017): turn chat off (`DESK_ASSISTANT=none`). The rest of the app doesn't depend on it.

## Amendment (2026-10-05): Agent Identity is off; the agent runs as `mm-agent-sa`

The MM-131 cutover switched the deployed agent to `identity_type=AGENT_IDENTITY`. **Every chat turn then failed:** Model Armor answered `401 … Expected OAuth 2 access token`, and the agent was rolled back to `mm-agent-sa` about 3 minutes later.

- **Cause.** Agent Identity issues **certificate-bound** tokens that Google APIs accept only over mTLS. Client libraries switch to mTLS endpoints only when `GOOGLE_API_USE_CLIENT_CERTIFICATE=true` and an mTLS endpoint exists. Model Armor has a global mTLS endpoint, but **no regional one** (`modelarmor.us-central1.rep.mtls.googleapis.com` doesn't resolve), and our template is regional.
- **Decision:** keep Model Armor and run the agent as `mm-agent-sa`. Screening every turn matters more than per-agent attribution.
  - Per-tool IAM still holds: `mm-agent-sa` is the only invoker of the MCP services, and the Slack/ServiceNow notifiers have no network service.
  - `deploy.py` pins the service account. Terraform keeps the Agent Identity grants behind `desk_agent_identity` (default false) for a later retry, which would need a regional mTLS endpoint or a global Model Armor template.
- **Also fixed:** the Model Armor adapter turned the 401 into an unhandled error. API errors now raise `GuardrailUnavailable`, so a screening outage gives a refusal (fail closed) instead of a crashed turn.
