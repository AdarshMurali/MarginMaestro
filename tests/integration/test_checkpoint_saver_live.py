"""Live-DB checkpoint persistence tests (MM-38). Skipped automatically if no
database is reachable (e.g. CI, which has no SQL Server or ODBC driver
available) -- run these locally with `docker compose up -d sqlserver` first.
"""

from typing import Literal

import pytest
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel
from sqlalchemy.exc import DBAPIError

from config.settings import get_settings
from persistence.db.bootstrap import ensure_database_exists
from persistence.db.checkpoint_saver import AzureSQLSaver
from persistence.db.engine import get_engine, get_session_factory
from persistence.db.models import Base


@pytest.fixture(scope="module")
def db_session_factory():
    settings = get_settings()
    try:
        ensure_database_exists(settings)
        engine = get_engine(settings)
        Base.metadata.create_all(engine)
        engine.dispose()
    except DBAPIError as exc:
        pytest.skip(f"No reachable database for integration tests: {exc}")
    yield get_session_factory(settings)


class _State(BaseModel):
    a: str
    decision: Literal["approved", "rejected", "adjusted"] | None = None


def _interrupt_graph():
    def node1(state: _State) -> dict:
        resume = interrupt("pause")
        return {"decision": resume["decision"]}

    graph = StateGraph(_State)
    graph.add_node("n1", node1)
    graph.add_edge(START, "n1")
    graph.add_edge("n1", END)
    return graph


def test_a_paused_run_survives_a_fresh_saver_against_the_real_database(
    db_session_factory,
) -> None:
    """The whole point of MM-38: not just that put/get round-trip against a
    real SQL Server, but that a brand new AzureSQLSaver/graph instance --
    standing in for a restarted process -- can resume a run it never itself
    paused, reading nothing but what's on disk in the real database."""
    thread_id = "mm38-live-restart-test"
    cfg = {"configurable": {"thread_id": thread_id}}

    graph1 = _interrupt_graph().compile(checkpointer=AzureSQLSaver(db_session_factory))
    try:
        paused = graph1.invoke(_State(a="live"), config=cfg)
        assert "__interrupt__" in paused

        graph2 = _interrupt_graph().compile(checkpointer=AzureSQLSaver(db_session_factory))
        resumed = graph2.invoke(Command(resume={"decision": "approved"}), config=cfg)

        assert resumed == {"a": "live", "decision": "approved"}
    finally:
        AzureSQLSaver(db_session_factory).delete_thread(thread_id)
