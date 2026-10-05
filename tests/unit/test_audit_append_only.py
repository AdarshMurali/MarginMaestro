"""MM-137: the audit trail is append-only. The database enforces it on
Postgres (migration e3f8a1c5d927, tested live in
tests/integration/test_audit_append_only_live.py); this static guard keeps
application code from even trying -- on SQL Server too, where there are no
such grants -- so a new UPDATE/DELETE of audit rows fails CI here first."""

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
MIGRATION = ROOT / "migrations" / "versions" / "e3f8a1c5d927_append_only_audit_log.py"

# SQL text that rewrites or erases audit rows.
RAW_SQL = re.compile(
    r"\b(UPDATE\s+audit_log|DELETE\s+FROM\s+audit_log|TRUNCATE\s+(TABLE\s+)?audit_log)\b",
    re.IGNORECASE,
)


def _python_files() -> list[Path]:
    return sorted(SRC.rglob("*.py"))


def _audit_row_mutations(tree: ast.AST) -> list[str]:
    """`update(AuditLogORM)`, `delete(AuditLogORM)`, `AuditLogORM.__table__.update()`,
    `<query of AuditLogORM>.update()/.delete()`, and `session.delete(<audit row>)`
    where the row came straight from a query of AuditLogORM."""
    problems = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
        if name not in ("update", "delete"):
            continue
        mentions_audit = any(
            isinstance(n, ast.Name) and n.id == "AuditLogORM"
            for part in [*node.args, getattr(func, "value", None)]
            if part is not None
            for n in ast.walk(part)
        )
        if mentions_audit:
            problems.append(f"line {node.lineno}: {ast.unparse(node)[:80]}")
    return problems


@pytest.mark.parametrize("path", _python_files(), ids=lambda p: str(p.relative_to(SRC)))
def test_application_code_never_updates_or_deletes_audit_rows(path):
    source = path.read_text(encoding="utf-8")
    assert not RAW_SQL.search(source), f"{path}: raw SQL rewrites audit_log"
    assert _audit_row_mutations(ast.parse(source)) == [], path


@pytest.mark.parametrize(
    "snippet",
    [
        "session.execute(update(AuditLogORM).values(payload=None))",
        "session.execute(delete(AuditLogORM).where(AuditLogORM.id == 1))",
        "session.query(AuditLogORM).filter_by(id=1).delete()",
        "session.query(AuditLogORM).update({'event_type': 'x'})",
        "AuditLogORM.__table__.delete()",
    ],
)
def test_the_guard_catches_orm_mutations(snippet):
    assert _audit_row_mutations(ast.parse(snippet))


@pytest.mark.parametrize(
    "snippet",
    ["UPDATE audit_log SET payload = NULL", "delete from audit_log", "TRUNCATE TABLE audit_log"],
)
def test_the_guard_catches_raw_sql(snippet):
    assert RAW_SQL.search(snippet)


def test_inserts_and_reads_are_not_flagged():
    snippet = (
        "session.add(AuditLogORM(correlation_id='c', event_type='e'))\n"
        "session.execute(select(AuditLogORM).where(AuditLogORM.id == 1))\n"
        "session.execute(delete(ProcessedEventORM).where(ProcessedEventORM.event_id == 'x'))\n"
    )
    assert _audit_row_mutations(ast.parse(snippet)) == []


def test_the_migration_revokes_update_and_delete_from_the_app_role_on_postgres_only():
    source = MIGRATION.read_text(encoding="utf-8")
    assert "REVOKE UPDATE, DELETE, TRUNCATE ON audit_log FROM {APP_ROLE}" in source
    assert 'APP_ROLE = "mm_app"' in source
    assert "if not _is_postgres():\n        return" in source  # SQL Server untouched
