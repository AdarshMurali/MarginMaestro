import threading
from datetime import UTC, datetime
from typing import Literal

import pytest
from langgraph.checkpoint.base import WRITES_IDX_MAP
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from persistence.db.checkpoint_saver import AzureSQLSaver
from persistence.db.models import Base


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _checkpoint(checkpoint_id: str) -> dict:
    return {
        "v": 1,
        "id": checkpoint_id,
        "ts": datetime.now(UTC).isoformat(),
        "channel_values": {"a": "x"},
        "channel_versions": {"a": 1},
        "versions_seen": {},
        "updated_channels": None,
    }


class _State(BaseModel):
    a: str
    decision: Literal["approved", "rejected", "adjusted"] | None = None
    adjusted: float | None = None


def _interrupt_graph():
    def node1(state: _State) -> dict:
        resume = interrupt("pause")
        decision = resume["decision"]
        return {
            "decision": decision,
            "adjusted": resume.get("adjusted") if decision == "adjusted" else None,
        }

    graph = StateGraph(_State)
    graph.add_node("n1", node1)
    graph.add_edge(START, "n1")
    graph.add_edge("n1", END)
    return graph


class TestAzureSQLSaverRealGraph:
    """Exercises put/put_writes/get_tuple/list together via a real LangGraph
    interrupt()/resume cycle -- the same contract the orchestrator relies on."""

    def test_pause_and_resume_round_trips_through_the_saver(self, session_factory) -> None:
        graph = _interrupt_graph().compile(checkpointer=AzureSQLSaver(session_factory))
        cfg = {"configurable": {"thread_id": "t1"}}

        paused = graph.invoke(_State(a="x"), config=cfg)
        assert "__interrupt__" in paused

        resumed = graph.invoke(Command(resume={"decision": "approved"}), config=cfg)
        assert resumed == {"a": "x", "decision": "approved", "adjusted": None}

    def test_a_fresh_saver_instance_over_the_same_db_resumes_correctly(
        self, session_factory
    ) -> None:
        """Simulates a process restart: a brand new AzureSQLSaver + compiled
        graph object, pointed at the same underlying DB, must still resume
        correctly -- this is the whole point of MM-38."""
        graph1 = _interrupt_graph().compile(checkpointer=AzureSQLSaver(session_factory))
        cfg = {"configurable": {"thread_id": "t2"}}
        graph1.invoke(_State(a="y"), config=cfg)

        graph2 = _interrupt_graph().compile(checkpointer=AzureSQLSaver(session_factory))
        resumed = graph2.invoke(
            Command(resume={"decision": "adjusted", "adjusted": 42.0}), config=cfg
        )

        assert resumed == {"a": "y", "decision": "adjusted", "adjusted": 42.0}


