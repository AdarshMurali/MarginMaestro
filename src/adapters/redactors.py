"""Redactor implementations (MM-115).

- `SdpRedactor`: Sensitive Data Protection `deidentify_content`, replacing each
  finding with its info type (`[EMAIL_ADDRESS]`). Regional (us-central1).
- `RegexRedactor`: in-code fallback, deliberately strict -- every match is
  validated (Luhn for card numbers, mod-97 for IBANs, a leading `+` for
  phone numbers) so dates, amounts and CSA figures are never touched.
- `NoRedactor`: explicit opt-out.

Info types are financial/contact identifiers only. PERSON_NAME is excluded on
purpose: it fires on counterparty names ("Rodriguez Partners") that the CSA
extraction needs.
"""

import re
from typing import Any

INFO_TYPES = [
    "EMAIL_ADDRESS",
    "PHONE_NUMBER",
    "CREDIT_CARD_NUMBER",
    "IBAN_CODE",
    "SWIFT_CODE",
    "US_BANK_ROUTING_MICR",
    "US_SOCIAL_SECURITY_NUMBER",
    "IP_ADDRESS",
]


class SdpRedactor:
    name = "sdp"

    def __init__(self, project_id: str, location: str, client: Any) -> None:
        self._parent = f"projects/{project_id}/locations/{location}"
        self._client = client

    def redact(self, text: str) -> str:
        if not text.strip():
            return text
        response = self._client.deidentify_content(
            request={
                "parent": self._parent,
                "inspect_config": {
                    "info_types": [{"name": name} for name in INFO_TYPES],
                    # LIKELY+: avoid masking dates/amounts that merely look numeric.
                    "min_likelihood": "LIKELY",
                },
                "deidentify_config": {
                    "info_type_transformations": {
                        "transformations": [
                            {"primitive_transformation": {"replace_with_info_type_config": {}}}
                        ]
                    }
                },
                "item": {"value": text},
            }
        )
        redacted: str = response.item.value
        return redacted


_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
# International format only (leading +): "2026-08-16" or "USD 240,000" can't match.
_PHONE = re.compile(r"(?<![\w+])\+\d[\d ()-]{7,17}\d\b")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")
_CARD = re.compile(r"\b(?:\d[ -]?){12,18}\d\b")


def _luhn_ok(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _iban_ok(candidate: str) -> bool:
    compact = candidate.replace(" ", "")
    if not 15 <= len(compact) <= 34:
        return False
    rearranged = compact[4:] + compact[:4]
    numeric = "".join(str(int(ch, 36)) for ch in rearranged)
    return int(numeric) % 97 == 1


class RegexRedactor:
    name = "regex"

    def redact(self, text: str) -> str:
        text = _EMAIL.sub("[EMAIL_ADDRESS]", text)
        text = _IBAN.sub(lambda m: "[IBAN_CODE]" if _iban_ok(m.group()) else m.group(), text)

        def card(match: re.Match[str]) -> str:
            digits = re.sub(r"\D", "", match.group())
            return (
                "[CREDIT_CARD_NUMBER]"
                if 13 <= len(digits) <= 19 and _luhn_ok(digits)
                else match.group()
            )

        text = _CARD.sub(card, text)
        return _PHONE.sub("[PHONE_NUMBER]", text)


class NoRedactor:
    name = "none"

    def redact(self, text: str) -> str:
        return text


def dlp_client() -> Any:
    from google.cloud.dlp_v2 import DlpServiceClient

    return DlpServiceClient()


class ChainedRedactor:
    """Runs redactors in order, each on the previous one's output (MM-115).
    `REDACTOR_PROVIDER=sdp` chains Sensitive Data Protection with the strict
    regex pass: live testing showed SDP at LIKELY left an international phone
    number (+44 ...) unmasked, which the regex catches."""

    def __init__(self, redactors: list[Any]) -> None:
        if not redactors:
            raise ValueError("ChainedRedactor needs at least one redactor")
        self._redactors = redactors
        self.name = "+".join(r.name for r in redactors)

    def redact(self, text: str) -> str:
        for redactor in self._redactors:
            text = redactor.redact(text)
        return text
