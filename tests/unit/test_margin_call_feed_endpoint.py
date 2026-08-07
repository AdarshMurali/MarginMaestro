from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api.main import app
from api.schemas import MarginCallBucketFeedResponse, MarginCallFeedResponse

client = TestClient(app)


class TestMarginCallFeedEndpoint:
    def test_returns_the_feed_from_list_margin_calls(self) -> None:
        canned = MarginCallFeedResponse(as_of=datetime(2026, 1, 1, tzinfo=UTC), margin_calls=[])
        session_factory = MagicMock()
        session_factory.return_value.__enter__.return_value = MagicMock()
        with (
            patch("api.main.get_db_session_factory", return_value=session_factory),
            patch("api.main.get_orchestrator_graph", return_value=MagicMock()),
            patch("api.main.list_margin_calls", return_value=canned) as mock_list,
        ):
            response = client.get("/margin-calls")

        assert response.status_code == 200
        assert response.json()["margin_calls"] == []
        mock_list.assert_called_once()


class TestMarginCallBucketsEndpoint:
    def test_returns_the_buckets_from_list_margin_call_buckets(self) -> None:
        canned = MarginCallBucketFeedResponse(as_of=datetime(2026, 1, 1, tzinfo=UTC), buckets=[])
        session_factory = MagicMock()
        session_factory.return_value.__enter__.return_value = MagicMock()
        with (
            patch("api.main.get_db_session_factory", return_value=session_factory),
            patch("api.main.get_orchestrator_graph", return_value=MagicMock()),
            patch("api.main.list_margin_call_buckets", return_value=canned) as mock_list,
        ):
            response = client.get("/margin-calls/buckets")

        assert response.status_code == 200
        assert response.json()["buckets"] == []
        mock_list.assert_called_once()


class TestMarginCallsForCounterpartyEndpoint:
    def test_returns_the_feed_from_list_margin_calls_for_counterparty(self) -> None:
        canned = MarginCallFeedResponse(as_of=datetime(2026, 1, 1, tzinfo=UTC), margin_calls=[])
        session_factory = MagicMock()
        session_factory.return_value.__enter__.return_value = MagicMock()
        graph = MagicMock()
        with (
            patch("api.main.get_db_session_factory", return_value=session_factory),
            patch("api.main.get_orchestrator_graph", return_value=graph),
            patch("api.main.list_margin_calls_for_counterparty", return_value=canned) as mock_list,
        ):
            response = client.get("/margin-calls/counterparty/CP-1")

        assert response.status_code == 200
        assert response.json()["margin_calls"] == []
        mock_list.assert_called_once_with(
            graph, session_factory.return_value.__enter__.return_value, "CP-1"
        )
