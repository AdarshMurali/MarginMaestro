"""`Guardrail` over Google Cloud Model Armor (MM-114, ADR-0014) -- the
content-screening engine Agent Platform uses. Screens prompts with
SanitizeUserPrompt and model answers with SanitizeModelResponse against one
Terraform-managed template (prompt injection / jailbreak, malicious URLs,
responsible-AI filters). The same template is attached to Agent Gateway in G5.

Fail closed: anything short of a complete screening -- an API error, or an
invocation that only partly ran -- raises GuardrailUnavailable.
"""

from typing import Any

from ports.guardrail import GuardrailUnavailable, Stage, Verdict

MATCH_FOUND = "MATCH_FOUND"
SUCCESS = "SUCCESS"


def _name(enum_value: Any) -> str:
    return str(getattr(enum_value, "name", enum_value))


def _matched_filters(filter_results: Any) -> list[str]:
    """Names of the filters that matched, e.g. ['pi_and_jailbreak',
    'rai:dangerous']. Each FilterResult holds exactly one typed result."""
    reasons: list[str] = []
    for key, filter_result in filter_results.items():
        kind = type(filter_result).pb(filter_result).WhichOneof("filter_result")
        result = getattr(filter_result, kind) if kind else None
        if result is None or _name(result.match_state) != MATCH_FOUND:
            continue
        sub_results = getattr(result, "rai_filter_type_results", None)
        if sub_results:
            reasons.extend(
                f"{key}:{sub_key}"
                for sub_key, sub in sub_results.items()
                if _name(sub.match_state) == MATCH_FOUND
            )
        else:
            reasons.append(key)
    return reasons


class ModelArmorGuardrail:
    name = "modelarmor"

    def __init__(self, template: str, client: Any) -> None:
        # template: projects/<p>/locations/<loc>/templates/<id>
        self._template = template
        self._client = client

    def screen(self, text: str, stage: Stage) -> Verdict:
        from google.cloud import modelarmor_v1

        item = modelarmor_v1.DataItem(text=text)
        if stage == "prompt":
            response = self._client.sanitize_user_prompt(
                request=modelarmor_v1.SanitizeUserPromptRequest(
                    name=self._template, user_prompt_data=item
                )
            )
        else:
            response = self._client.sanitize_model_response(
                request=modelarmor_v1.SanitizeModelResponseRequest(
                    name=self._template, model_response_data=item
                )
            )
        result = response.sanitization_result
        if _name(result.invocation_result) != SUCCESS:
            raise GuardrailUnavailable(
                f"Model Armor screening incomplete ({_name(result.invocation_result)})"
            )
        if _name(result.filter_match_state) != MATCH_FOUND:
            return Verdict(allowed=True, guardrail=self.name)
        return Verdict(
            allowed=False,
            guardrail=self.name,
            reasons=_matched_filters(result.filter_results) or ["match_found"],
        )


def model_armor_client(location: str) -> Any:
    """Regional endpoint: Model Armor templates are regional resources."""
    from google.api_core.client_options import ClientOptions
    from google.cloud import modelarmor_v1

    return modelarmor_v1.ModelArmorClient(
        client_options=ClientOptions(api_endpoint=f"modelarmor.{location}.rep.googleapis.com")
    )
