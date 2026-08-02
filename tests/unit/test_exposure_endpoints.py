from datetime import UTC, date, datetime
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from api.main import app
from api.schemas import ExposureBoardResponse, PriceHistoryResponse, PricePoint
from streaming.market_feed import MarketDataUnavailableError

client = TestClient(app)


class TestExposureBoard:
    def test_returns_the_board_from_build_exposure_board(self) -> None:
        canned = ExposureBoardResponse(as_of=datetime(2026, 1, 1, tzinfo=UTC), counterparties=[])
        session_factory = MagicMock()
        session_factory.return_value.__enter__.return_value = MagicMock()
        with (
            patch("api.main.get_db_session_factory", return_value=session_factory),
            patch("api.main.get_market_feed", return_value=MagicMock()),
            patch("api.main.build_exposure_board", return_value=canned) as mock_build,
        ):
            response = client.get("/exposure")

        assert response.status_code == 200
        assert response.json()["counterparties"] == []
        mock_build.assert_called_once()


class TestPriceHistoryEndpoint:
    def test_returns_history_from_get_price_history(self) -> None:
        canned = PriceHistoryResponse(
            ticker="AAPL", points=[PricePoint(date=date(2026, 1, 1), price=200.0)]
        )
        with patch("api.main.get_price_history", return_value=canned) as mock_get:
            response = client.get("/prices/AAPL/history?days=10")

        assert response.status_code == 200
        assert response.json()["ticker"] == "AAPL"
        mock_get.assert_called_once_with("AAPL", days=10)

    def test_unavailable_ticker_returns_404(self) -> None:
        with patch(
            "api.main.get_price_history", side_effect=MarketDataUnavailableError("BADTICKER")
        ):
            response = client.get("/prices/BADTICKER/history")

        assert response.status_code == 404
