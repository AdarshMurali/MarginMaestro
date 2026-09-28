import base64
import json
from unittest.mock import MagicMock

import pytest
from cloudevents.http import CloudEvent
from pydantic import ValidationError

from ops import billing_killswitch
from ops.billing_killswitch import (
    BudgetNotification,
    handle_budget_alert,
    parse_notification,
    run_killswitch,
    should_disable_billing,
)


def _encode(payload: dict) -> str:
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def _payload(cost: float, budget: float = 4200.0) -> dict:
    # Shape of Cloud Billing's budget notification (schemaVersion 1.0).
    return {
        "budgetDisplayName": "marginmaestro-demo trial kill-switch",
        "alertThresholdExceeded": 0.8,
        "costAmount": cost,
        "costIntervalStart": "2026-09-28T00:00:00Z",
        "budgetAmount": budget,
        "budgetAmountType": "SPECIFIED_AMOUNT",
        "currencyCode": "INR",
    }


def _notification(cost: float, budget: float = 4200.0) -> BudgetNotification:
    return BudgetNotification.model_validate(_payload(cost, budget))


def test_parse_notification_reads_budget_fields():
    notification = parse_notification(_encode(_payload(1234.5)))

    assert notification.cost_amount == 1234.5
    assert notification.budget_amount == 4200.0
    assert notification.currency_code == "INR"


def test_parse_notification_fails_loud_on_missing_cost():
    payload = _payload(10.0)
    del payload["costAmount"]

    with pytest.raises(ValidationError):
        parse_notification(_encode(payload))


def test_parse_notification_fails_loud_on_non_json():
    with pytest.raises(json.JSONDecodeError):
        parse_notification(base64.b64encode(b"not json").decode("ascii"))


@pytest.mark.parametrize(
    ("cost", "expected"),
    [(0.0, False), (4199.99, False), (4200.0, True), (5000.0, True)],
)
def test_should_disable_billing_trips_at_budget_amount(cost, expected):
    assert should_disable_billing(_notification(cost)) is expected


def test_below_budget_takes_no_action():
    client = MagicMock()

    action = run_killswitch(_notification(100.0), "marginmaestro-demo", False, client)

    assert action == "none"
    client.update_project_billing_info.assert_not_called()


def test_dry_run_never_unlinks_billing():
    client = MagicMock()

    action = run_killswitch(_notification(4200.0), "marginmaestro-demo", True, client)

    assert action == "dry_run"
    client.update_project_billing_info.assert_not_called()


def test_budget_reached_unlinks_billing():
    client = MagicMock()

    action = run_killswitch(_notification(4300.0), "marginmaestro-demo", False, client)

    assert action == "disabled"
    client.update_project_billing_info.assert_called_once()
    kwargs = client.update_project_billing_info.call_args.kwargs
    assert kwargs["name"] == "projects/marginmaestro-demo"
    assert kwargs["project_billing_info"].billing_account_name == ""


def test_unlink_failure_propagates_so_pubsub_retries():
    client = MagicMock()
    client.update_project_billing_info.side_effect = PermissionError("denied")

    with pytest.raises(PermissionError):
        run_killswitch(_notification(4300.0), "marginmaestro-demo", False, client)


def _cloud_event(cost: float) -> CloudEvent:
    attributes = {
        "type": "google.cloud.pubsub.topic.v1.messagePublished",
        "source": "//pubsub.googleapis.com/projects/marginmaestro-demo/topics/billing-alerts",
    }
    return CloudEvent(attributes, {"message": {"data": _encode(_payload(cost))}})


@pytest.mark.parametrize(
    ("dry_run_env", "expect_unlink"),
    [(None, False), ("true", False), ("TRUE", False), ("false", True)],
)
def test_handler_reads_env_and_defaults_to_dry_run(monkeypatch, dry_run_env, expect_unlink):
    client = MagicMock()
    monkeypatch.setattr(billing_killswitch.billing_v1, "CloudBillingClient", lambda: client)
    monkeypatch.setenv("PROJECT_ID", "marginmaestro-demo")
    if dry_run_env is None:
        monkeypatch.delenv("DRY_RUN", raising=False)
    else:
        monkeypatch.setenv("DRY_RUN", dry_run_env)

    handle_budget_alert(_cloud_event(5000.0))

    assert client.update_project_billing_info.called is expect_unlink


def test_handler_requires_project_id(monkeypatch):
    monkeypatch.delenv("PROJECT_ID", raising=False)

    with pytest.raises(KeyError):
        handle_budget_alert(_cloud_event(5000.0))
