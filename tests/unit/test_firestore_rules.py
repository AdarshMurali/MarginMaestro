"""MM-146: firebase/firestore.rules stays in step with the code that relies on
it. A static check (the rules emulator needs Java + firebase-tools, not in
CI): the status collection, the claim names the token endpoint mints, no
client writes, and a deny-all fallback. Terraform deploys this exact file."""

import re
from pathlib import Path

from config.settings import Settings
from realtime.tokens import scope_claims

ROOT = Path(__file__).resolve().parents[2]
RULES = (ROOT / "firebase" / "firestore.rules").read_text(encoding="utf-8")


def _block(collection: str) -> str:
    match = re.search(rf"match /{collection}/\{{\w+\}} \{{(.*?)\n    \}}", RULES, re.DOTALL)
    assert match, f"no rules for {collection}"
    return match.group(1)


def test_rules_cover_the_configured_status_collection():
    _block(Settings(_env_file=None).realtime_collection)


def test_reads_check_the_claims_the_token_endpoint_mints():
    block = _block("margin_call_status")
    claims = set(scope_claims("*")) | set(scope_claims("CP-1"))
    assert claims == {"firm_wide", "cps"}
    for claim in claims:
        assert f"request.auth.token.get('{claim}'" in block
    assert "request.auth != null" in block
    assert "resource.data.counterparty_id in request.auth.token.get('cps', [])" in block


def test_browsers_never_write():
    assert "allow write: if false;" in _block("margin_call_status")


def test_everything_else_is_denied():
    assert re.search(
        r"match /\{document=\*\*\} \{\s*allow read, write: if false;\s*\}", RULES
    ), "missing deny-all fallback"


def test_terraform_deploys_this_file():
    firebase_tf = (ROOT / "infra" / "gcp" / "firebase.tf").read_text(encoding="utf-8")
    assert 'file("${path.module}/../../firebase/firestore.rules")' in firebase_tf
    assert 'name         = "cloud.firestore"' in firebase_tf
