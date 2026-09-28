"""Billing kill-switch for the GCP trial (MM-98, ADR-0017).

Cloud Billing publishes a budget notification to Pub/Sub every ~20-30 minutes.
When the budget's cost reaches its amount, this function unlinks the project's
billing account, which stops every paid service. The budget itself is set to
the kill threshold (e.g. INR 4,200 ~ USD 50) and counts usage before credits,
so ``costAmount >= budgetAmount`` is the trip condition.

Deployed as a Cloud Run function: Terraform packages this file as ``main.py``
with entry point ``handle_budget_alert``. It must stay self-contained -- no
imports from the rest of ``src/``.

Environment:
    PROJECT_ID  project whose billing gets unlinked (required)
    DRY_RUN     "true" (default) logs the decision without unlinking billing
"""

import base64
import json
import os
from typing import Any, Protocol

import functions_framework
from cloudevents.http import CloudEvent
from google.cloud import billing_v1
from pydantic import BaseModel, ConfigDict, Field


class BudgetNotification(BaseModel):
    """The fields we act on from Cloud Billing's budget notification payload."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")

    budget_display_name: str = Field(alias="budgetDisplayName")
    cost_amount: float = Field(alias="costAmount")
    budget_amount: float = Field(alias="budgetAmount")
    currency_code: str = Field(alias="currencyCode")


class BillingClient(Protocol):
    def update_project_billing_info(
        self, *, name: str, project_billing_info: billing_v1.ProjectBillingInfo
    ) -> Any: ...


def parse_notification(message_data_b64: str) -> BudgetNotification:
    """Decode a Pub/Sub message body. Fails loud on malformed payloads."""
    payload = json.loads(base64.b64decode(message_data_b64).decode("utf-8"))
    return BudgetNotification.model_validate(payload)


def should_disable_billing(notification: BudgetNotification) -> bool:
    return notification.cost_amount >= notification.budget_amount


def _log(severity: str, message: str, **fields: Any) -> None:
    # One JSON object per line: Cloud Logging parses `severity` and keeps the
    # rest as structured jsonPayload fields.
    print(json.dumps({"severity": severity, "message": message, **fields}))


def run_killswitch(
    notification: BudgetNotification,
    project_id: str,
    dry_run: bool,
    client: BillingClient,
) -> str:
    """Apply the kill-switch decision. Returns the action taken, for logs and tests."""
    context = {
        "budget": notification.budget_display_name,
        "cost": notification.cost_amount,
        "budget_amount": notification.budget_amount,
        "currency": notification.currency_code,
        "project_id": project_id,
    }

    if not should_disable_billing(notification):
        _log("INFO", "Spend within budget; no action", action="none", **context)
        return "none"

    if dry_run:
        _log(
            "CRITICAL",
            "Budget reached; billing NOT unlinked (dry run)",
            action="dry_run",
            **context,
        )
        return "dry_run"

    # An empty billing account name unlinks billing from the project.
    client.update_project_billing_info(
        name=f"projects/{project_id}",
        project_billing_info=billing_v1.ProjectBillingInfo(billing_account_name=""),
    )
    _log("CRITICAL", "Budget reached; billing unlinked from project", action="disabled", **context)
    return "disabled"


@functions_framework.cloud_event
def handle_budget_alert(cloud_event: CloudEvent) -> None:
    project_id = os.environ["PROJECT_ID"]
    dry_run = os.environ.get("DRY_RUN", "true").lower() != "false"
    notification = parse_notification(cloud_event.data["message"]["data"])
    run_killswitch(notification, project_id, dry_run, billing_v1.CloudBillingClient())
