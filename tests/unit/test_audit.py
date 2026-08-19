import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from persistence.audit import list_audit_events, record_audit_event
from persistence.db.models import AuditLogORM, Base


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


class TestRecordAuditEvent:
    def test_inserts_a_row_with_the_given_fields(self, session_factory) -> None:
        with session_factory() as session:
            record_audit_event(
                session,
                "corr-1",
                "compute_exposure",
                {"variation_margin": 100.0},
                counterparty_id="CP-1",
            )

            rows = list_audit_events(session, "corr-1", "CP-1")

        assert len(rows) == 1
        assert rows[0].correlation_id == "corr-1"
        assert rows[0].counterparty_id == "CP-1"
        assert rows[0].event_type == "compute_exposure"
        assert rows[0].payload == {"variation_margin": 100.0}
        assert rows[0].created_at is not None

    def test_payload_and_counterparty_id_default_to_none(self, session_factory) -> None:
        """Matches persistence.batch_loader's own "batch_load" audit
        event -- a system-level event not scoped to any one counterparty."""
        with session_factory() as session:
            record_audit_event(session, "corr-1", "batch_load")

            row = session.execute(select(AuditLogORM)).scalar_one()

        assert row.payload is None
        assert row.counterparty_id is None


class TestListAuditEvents:
    def test_returns_only_events_for_the_given_run(self, session_factory) -> None:
        with session_factory() as session:
            record_audit_event(session, "corr-1", "compute_exposure", counterparty_id="CP-1")
            # Same correlation_id, different counterparty -- a sibling run
            # from the same triggering event, must not leak in.
            record_audit_event(session, "corr-1", "compute_exposure", counterparty_id="CP-2")
            # Different correlation_id entirely.
            record_audit_event(session, "corr-2", "compute_exposure", counterparty_id="CP-1")
            record_audit_event(session, "corr-1", "fetch_csa_terms", counterparty_id="CP-1")

            rows = list_audit_events(session, "corr-1", "CP-1")

        assert [r.event_type for r in rows] == ["compute_exposure", "fetch_csa_terms"]

    def test_returns_events_in_insertion_order(self, session_factory) -> None:
        with session_factory() as session:
            record_audit_event(session, "corr-1", "compute_exposure", counterparty_id="CP-1")
            record_audit_event(session, "corr-1", "fetch_csa_terms", counterparty_id="CP-1")
            record_audit_event(session, "corr-1", "evaluate_breach", counterparty_id="CP-1")

            rows = list_audit_events(session, "corr-1", "CP-1")

        assert [r.event_type for r in rows] == [
            "compute_exposure",
            "fetch_csa_terms",
            "evaluate_breach",
        ]

    def test_empty_for_an_unknown_run(self, session_factory) -> None:
        with session_factory() as session:
            assert list_audit_events(session, "corr-none", "CP-none") == []
