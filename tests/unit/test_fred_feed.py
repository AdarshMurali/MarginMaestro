from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest

from config.settings import Settings
from persistence.fred_feed import FredFeed, RateDataUnavailableError


def _fake_client(series: pd.Series) -> object:
    class FakeFred:
        def get_series(self, series_id, observation_start=None, observation_end=None):
            return series

    return FakeFred()


class TestFredFeed:
    def test_get_series_returns_observations(self) -> None:
        series = pd.Series(
            {pd.Timestamp("2026-07-24"): 4.25, pd.Timestamp("2026-07-25"): 4.3},
        )
        feed = FredFeed(client=_fake_client(series))

        result = feed.get_series("SOFR")

        assert result[0].series_id == "SOFR"
        assert result[0].date == date(2026, 7, 24)
        assert result[0].value == 4.25
        assert result[1].value == 4.3

    def test_get_latest_returns_last_observation(self) -> None:
        series = pd.Series(
            {pd.Timestamp("2026-07-24"): 4.25, pd.Timestamp("2026-07-25"): 4.3},
        )
        feed = FredFeed(client=_fake_client(series))

        latest = feed.get_latest("SOFR")

        assert latest.date == date(2026, 7, 25)
        assert latest.value == 4.3

    def test_drops_nan_observations(self) -> None:
        series = pd.Series(
            {pd.Timestamp("2026-07-24"): float("nan"), pd.Timestamp("2026-07-25"): 4.3},
        )
        feed = FredFeed(client=_fake_client(series))

        result = feed.get_series("SOFR")

        assert len(result) == 1
        assert result[0].value == 4.3

    def test_empty_series_raises(self) -> None:
        feed = FredFeed(client=_fake_client(pd.Series(dtype=float)))

        with pytest.raises(RateDataUnavailableError, match="SOFR"):
            feed.get_series("SOFR")

    def test_client_error_raises(self) -> None:
        class RaisingFred:
            def get_series(self, series_id, observation_start=None, observation_end=None):
                raise RuntimeError("boom")

        feed = FredFeed(client=RaisingFred())

        with pytest.raises(RateDataUnavailableError, match="boom"):
            feed.get_series("SOFR")

    def test_missing_api_key_raises(self) -> None:
        settings = Settings(_env_file=None, fred_api_key=None)

        with pytest.raises(RateDataUnavailableError, match="FRED_API_KEY"):
            FredFeed(settings=settings)

    def test_constructs_real_client_with_configured_key(self) -> None:
        settings = Settings(_env_file=None, fred_api_key="test-key")

        with patch("persistence.fred_feed.Fred") as mock_fred_cls:
            feed = FredFeed(settings=settings)

        mock_fred_cls.assert_called_once_with(api_key="test-key")
        assert feed._client is mock_fred_cls.return_value
