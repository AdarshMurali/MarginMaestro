from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import httpx
import pytest

from agents.escalation import (
    EscalationUnavailableError,
    ServiceNowError,
    open_servicenow_incident,
    retrieve_escalation_procedure,
)
from config.settings import Settings
from rag.retriever import RetrievedChunk

SAMPLE_CHUNKS = [
    RetrievedChunk(
        text="A margin call is escalated once the SLA timer elapses.",
        source_file="escalation/escalation_procedures.md",
        doc_type="escalation",
        counterparty_id="",
        effective_date="2026-08-01",
        section="Escalation Trigger",
        distance=0.1,
    )
]


class TestRetrieveEscalationProcedure:
    def test_scopes_retrieval_to_the_escalation_doc_type(self) -> None:
        with patch("agents.escalation.retrieve", return_value=SAMPLE_CHUNKS) as mock_retrieve:
            retrieve_escalation_procedure()

        _, kwargs = mock_retrieve.call_args
        assert kwargs["doc_type"] == "escalation"

    def test_formats_chunks_with_section_headers(self) -> None:
        with patch("agents.escalation.retrieve", return_value=SAMPLE_CHUNKS):
            result = retrieve_escalation_procedure()

        assert "[Escalation Trigger]" in result
        assert "A margin call is escalated once the SLA timer elapses." in result

    def test_no_chunks_raises(self) -> None:
        with (
            patch("agents.escalation.retrieve", return_value=[]),
            pytest.raises(EscalationUnavailableError),
        ):
            retrieve_escalation_procedure()


def _configured_settings() -> Settings:
    return Settings(
        _env_file=None,
        servicenow_instance_url="https://dev12345.service-now.com",
        servicenow_username="admin",
        servicenow_password="secret",
    )


class TestOpenServiceNowIncident:
    def _mock_http_client(self, number: str = "INC0010001", sys_id: str = "abc123") -> MagicMock:
        client = MagicMock()
        response = MagicMock()
        response.json.return_value = {"result": {"number": number, "sys_id": sys_id}}
        client.post.return_value = response
        return client

    def test_posts_to_the_table_api_with_full_context(self) -> None:
        client = self._mock_http_client()

        open_servicenow_incident(
            "corr-1",
            "CP-1",
            474_000.0,
            "USD",
            100_000.0,
            datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
            datetime(2026, 8, 1, 13, 0, tzinfo=UTC),
            "[Escalation Trigger]\nmock procedure",
            settings=_configured_settings(),
            http_client=client,
        )

        args, kwargs = client.post.call_args
        assert args[0] == "/api/now/table/incident"
        body = kwargs["json"]
        assert "CP-1" in body["short_description"]
        assert "corr-1" in body["description"]
        assert "474,000.00 USD" in body["description"]
        assert "mock procedure" in body["description"]

    def test_high_urgency_past_5x_threshold(self) -> None:
        client = self._mock_http_client()

        open_servicenow_incident(
            "corr-1",
            "CP-1",
            600_000.0,
            "USD",
            100_000.0,
            datetime.now(UTC),
            datetime.now(UTC),
            "procedure",
            settings=_configured_settings(),
            http_client=client,
        )

        assert client.post.call_args.kwargs["json"]["urgency"] == "1"

    def test_moderate_urgency_within_5x_threshold(self) -> None:
        client = self._mock_http_client()

        open_servicenow_incident(
            "corr-1",
            "CP-1",
            300_000.0,
            "USD",
            100_000.0,
            datetime.now(UTC),
            datetime.now(UTC),
            "procedure",
            settings=_configured_settings(),
            http_client=client,
        )

        assert client.post.call_args.kwargs["json"]["urgency"] == "2"

    def test_returns_incident_number_and_sys_id(self) -> None:
        client = self._mock_http_client(number="INC0010042", sys_id="xyz789")

        result = open_servicenow_incident(
            "corr-1",
            "CP-1",
            474_000.0,
            "USD",
            100_000.0,
            datetime.now(UTC),
            datetime.now(UTC),
            "procedure",
            settings=_configured_settings(),
            http_client=client,
        )

        assert result.incident_number == "INC0010042"
        assert result.sys_id == "xyz789"

    def test_raises_when_not_configured(self) -> None:
        with pytest.raises(ServiceNowError):
            open_servicenow_incident(
                "corr-1",
                "CP-1",
                474_000.0,
                "USD",
                100_000.0,
                datetime.now(UTC),
                datetime.now(UTC),
                "procedure",
                settings=Settings(_env_file=None),
                http_client=MagicMock(),
            )

    def test_raises_on_http_error(self) -> None:
        client = MagicMock()
        client.post.side_effect = httpx.HTTPError("boom")

        with pytest.raises(ServiceNowError):
            open_servicenow_incident(
                "corr-1",
                "CP-1",
                474_000.0,
                "USD",
                100_000.0,
                datetime.now(UTC),
                datetime.now(UTC),
                "procedure",
                settings=_configured_settings(),
                http_client=client,
            )
