"""MM-128: read-only MCP servers over streamable HTTP, scoped to the caller."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

from api.schemas import MarginCallFeedResponse, MarginCallLifecycleStatus, MarginCallSummary
from mcp_servers import caller, http, margin_status, rag_retriever
from mcp_servers.caller import CallerNotAuthorizedError, caller_scope, scoped_factory
from persistence.db.models import Base, CounterpartyORM, UserCounterpartyAccessORM, UserORM
from persistence.db.rls import FIRM_WIDE, RLS_SCOPE_KEY
from rag.retriever import RetrievedChunk

HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
    "Host": "mcp-rag-123456789.us-central1.run.app",
}


@pytest.fixture(autouse=True)
def fresh_session_managers():
    """FastMCP's session manager runs once per server object; production
    builds one app per process, tests build several."""
    for name in http.SERVERS:
        server = http.get_server(name)
        server._session_manager = None
        # As Terraform sets MCP_ALLOWED_HOSTS on Cloud Run (servers are built at import).
        server.settings.transport_security.allowed_hosts = [HEADERS["Host"]]


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        for cp in ("CP-1", "CP-3"):
            session.add(CounterpartyORM(id=cp, name=cp, type="fund", country="US"))
        session.add(UserORM(username="analyst1", password_hash="x", role="viewer"))
        session.add(UserORM(username="approver", password_hash="x", role="approver"))
        session.add(UserCounterpartyAccessORM(username="analyst1", counterparty_id="CP-1"))
        session.commit()
    return factory


def _ctx(headers: dict | None) -> SimpleNamespace:
    """A stand-in for FastMCP's Context: an HTTP request when headers are given."""
    request = SimpleNamespace(headers=headers) if headers is not None else None
    return SimpleNamespace(request_context=SimpleNamespace(request=request))


def _call(tool: str, arguments: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": arguments},
    }


def _chunk(counterparty_id: str) -> RetrievedChunk:
    return RetrievedChunk(
        text="Threshold text",
        source_file=f"csa/{counterparty_id or 'policy'}.md",
        doc_type="csa" if counterparty_id else "policy",
        counterparty_id=counterparty_id,
        effective_date="2026-07-26",
        section="Threshold",
        distance=0.1,
    )


def _summary(thread_id: str, counterparty_id: str, status: MarginCallLifecycleStatus):
    return MarginCallSummary(
        thread_id=thread_id,
        correlation_id="corr",
        counterparty_id=counterparty_id,
        event_type="price_shock",
        reason="HPE +7.4%",
        occurred_at=datetime(2026, 10, 2, 17, 30, tzinfo=UTC),
        status=status,
        call_amount=250_785.91,
    )


# --- caller identity and scope ---------------------------------------------------


def test_in_process_calls_run_firm_wide(session_factory):
    assert caller_scope(None, session_factory) == FIRM_WIDE
    assert caller_scope(_ctx(None), session_factory) == FIRM_WIDE


def test_context_outside_a_request_is_in_process(session_factory):
    class NoRequest:
        @property
        def request_context(self):
            raise ValueError("Context is not available outside of a request")

    assert caller_scope(NoRequest(), session_factory) == FIRM_WIDE


def test_scoped_analyst_gets_only_their_counterparties(session_factory):
    assert caller_scope(_ctx({"x-mm-user": "analyst1"}), session_factory) == "CP-1"


def test_firm_wide_role_is_read_from_the_database(session_factory):
    assert caller_scope(_ctx({"x-mm-user": "approver"}), session_factory) == FIRM_WIDE


def test_http_call_without_a_user_fails_loud(session_factory):
    with pytest.raises(CallerNotAuthorizedError, match="x-mm-user"):
        caller_scope(_ctx({}), session_factory)


def test_unknown_user_fails_loud(session_factory):
    with pytest.raises(CallerNotAuthorizedError, match="Unknown user"):
        caller_scope(_ctx({"x-mm-user": "mallory"}), session_factory)


def test_scoped_factory_carries_the_scope(session_factory):
    with scoped_factory(session_factory, "CP-1")() as session:
        assert session.info[RLS_SCOPE_KEY] == "CP-1"


# --- RAG tool --------------------------------------------------------------------


def test_rag_drops_documents_outside_the_callers_scope():
    chunks = [_chunk("CP-1"), _chunk("CP-3"), _chunk("")]
    with (
        patch.object(rag_retriever, "_scoped_store", return_value=("CP-1", None)),
        patch.object(rag_retriever, "retrieve", return_value=chunks) as retrieve,
    ):
        result = rag_retriever.retrieve_document_chunks("threshold?", ctx=_ctx({}))

    retrieve.assert_called_once_with("threshold?", None, None, 5, vector_store=None)
    assert [c["counterparty_id"] for c in result] == ["CP-1", ""]


