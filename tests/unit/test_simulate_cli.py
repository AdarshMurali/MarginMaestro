from unittest.mock import patch

from streaming.schemas import MarketEventType
from streaming.simulate_cli import main


def test_parses_scenario_and_runs_it() -> None:
    with (
        patch("streaming.simulate_cli.run_scenario") as mock_run,
        patch("sys.argv", ["simulate_cli", "--scenario", "price_shock"]),
    ):
        main()

    mock_run.assert_called_once_with(MarketEventType.PRICE_SHOCK)
