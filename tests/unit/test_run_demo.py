from unittest.mock import MagicMock, patch

import jwt
import pytest

from api.auth import JWT_ALGORITHM
from config.settings import Settings
from demo.run_demo import SCENARIOS, DemoScenario, _token, main, run_demo, run_scenario

TEST_SECRET = "test-demo-secret"


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, auth_backend_secret=TEST_SECRET)


def _response(json_body: dict) -> MagicMock:
    resp = MagicMock()
    resp.json.return_value = json_body
    resp.raise_for_status.return_value = None
    return resp


class TestToken:
    def test_encodes_role_and_subject(self, settings: Settings) -> None:
        token = _token(settings, "approver", "demo-approver")

        claims = jwt.decode(token, TEST_SECRET, algorithms=[JWT_ALGORITHM])

        assert claims["role"] == "approver"
        assert claims["sub"] == "demo-approver"

    def test_raises_when_secret_not_configured(self) -> None:
        with pytest.raises(RuntimeError, match="AUTH_BACKEND_SECRET"):
            _token(Settings(_env_file=None, auth_backend_secret=None), "approver", "x")


class TestRunScenario:
    def _standard_scenario(self) -> DemoScenario:
        return DemoScenario(
            counterparty_id="CP-6",
            ticker="ETH-USD",
            pct_change=7.0,
            tier="standard",
            narrative="test",
        )

    def _elite_scenario(self) -> DemoScenario:
        return DemoScenario(
            counterparty_id="CP-5", ticker="MU", pct_change=25.0, tier="elite", narrative="test"
        )

    def test_standard_tier_happy_path_skips_manager_approve(self, settings: Settings) -> None:
        client = MagicMock()
        client.post.side_effect = [
            _response(
                {
                    "affected_counterparties": [
                        {
                            "counterparty_id": "CP-6",
                            "thread_id": "evt-1:CP-6",
                            "breached": True,
                            "call_amount": 30_772.0,
                        }
                    ]
                }
            ),
            _response({"approval_decision": "approved"}),  # /approve
            _response({"sla_outcome": "met"}),  # /respond
        ]

        result = run_scenario(client, settings, self._standard_scenario())

        assert result == {
            "counterparty_id": "CP-6",
            "tier": "standard",
            "narrative": "test",
            "thread_id": "evt-1:CP-6",
            "call_amount": 30_772.0,
            "sla_outcome": "met",
        }
        called_paths = [call.args[0] for call in client.post.call_args_list]
        assert called_paths == [
            "/simulate",
            "/margin-calls/evt-1:CP-6/approve",
            "/margin-calls/evt-1:CP-6/respond",
        ]

    def test_elite_tier_also_calls_manager_approve(self, settings: Settings) -> None:
        client = MagicMock()
        client.post.side_effect = [
            _response(
                {
                    "affected_counterparties": [
                        {
                            "counterparty_id": "CP-5",
                            "thread_id": "evt-2:CP-5",
                            "breached": True,
                            "call_amount": 270_151.0,
                        }
                    ]
                }
            ),
            _response({"approval_decision": "approved"}),  # /approve
            _response(
                {"approval_decision": "approved", "manager_decision": "approved"}
            ),  # /manager-approve
            _response({"sla_outcome": "met"}),  # /respond
        ]

        result = run_scenario(client, settings, self._elite_scenario())

        assert result["sla_outcome"] == "met"
        called_paths = [call.args[0] for call in client.post.call_args_list]
        assert called_paths == [
            "/simulate",
            "/margin-calls/evt-2:CP-5/approve",
            "/margin-calls/evt-2:CP-5/manager-approve",
            "/margin-calls/evt-2:CP-5/respond",
        ]

    def test_raises_if_the_scenario_did_not_actually_breach(self, settings: Settings) -> None:
        client = MagicMock()
        client.post.return_value = _response(
            {
                "affected_counterparties": [
                    {
                        "counterparty_id": "CP-6",
                        "thread_id": "evt-3:CP-6",
                        "breached": False,
                        "call_amount": 0.0,
                    }
                ]
            }
        )

        with pytest.raises(RuntimeError, match="did not breach"):
            run_scenario(client, settings, self._standard_scenario())


class TestRunDemo:
    def test_runs_every_scenario_against_a_real_client(self, settings: Settings) -> None:
        fake_results = [{"counterparty_id": s.counterparty_id} for s in SCENARIOS]
        with patch("demo.run_demo.run_scenario", side_effect=fake_results) as mock_run:
            results = run_demo(settings, "http://localhost:8000")

        assert results == fake_results
        assert mock_run.call_count == len(SCENARIOS)


class TestMain:
    def test_parses_base_url_and_prints_results(self, capsys) -> None:
        fake_result = {
            "counterparty_id": "CP-6",
            "tier": "standard",
            "narrative": "test",
            "thread_id": "evt-1:CP-6",
            "call_amount": 1_000.0,
            "sla_outcome": "met",
        }
        with (
            patch("demo.run_demo.run_demo", return_value=[fake_result]) as mock_run_demo,
            patch("demo.run_demo.get_settings", return_value=Settings(_env_file=None)),
            patch("sys.argv", ["run_demo", "--base-url", "http://example.test"]),
        ):
            main()

        mock_run_demo.assert_called_once()
        assert mock_run_demo.call_args.args[1] == "http://example.test"
        assert "CP-6" in capsys.readouterr().out

    def test_defaults_base_url_to_localhost_with_api_port(self, capsys) -> None:
        with (
            patch("demo.run_demo.run_demo", return_value=[]) as mock_run_demo,
            patch(
                "demo.run_demo.get_settings",
                return_value=Settings(_env_file=None, api_port=9999),
            ),
            patch("sys.argv", ["run_demo"]),
        ):
            main()

        assert mock_run_demo.call_args.args[1] == "http://localhost:9999"