def test_rag_uses_a_scoped_pgvector_store_for_analysts(session_factory):
    settings = SimpleNamespace(vector_store="pgvector")
    with (
        patch.object(rag_retriever, "get_mcp_session_factory", return_value=session_factory),
        patch.object(rag_retriever, "get_settings", return_value=settings),
    ):
        scope, store = rag_retriever._scoped_store(_ctx({"x-mm-user": "analyst1"}))

    assert scope == "CP-1"
    with store._session_factory() as session:
        assert session.info[RLS_SCOPE_KEY] == "CP-1"


@pytest.mark.parametrize("vector_store", ["chroma", "pgvector"])
def test_rag_firm_wide_or_chroma_uses_the_default_store(session_factory, vector_store):
    settings = SimpleNamespace(vector_store=vector_store)
    user = "approver" if vector_store == "pgvector" else "analyst1"
    with (
        patch.object(rag_retriever, "get_mcp_session_factory", return_value=session_factory),
        patch.object(rag_retriever, "get_settings", return_value=settings),
    ):
        _, store = rag_retriever._scoped_store(_ctx({"x-mm-user": user}))

    assert store is None


# --- margin-status tools ---------------------------------------------------------


@pytest.fixture
def feed(session_factory):
    calls = [
        _summary("t1:CP-1", "CP-1", MarginCallLifecycleStatus.AWAITING_APPROVAL),
        _summary("t2:CP-3", "CP-3", MarginCallLifecycleStatus.ESCALATED),
        _summary("t3:CP-1", "CP-1", MarginCallLifecycleStatus.ESCALATED),
    ]
    response = MarginCallFeedResponse(as_of=datetime.now(UTC), margin_calls=calls)
    with (
        patch.object(margin_status, "get_mcp_session_factory", return_value=session_factory),
        patch.object(margin_status, "get_graph", return_value=MagicMock()),
        patch.object(margin_status, "margin_call_feed", return_value=response) as feed_mock,
    ):
        yield feed_mock


def test_list_margin_calls_is_scoped_and_filtered(feed):
    analyst = _ctx({"x-mm-user": "analyst1"})

    everything = margin_status.list_margin_calls(ctx=analyst)
    escalated = margin_status.list_margin_calls(status="escalated", ctx=analyst)

    assert [c["thread_id"] for c in everything] == ["t1:CP-1", "t3:CP-1"]
    assert [c["thread_id"] for c in escalated] == ["t3:CP-1"]
    session = feed.call_args.args[1]
    assert session.info[RLS_SCOPE_KEY] == "CP-1"


def test_list_margin_calls_filters_by_counterparty_and_limit(feed):
    result = margin_status.list_margin_calls(counterparty_id="CP-1", limit=1)

    assert [c["thread_id"] for c in result] == ["t1:CP-1"]
    assert result[0]["call_amount"] == 250_785.91


def test_list_margin_calls_rejects_an_unknown_status(feed):
    with pytest.raises(ValueError, match="Unknown status"):
        margin_status.list_margin_calls(status="paid")


def test_get_margin_call_outside_scope_looks_like_not_found(feed):
    analyst = _ctx({"x-mm-user": "analyst1"})

    assert margin_status.get_margin_call("t1:CP-1", ctx=analyst)["counterparty_id"] == "CP-1"
    with pytest.raises(margin_status.MarginCallNotFoundError):
        margin_status.get_margin_call("t2:CP-3", ctx=analyst)


def test_status_graph_uses_the_mcp_session_factory(session_factory):
    margin_status.get_graph.cache_clear()
    with (
        patch.object(margin_status, "get_mcp_session_factory", return_value=session_factory),
        patch.object(margin_status, "build_orchestrator_graph") as build,
    ):
        margin_status.get_graph()
    margin_status.get_graph.cache_clear()

    build.assert_called_once_with(session_factory=session_factory)


# --- HTTP transport --------------------------------------------------------------


def test_only_read_only_servers_are_served():
    assert set(http.SERVERS) == {"market-data", "rag", "margin-status"}
    with pytest.raises(ValueError, match="Unknown MCP server"):
        http.get_server("slack-notifier")


def test_health_endpoint():
    with TestClient(http.build_app("market-data")) as client:
        response = client.get("/health", headers={"Host": HEADERS["Host"]})

    assert response.json() == {"status": "ok", "server": "market-data"}


