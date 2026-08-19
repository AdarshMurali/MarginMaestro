from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.audit_log import get_margin_call_audit_log
from persistence.audit import record_audit_event
from persistence.db.models import Base


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _graph_with_state(values: dict) -> MagicMock:
    graph = MagicMock()
    graph.get_state.return_value.values = values
    return graph


class TestGetMarginCallAuditLog:
    def test_returns_none_when_no_run_exists(self, session_factory) -> None:
        graph = _graph_with_state({})

        with session_factory() as session:
            result = get_margin_call_audit_log(graph, session, "no-such-thread")

        assert result is None

    def test_returns_entries_in_insertion_order(self, session_factory) -> None:
        graph = _graph_with_state({"correlation_id": "corr-1", "counterparty_id": "CP-1"})

        with session_factory() as session:
            record_audit_event(
                session,
                "corr-1",
                "compute_exposure",
                {"variation_margin": 1.0},
                counterparty_id="CP-1",
            )
            record_audit_event(
                session, "corr-1", "fetch_csa_terms", {"threshold": 1000.0}, counterparty_id="CP-1"
            )

            result = get_margin_call_audit_log(graph, session, "evt-1:CP-1")

        assert result is not None
        assert result.thread_id == "evt-1:CP-1"
        assert result.correlation_id == "corr-1"
        assert [e.event_type for e in result.entries] == ["compute_exposure", "fetch_csa_terms"]
        assert result.entries[0].payload == {"variation_margin": 1.0}

    def test_only_returns_events_for_this_runs_correlation_and_counterparty_id(
        self, session_factory
    ) -> None:
        graph = _graph_with_state({"correlation_id": "corr-1", "counterparty_id": "CP-1"})

        with session_factory() as session:
            record_audit_event(session, "corr-1", "compute_exposure", counterparty_id="CP-1")
            # Same correlation_id (same triggering event), different
            # counterparty -- a sibling run, must not leak into this one's
            # audit log (the real bug this test guards against).
            record_audit_event(session, "corr-1", "compute_exposure", counterparty_id="CP-2")
            # Different correlation_id entirely.
            record_audit_event(session, "corr-OTHER", "compute_exposure", counterparty_id="CP-1")

            result = get_margin_call_audit_log(graph, session, "evt-1:CP-1")

        assert result is not None
        assert len(result.entries) == 1

    def test_empty_entries_when_run_exists_but_has_no_audit_rows_yet(self, session_factory) -> None:
        graph = _graph_with_state({"correlation_id": "corr-1", "counterparty_id": "CP-1"})

        with session_factory() as session:
            result = get_margin_call_audit_log(graph, session, "evt-1:CP-1")

        assert result is not None
        assert result.entries == []
