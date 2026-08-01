"""Real RAG retrieval + real ServiceNow calls. Excluded from the default/CI
test run (see the `live` marker in pyproject.toml) since they depend on real
external services and create a real incident in the configured ServiceNow
instance.

Run explicitly with: pytest -m live tests/integration/test_escalation_live.py
"""

from datetime import UTC, datetime, timedelta

import pytest

from agents.escalation import open_servicenow_incident, retrieve_escalation_procedure
from config.settings import get_settings

pytestmark = pytest.mark.live


def test_retrieves_the_real_escalation_procedure_and_opens_a_real_incident() -> None:
    settings = get_settings()

    procedure = retrieve_escalation_procedure(settings=settings)
    assert "escalat" in procedure.lower()

    now = datetime.now(UTC)
    result = open_servicenow_incident(
        "live-test-corr-1",
        "CP-TEST",
        474_000.0,
        "USD",
        100_000.0,
        now - timedelta(hours=1),
        now,
        procedure,
        settings=settings,
    )

    assert result.incident_number.startswith("INC")
    assert result.sys_id