def test_other_hosts_are_rejected():
    """DNS-rebinding protection stays on: only the service's own hostname."""
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    with TestClient(http.build_app("margin-status")) as client:
        response = client.post("/mcp", json=body, headers={**HEADERS, "Host": "evil.example"})

    assert response.status_code == 421


def test_allowed_hosts_come_from_settings(monkeypatch):
    from config.settings import get_settings
    from mcp_servers.base import new_server

    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "a.run.app, b.run.app")
    get_settings.cache_clear()
    try:
        security = new_server("x").settings.transport_security
    finally:
        get_settings.cache_clear()

    assert security.enable_dns_rebinding_protection is True
    assert security.allowed_hosts == ["a.run.app", "b.run.app"]


def test_tools_list_over_http_accepts_the_cloud_run_host():
    """The service's own *.run.app hostname is allowed."""
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    with TestClient(http.build_app("margin-status")) as client:
        response = client.post("/mcp", json=body, headers=HEADERS)

    assert response.status_code == 200
    names = [tool["name"] for tool in response.json()["result"]["tools"]]
    assert names == ["list_margin_calls", "get_margin_call"]


def test_forwarded_user_reaches_the_tool_over_http(session_factory):
    chunks = [_chunk("CP-1"), _chunk("CP-3")]
    with (
        patch.object(rag_retriever, "get_mcp_session_factory", return_value=session_factory),
        patch.object(
            rag_retriever, "get_settings", return_value=SimpleNamespace(vector_store="chroma")
        ),
        patch.object(rag_retriever, "retrieve", return_value=chunks),
        TestClient(http.build_app("rag")) as client,
    ):
        response = client.post(
            "/mcp",
            json=_call("retrieve_document_chunks", {"query": "threshold?"}),
            headers={**HEADERS, "X-MM-User": "analyst1"},
        )

    result = response.json()["result"]
    assert result["isError"] is False
    assert [c["counterparty_id"] for c in result["structuredContent"]["result"]] == ["CP-1"]


def test_http_call_without_a_user_is_an_error(session_factory):
    with (
        patch.object(rag_retriever, "get_mcp_session_factory", return_value=session_factory),
        patch.object(rag_retriever, "retrieve") as retrieve,
        TestClient(http.build_app("rag")) as client,
    ):
        response = client.post(
            "/mcp", json=_call("retrieve_document_chunks", {"query": "q"}), headers=HEADERS
        )

    result = response.json()["result"]
    assert result["isError"] is True
    assert "x-mm-user" in result["content"][0]["text"]
    retrieve.assert_not_called()


def test_create_app_serves_the_server_named_in_the_environment(monkeypatch):
    monkeypatch.setenv("MCP_SERVER", "market-data")
    with patch.object(http, "configure_logging") as configure:
        app = http.create_app()

    configure.assert_called_once()
    with TestClient(app) as client:
        assert client.get("/health").json()["server"] == "market-data"


def test_create_app_rejects_an_unknown_server(monkeypatch):
    monkeypatch.setenv("MCP_SERVER", "slack-notifier")
    with patch.object(http, "configure_logging"), pytest.raises(ValueError):
        http.create_app()


def test_caller_module_logs_without_leaking_headers(session_factory):
    with patch.object(caller, "logger") as logger:
        caller_scope(_ctx({"x-mm-user": "analyst1", "authorization": "Bearer t"}), session_factory)

    assert "Bearer t" not in str(logger.info.call_args)


def test_amounts_are_returned_in_cents(feed):
    call = _summary("t9:CP-1", "CP-1", MarginCallLifecycleStatus.AWAITING_APPROVAL)
    call.call_amount = 62957.75959485657
    feed.return_value = MarginCallFeedResponse(as_of=datetime.now(UTC), margin_calls=[call])

    assert margin_status.list_margin_calls()[0]["call_amount"] == 62957.76
    assert margin_status.get_margin_call("t9:CP-1")["call_amount"] == 62957.76


def test_a_call_without_an_amount_stays_none(feed):
    call = _summary("t8:CP-1", "CP-1", MarginCallLifecycleStatus.EVALUATING)
    call.call_amount = None
    feed.return_value = MarginCallFeedResponse(as_of=datetime.now(UTC), margin_calls=[call])

    assert margin_status.list_margin_calls()[0]["call_amount"] is None


def test_tool_description_explains_the_approval_stages():
    doc = margin_status.list_margin_calls.__doc__

    assert "awaiting_manager_approval = approved, needs a manager's second signature" in doc
    assert "awaiting_approval = needs an approver's decision" in doc
