"""MM-G88: the CI security gates (pip-audit fixable vulns, licence allow-list)."""

import json

import pytest

from ops import security_gates

AUDIT = {
    "dependencies": [
        {
            "name": "pyjwt",
            "version": "2.13.0",
            "vulns": [{"id": "PYSEC-1", "fix_versions": ["2.14.0"]}],
        },
        {"name": "chromadb", "version": "1.5.9", "vulns": [{"id": "PYSEC-2", "fix_versions": []}]},
        {"name": "fastapi", "version": "1.0", "vulns": []},
        {"name": "local-pkg", "skip_reason": "not on PyPI"},
    ]
}


def test_fixable_and_unfixed_vulnerabilities_are_split():
    fixable, unfixed = security_gates.fixable_vulnerabilities(AUDIT)
    assert fixable == ["pyjwt 2.13.0: PYSEC-1 (fix: 2.14.0)"]
    assert unfixed == ["chromadb 1.5.9: PYSEC-2"]


@pytest.mark.parametrize(
    ("licence", "forbidden"),
    [
        ("GNU General Public License v3 (GPLv3)", True),
        ("GPL-2.0-or-later", True),
        ("AGPL-3.0", True),
        ("GNU Affero General Public License v3", True),
        ("GNU Lesser General Public License v3 (LGPLv3)", False),
        ("LGPL-3.0-only", False),
        ("GNU Library or Lesser General Public License (LGPL)", False),
        ("MIT License", False),
        ("Apache Software License; BSD License", False),
        ("UNKNOWN", False),
    ],
)
def test_licence_allow_list(licence, forbidden):
    packages = [{"Name": "pkg", "Version": "1", "License": licence}]
    assert bool(security_gates.forbidden_licences(packages)) is forbidden


def test_exceptions_allow_a_dual_licensed_package(monkeypatch):
    monkeypatch.setattr(security_gates, "LICENCE_EXCEPTIONS", {"dual": "MIT OR GPL, using MIT"})
    packages = [{"Name": "Dual", "Version": "1", "License": "MIT OR GPL-2.0"}]
    assert security_gates.forbidden_licences(packages) == []


def test_main_exit_codes(tmp_path, capsys):
    audit = tmp_path / "pip-audit.json"
    audit.write_text(json.dumps(AUDIT), encoding="utf-8")
    assert security_gates.main(["pip-audit"], reports_dir=tmp_path) == 1
    assert "FIXABLE: pyjwt" in capsys.readouterr().out

    audit.write_text(json.dumps({"dependencies": [AUDIT["dependencies"][1]]}), encoding="utf-8")
    assert security_gates.main(["pip-audit"], reports_dir=tmp_path) == 0

    licences = tmp_path / "licences.json"
    licences.write_text(
        json.dumps([{"Name": "x", "Version": "1", "License": "GPLv3"}]), encoding="utf-8"
    )
    assert security_gates.main(["licences"], reports_dir=tmp_path) == 1
    licences.write_text(json.dumps([{"Name": "x", "Version": "1", "License": "MIT"}]), "utf-8")
    assert security_gates.main(["licences"], reports_dir=tmp_path) == 0
    assert "1 packages checked, 0 under GPL/AGPL" in capsys.readouterr().out


def test_main_reads_fixed_report_names_from_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "licences.json").write_text("[]", encoding="utf-8")
    assert security_gates.main(["licences"]) == 0


@pytest.mark.parametrize("argv", [["unknown"], ["pip-audit", "../../etc/passwd"], []])
def test_main_rejects_anything_but_a_gate_name(argv):
    assert security_gates.main(argv) == 2
