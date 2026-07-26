from datetime import date

import pandas as pd
from fredapi import Fred
from pydantic import BaseModel

from config.settings import Settings, get_settings

# Curated series covering the "rates/yields/VIX/macro" reference data this
# project's IM/haircut calcs will need (docs/DATA_SOURCES.md). The Treasury
# yields map onto the Treasury ETFs already in the securities universe:
# SHY (1-3yr) -> DGS2, IEF (7-10yr) -> DGS10, TLT (20yr+) -> DGS30.
REFERENCE_SERIES = {"SOFR", "DGS2", "DGS10", "DGS30", "VIXCLS"}


class RateObservation(BaseModel):
    series_id: str
    date: date
    value: float


class RateDataUnavailableError(Exception):
    """Raised when a FRED series can't be fetched or has no data in range."""


class FredFeed:
    """Rates/yields/VIX/macro reference data via the free FRED API."""

    def __init__(self, settings: Settings | None = None, client: Fred | None = None) -> None:
        settings = settings or get_settings()
        if client is not None:
            self._client = client
        elif settings.fred_api_key:
            self._client = Fred(api_key=settings.fred_api_key)
        else:
            raise RateDataUnavailableError("FRED_API_KEY is not configured")

    def get_series(
        self, series_id: str, start: date | None = None, end: date | None = None
    ) -> list[RateObservation]:
        try:
            series = self._client.get_series(
                series_id, observation_start=start, observation_end=end
            )
        except Exception as exc:
            raise RateDataUnavailableError(f"FRED series '{series_id}' failed: {exc}") from exc

        observations = [
            RateObservation(series_id=series_id, date=ts.date(), value=float(value))
            for ts, value in series.items()
            if pd.notna(value)
        ]
        if not observations:
            raise RateDataUnavailableError(f"FRED series '{series_id}' returned no data")
        return observations

    def get_latest(self, series_id: str) -> RateObservation:
        return self.get_series(series_id)[-1]
