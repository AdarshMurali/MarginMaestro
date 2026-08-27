"""Curated two-counterparty demo (MM-100): triggers real, hand-verified
breach scenarios for one standard-tier and one elite-tier counterparty and
walks each through its full lifecycle -- approval (plus a second sign-off
for the elite one) -> notification -> SLA met -- entirely through the real
API, the same endpoints proven live throughout Phase 9.5's testing. Not a
Kafka/Event-Agent demo (see docs/ROADMAP.md's MM-100 note): this hits
/simulate the same way the frontend's Simulate Event panel does, so it
runs in well under a minute with no separate consumer process required.

Run via `make demo` (defaults to the local backend); pass --base-url to
point at a deployed instance once Phase 10's AWS backend is live.
"""

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import httpx
import jwt

from api.auth import JWT_ALGORITHM
from config.settings import Settings, get_settings


# Both scenarios were hand-verified live against real market data, most
# recently 2026-08-27 (re-tuned against the deployed instance -- CP-6's
# original +7.0% no longer breached after real ETH-USD/collateral drift
# since Phase 9.5's original calibration; see docs/PROGRESS.md's 2026-08-27
# entry). Exact figures drift day to day with real prices -- re-verify with
# GET /simulate against a real deployment before assuming these still
# breach. CP-6's ETH-USD shock also currently breaches CP-3 as a side
# effect (CP-3 sits close to its own threshold independent of this
# scenario) -- accepted, not chased away, since the demo only acts on its
# own two target counterparties' threads.
@dataclass(frozen=True)
class DemoScenario:
    counterparty_id: str
    ticker: str
    pct_change: float
    tier: str
    narrative: str


SCENARIOS = [
    DemoScenario(
        counterparty_id="CP-6",
        ticker="ETH-USD",
        pct_change=15.0,
        tier="standard",
        narrative="A crypto rally pushes CP-6 over its CSA threshold.",
    ),
    DemoScenario(
        counterparty_id="CP-5",
        ticker="MU",
        pct_change=25.0,
        tier="elite",
        narrative="A large move in CP-5's dominant MU position triggers a breach "
        "requiring two-person sign-off.",
    ),
]


def _token(settings: Settings, role: str, sub: str) -> str:
    if not settings.auth_backend_secret:
        raise RuntimeError("AUTH_BACKEND_SECRET is not configured")
    payload = {"sub": sub, "role": role, "exp": datetime.now(UTC) + timedelta(minutes=15)}
    return jwt.encode(payload, settings.auth_backend_secret, algorithm=JWT_ALGORITHM)


def _auth_header(settings: Settings, role: str, sub: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(settings, role, sub)}"}


def run_scenario(client: httpx.Client, settings: Settings, scenario: DemoScenario) -> dict:
    """Runs one scenario end to end, returning a plain summary dict for the
    caller to print/report -- kept free of any print()s itself so it stays
    easily unit-testable against a mocked client."""
    approver_headers = _auth_header(settings, "approver", "demo-approver")

    sim = client.post(
        "/simulate",
        json={
            "event_type": "price_shock",
            "ticker": scenario.ticker,
            "pct_change": scenario.pct_change,
        },
        headers=approver_headers,
    )
    sim.raise_for_status()
    result = next(
        r
        for r in sim.json()["affected_counterparties"]
        if r["counterparty_id"] == scenario.counterparty_id
    )
    if not result["breached"]:
        raise RuntimeError(
            f"{scenario.counterparty_id} did not breach on {scenario.ticker} "
            f"{scenario.pct_change:+.1f}% -- scenario needs re-tuning against current market data"
        )
    thread_id = result["thread_id"]
    call_amount = result["call_amount"]

    approve = client.post(
        f"/margin-calls/{thread_id}/approve",
        json={"decision": "approved"},
        headers=approver_headers,
    )
    approve.raise_for_status()

    if scenario.tier == "elite":
        manager_headers = _auth_header(settings, "manager", "demo-manager")
        manager_approve = client.post(
            f"/margin-calls/{thread_id}/manager-approve",
            json={"decision": "approved"},
            headers=manager_headers,
        )
        manager_approve.raise_for_status()

    respond = client.post(f"/margin-calls/{thread_id}/respond", headers=approver_headers)
    respond.raise_for_status()

    return {
        "counterparty_id": scenario.counterparty_id,
        "tier": scenario.tier,
        "narrative": scenario.narrative,
        "thread_id": thread_id,
        "call_amount": call_amount,
        "sla_outcome": respond.json()["sla_outcome"],
    }


def run_demo(settings: Settings, base_url: str) -> list[dict]:
    # A fixed domain allowlist (SonarCloud python:S8703's default suggested
    # fix) doesn't fit here -- this CLI's whole purpose is pointing at
    # whichever backend the caller names (local dev, a deployed instance),
    # not a closed set of trusted hosts. Validating the shape of the URL
    # instead still addresses the real concern (an LLM/agent invoking this
    # with a malformed or unintended -- e.g. non-http(s) -- argument ending
    # up as a real network target) without breaking that flexibility.
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"base_url must be an absolute http(s) URL, got {base_url!r}")

    with httpx.Client(base_url=base_url, timeout=90.0) as client:
        return [run_scenario(client, settings, scenario) for scenario in SCENARIOS]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run MarginMaestro's curated two-counterparty demo scenario."
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Backend base URL (default: http://localhost:<API_PORT>)",
    )
    args = parser.parse_args()

    settings = get_settings()
    base_url = args.base_url or f"http://localhost:{settings.api_port}"

    print(f"Running curated demo against {base_url} ...\n")
    for result in run_demo(settings, base_url):
        print(
            f"{result['counterparty_id']} ({result['tier']} tier): {result['narrative']}\n"
            f"  thread_id:   {result['thread_id']}\n"
            f"  call_amount: {result['call_amount']:,.2f}\n"
            f"  sla_outcome: {result['sla_outcome']}\n"
        )


if __name__ == "__main__":
    main()