class TestAzureSQLSaverDirect:
    def test_get_tuple_returns_none_when_missing(self, session_factory) -> None:
        saver = AzureSQLSaver(session_factory)
        assert saver.get_tuple({"configurable": {"thread_id": "nope"}}) is None

    def test_defaults_to_a_private_lock_when_none_given(self) -> None:
        saver_a = AzureSQLSaver(lambda: None)
        saver_b = AzureSQLSaver(lambda: None)
        assert saver_a._lock is not saver_b._lock

    def test_uses_an_externally_provided_lock_when_given(self, session_factory) -> None:
        """MM-91: the orchestrator shares one lock between this class's own
        writes and its separate audit-log writes against the same
        connection -- this only works if an injected lock is actually the
        one acquired, not silently replaced by a private one."""
        shared_lock = threading.Lock()
        saver = AzureSQLSaver(session_factory, lock=shared_lock)

        assert saver._lock is shared_lock

        # Prove it's genuinely used, not just stored: held externally, a put()
        # on another thread should block until released.
        shared_lock.acquire()
        entered = threading.Event()

        def _put() -> None:
            saver.put({"configurable": {"thread_id": "t-lock"}}, _checkpoint("c1"), {}, {})
            entered.set()

        thread = threading.Thread(target=_put)
        thread.start()
        blocked_in_time = not entered.wait(timeout=0.2)
        shared_lock.release()
        thread.join(timeout=2)

        assert blocked_in_time
        assert entered.is_set()

    def test_put_then_get_tuple_round_trips_checkpoint_and_metadata(self, session_factory) -> None:
        saver = AzureSQLSaver(session_factory)
        config = {"configurable": {"thread_id": "t3"}}
        checkpoint = _checkpoint("c1")

        saver.put(config, checkpoint, {"source": "loop", "step": 0}, {"a": 1})
        tup = saver.get_tuple({"configurable": {"thread_id": "t3"}})

        assert tup is not None
        assert tup.checkpoint["id"] == "c1"
        assert tup.checkpoint["channel_values"] == {"a": "x"}
        assert tup.metadata["source"] == "loop"

    def test_get_tuple_without_checkpoint_id_returns_the_latest(self, session_factory) -> None:
        saver = AzureSQLSaver(session_factory)
        config = {"configurable": {"thread_id": "t4"}}
        saver.put(config, _checkpoint("c1"), {}, {})
        saver.put(
            {"configurable": {"thread_id": "t4", "checkpoint_id": "c1"}},
            _checkpoint("c2"),
            {},
            {},
        )

        tup = saver.get_tuple({"configurable": {"thread_id": "t4"}})

        assert tup is not None
        assert tup.checkpoint["id"] == "c2"
        assert tup.parent_config is not None
        assert tup.parent_config["configurable"]["checkpoint_id"] == "c1"

    def test_list_respects_limit_and_thread_scoping(self, session_factory) -> None:
        saver = AzureSQLSaver(session_factory)
        for cid in ("c1", "c2", "c3"):
            saver.put({"configurable": {"thread_id": "t5"}}, _checkpoint(cid), {}, {})
        saver.put({"configurable": {"thread_id": "other"}}, _checkpoint("c1"), {}, {})

        results = list(saver.list({"configurable": {"thread_id": "t5"}}, limit=2))

        assert len(results) == 2
        assert all(r.config["configurable"]["thread_id"] == "t5" for r in results)

    def test_list_filters_by_explicit_checkpoint_ns_and_checkpoint_id(
        self, session_factory
    ) -> None:
        saver = AzureSQLSaver(session_factory)
        saver.put({"configurable": {"thread_id": "t9"}}, _checkpoint("c1"), {}, {})
        saver.put(
            {"configurable": {"thread_id": "t9", "checkpoint_id": "c1"}}, _checkpoint("c2"), {}, {}
        )

        results = list(
            saver.list(
                {
                    "configurable": {
                        "thread_id": "t9",
                        "checkpoint_ns": "",
                        "checkpoint_id": "c1",
                    }
                }
            )
        )

        assert [r.checkpoint["id"] for r in results] == ["c1"]

    def test_list_before_excludes_checkpoints_at_or_after_the_given_id(
        self, session_factory
    ) -> None:
        saver = AzureSQLSaver(session_factory)
        saver.put({"configurable": {"thread_id": "t10"}}, _checkpoint("c1"), {}, {})
        saver.put(
            {"configurable": {"thread_id": "t10", "checkpoint_id": "c1"}},
            _checkpoint("c2"),
            {},
            {},
        )

        results = list(
            saver.list(
                {"configurable": {"thread_id": "t10"}},
                before={"configurable": {"thread_id": "t10", "checkpoint_id": "c2"}},
            )
        )

        assert [r.checkpoint["id"] for r in results] == ["c1"]

    def test_list_filter_matches_on_metadata(self, session_factory) -> None:
        saver = AzureSQLSaver(session_factory)
        saver.put(
            {"configurable": {"thread_id": "t11"}}, _checkpoint("c1"), {"source": "input"}, {}
        )
        saver.put(
            {"configurable": {"thread_id": "t11", "checkpoint_id": "c1"}},
            _checkpoint("c2"),
            {"source": "loop"},
            {},
        )

        results = list(
            saver.list({"configurable": {"thread_id": "t11"}}, filter={"source": "loop"})
        )

        assert [r.checkpoint["id"] for r in results] == ["c2"]

    def test_put_writes_first_write_wins_for_a_normal_channel(self, session_factory) -> None:
        saver = AzureSQLSaver(session_factory)
        config = {"configurable": {"thread_id": "t6", "checkpoint_id": "c1"}}
        saver.put_writes(config, [("chan", "first")], task_id="task-1")
        saver.put_writes(config, [("chan", "second")], task_id="task-1")

        tup_config = {"configurable": {"thread_id": "t6"}}
        saver.put(tup_config, _checkpoint("c1"), {}, {})
        tup = saver.get_tuple({"configurable": {"thread_id": "t6", "checkpoint_id": "c1"}})

        assert tup is not None
        assert tup.pending_writes == [("task-1", "chan", "first")]

    def test_put_writes_overwrites_for_a_sentinel_channel(self, session_factory) -> None:
        error_channel = next(iter(WRITES_IDX_MAP))
        saver = AzureSQLSaver(session_factory)
        config = {"configurable": {"thread_id": "t7", "checkpoint_id": "c1"}}
        saver.put_writes(config, [(error_channel, "first-error")], task_id="task-1")
        saver.put_writes(config, [(error_channel, "second-error")], task_id="task-1")

        saver.put({"configurable": {"thread_id": "t7"}}, _checkpoint("c1"), {}, {})
        tup = saver.get_tuple({"configurable": {"thread_id": "t7", "checkpoint_id": "c1"}})

        assert tup is not None
        assert tup.pending_writes == [("task-1", error_channel, "second-error")]

    def test_delete_thread_removes_checkpoints_and_writes(self, session_factory) -> None:
        saver = AzureSQLSaver(session_factory)
        config = {"configurable": {"thread_id": "t8", "checkpoint_id": "c1"}}
        saver.put({"configurable": {"thread_id": "t8"}}, _checkpoint("c1"), {}, {})
        saver.put_writes(config, [("chan", "value")], task_id="task-1")

        saver.delete_thread("t8")

        assert saver.get_tuple({"configurable": {"thread_id": "t8"}}) is None

    def test_concurrent_puts_do_not_lose_checkpoints(self, session_factory) -> None:
        """Regression test for a real bug: LangGraph's Pregel runtime calls
        checkpointer methods from an internal ThreadPoolExecutor even for a
        simple sequential graph. Without AzureSQLSaver's lock, concurrent
        put() calls against the same connection intermittently (roughly
        1-in-5 to 1-in-8 runs) lost a checkpoint row silently."""
        from concurrent.futures import ThreadPoolExecutor

        saver = AzureSQLSaver(session_factory)
        checkpoint_ids = [f"c{i}" for i in range(20)]

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(
                pool.map(
                    lambda cid: saver.put(
                        {"configurable": {"thread_id": "concurrent"}}, _checkpoint(cid), {}, {}
                    ),
                    checkpoint_ids,
                )
            )

        stored_ids = {
            tup.checkpoint["id"]
            for tup in saver.list({"configurable": {"thread_id": "concurrent"}})
        }
        assert stored_ids == set(checkpoint_ids)
