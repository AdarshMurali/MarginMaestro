"""Picks the guardrail from Settings (MM-113/114). Kept apart from
adapters.factory so code that ships without the rest of the app -- the desk
assistant on Agent Runtime (MM-129) -- can screen text without importing the
OpenAI, Chroma or Kafka adapters."""

from adapters.selection import choose
from config.settings import Settings
from ports.guardrail import Guardrail


def get_guardrail(settings: Settings) -> Guardrail:
    choice = choose(
        "GUARDRAIL_PROVIDER", settings.guardrail_provider, ("incode", "modelarmor", "none")
    )
    if choice == "modelarmor":
        from adapters.model_armor_guardrail import ModelArmorGuardrail, model_armor_client

        if not settings.gcp_project_id:
            raise ValueError("GUARDRAIL_PROVIDER=modelarmor requires GCP_PROJECT_ID")
        template = (
            f"projects/{settings.gcp_project_id}/locations/{settings.model_armor_location}"
            f"/templates/{settings.model_armor_template_id}"
        )
        from adapters.composite_guardrail import CompositeGuardrail
        from adapters.incode_guardrail import InCodeGuardrail

        # Defence in depth: Model Armor plus the in-code checks; either blocks.
        return CompositeGuardrail(
            [
                ModelArmorGuardrail(template, model_armor_client(settings.model_armor_location)),
                InCodeGuardrail(),
            ]
        )
    from adapters.incode_guardrail import InCodeGuardrail, NoGuardrail

    return NoGuardrail() if choice == "none" else InCodeGuardrail()
