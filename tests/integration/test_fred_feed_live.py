"""Real calls against the FRED API using the user-supplied FRED_API_KEY.
Excluded from the default/CI test run (see the `live` marker in
pyproject.toml) -- run explicitly with: pytest -m live tests/integration/test_fred_feed_live.py
"""

import pytest

from persistence.fred_feed import REFERENCE_SERIES, FredFeed

pytestmark = pytest.mark.live


def test_fetches_latest_value_for_every_reference_series() -> None:
    feed = FredFeed()

    for series_id in REFERENCE_SERIES:
        observation = feed.get_latest(series_id)
        assert observation.series_id == series_id
        assert observation.value > 0
