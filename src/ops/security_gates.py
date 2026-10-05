"""CI security gates (MM-G88, ADR-0018) over scanner JSON output.

    python -m ops.security_gates pip-audit   # reads ./pip-audit.json
    python -m ops.security_gates licences    # reads ./licences.json

- `pip-audit`: fails when a dependency has a known vulnerability **with a fix
  available** -- something a version bump resolves. Vulnerabilities with no
  fix yet are printed, not failed (nothing to do but wait; Dependabot and the
  Security tab track them).
- `licences`: the licence allow-list. Fails on GPL / AGPL (strong copyleft
  would bind the image we ship); LGPL and permissive licences pass. A
  dual-licensed package can be allowed in `LICENCE_EXCEPTIONS` with a reason.

Exit code 1 on a failed gate, so the CI step fails.
"""

import json
import re
import sys
from pathlib import Path
from typing import Any

# GPL / AGPL in SPDX ids, classifiers or free text -- not LGPL / "Lesser".
_STRONG_COPYLEFT = re.compile(
    r"(?<![a-z])A?GPL|GNU (Affero )?General Public License", re.IGNORECASE
)

# gate -> the report file it reads (written by the CI step before it).
REPORTS = {"pip-audit": "pip-audit.json", "licences": "licences.json"}

# package name (lowercase) -> why it is acceptable despite the match.
LICENCE_EXCEPTIONS: dict[str, str] = {}


def fixable_vulnerabilities(audit: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(fixable, unfixed) findings from `pip-audit -f json` output."""
    fixable, unfixed = [], []
    for dependency in audit.get("dependencies", []):
        for vuln in dependency.get("vulns", []):
            line = f"{dependency['name']} {dependency.get('version', '?')}: {vuln['id']}"
            if vuln.get("fix_versions"):
                fixable.append(f"{line} (fix: {', '.join(vuln['fix_versions'])})")
            else:
                unfixed.append(line)
    return fixable, unfixed


def forbidden_licences(packages: list[dict[str, Any]]) -> list[str]:
    """Packages from `pip-licenses --format=json` under GPL / AGPL."""
    found = []
    for package in packages:
        licence = str(package.get("License", ""))
        name = str(package.get("Name", "")).lower()
        if _STRONG_COPYLEFT.search(licence) and name not in LICENCE_EXCEPTIONS:
            found.append(f"{package.get('Name')} {package.get('Version', '?')}: {licence}")
    return found


def main(argv: list[str], reports_dir: Path | None = None) -> int:
    """The report is read from a fixed file name in the working directory
    (REPORTS), never from a path given on the command line."""
    if len(argv) != 1 or argv[0] not in REPORTS:
        print(f"usage: python -m ops.security_gates {{{'|'.join(REPORTS)}}}")
        return 2
    gate = argv[0]
    data = json.loads(((reports_dir or Path.cwd()) / REPORTS[gate]).read_text(encoding="utf-8"))
    if gate == "pip-audit":
        fixable, unfixed = fixable_vulnerabilities(data)
        for line in unfixed:
            print(f"no fix yet (not failing): {line}")
        for line in fixable:
            print(f"FIXABLE: {line}")
        return 1 if fixable else 0
    forbidden = forbidden_licences(data)
    for line in forbidden:
        print(f"FORBIDDEN LICENCE: {line}")
    print(f"{len(data)} packages checked, {len(forbidden)} under GPL/AGPL")
    return 1 if forbidden else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
