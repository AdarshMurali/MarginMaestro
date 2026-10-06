"""MM-143: per-counterparty WhatsApp contacts -- the repository and the admin
CLI. The number is personal data: it is read from a hidden prompt and never
printed (only its last two digits)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from persistence import contacts
from persistence.contacts import (
    ContactError,
    active_contact,
    contact_phone_if_unchanged,
    contact_version,
    list_contacts,
    main,
    mask_last2,
    remove_contact,
    set_contact,
    validate_e164,
)
from persistence.db.models import Base, CounterpartyContactORM, CounterpartyORM

NUMBER = "+15550100987"  # fictional (555-01xx)
OTHER = "+447700900123"  # Ofcom drama range


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as session:
        for cp in ("CP-1", "CP-2"):
            session.add(CounterpartyORM(id=cp, name=f"Name {cp}", type="Bank", country="US"))
        session.commit()
    return factory


# --- validation and masking --------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("+15550100987", "+15550100987"),
        ("+1 (555) 010-0987", "+15550100987"),
        ("+44 7700.900.123", "+447700900123"),
    ],
)
def test_e164_numbers_are_normalised(raw, expected):
    assert validate_e164(raw) == expected


@pytest.mark.parametrize("raw", ["15550100987", "+0123456789", "+1555", "+1555010098712345", ""])
def test_invalid_numbers_are_rejected_without_echoing_them(raw):
    with pytest.raises(ContactError) as exc_info:
        validate_e164(raw)
    digits = "".join(ch for ch in raw if ch.isdigit())
    assert not digits or digits not in str(exc_info.value)


def test_masking_keeps_only_the_last_two_digits():
    assert mask_last2(NUMBER) == "+…87"
    assert mask_last2("") == "+…"


# --- repository ---------------------------------------------------------------------


def test_set_then_route_to_the_active_contact(session_factory):
    with session_factory() as session:
        row = set_contact(session, "CP-1", "  Jane Doe ", "+1 555 010 0987")
        recipient = active_contact(session, "CP-1")

    assert row.contact_name == "Jane Doe"
    assert recipient is not None
    assert recipient.phone == NUMBER
    assert recipient.version == contact_version(row.updated_at)
    with session_factory() as session:
        assert active_contact(session, "CP-2") is None  # unmapped: default applies


def test_inactive_contact_is_not_used(session_factory):
    with session_factory() as session:
        set_contact(session, "CP-1", "Jane", NUMBER, active=False)
        assert active_contact(session, "CP-1") is None


def test_every_change_gives_a_new_version(session_factory):
    with session_factory() as session:
        set_contact(session, "CP-1", "Jane", NUMBER)
        first = active_contact(session, "CP-1")
        set_contact(session, "CP-1", "Jane", OTHER)  # same second: still a new version
        second = active_contact(session, "CP-1")

    assert first is not None and second is not None
    assert first.contact_id == second.contact_id  # replaced in place, one row
    assert first.version != second.version
    assert second.phone == OTHER


def test_phone_is_only_returned_for_the_unchanged_version(session_factory):
    with session_factory() as session:
        set_contact(session, "CP-1", "Jane", NUMBER)
        sent_to = active_contact(session, "CP-1")
        assert sent_to is not None
        assert contact_phone_if_unchanged(session, sent_to.contact_id, sent_to.version) == NUMBER

        set_contact(session, "CP-1", "Jane", OTHER)
        assert contact_phone_if_unchanged(session, sent_to.contact_id, sent_to.version) is None

        current = active_contact(session, "CP-1")
        assert current is not None
        set_contact(session, "CP-1", "Jane", OTHER, active=False)
        assert contact_phone_if_unchanged(session, current.contact_id, current.version) is None
        assert contact_phone_if_unchanged(session, 999, current.version) is None


def test_unknown_counterparty_and_empty_name_are_rejected(session_factory):
    with session_factory() as session:
        with pytest.raises(ContactError, match="unknown counterparty"):
            set_contact(session, "CP-404", "Jane", NUMBER)
        with pytest.raises(ContactError, match="name is empty"):
            set_contact(session, "CP-1", "  ", NUMBER)


def test_list_is_masked_and_remove_deletes(session_factory):
    with session_factory() as session:
        set_contact(session, "CP-2", "Bob", OTHER)
        set_contact(session, "CP-1", "Jane", NUMBER)
        listed = list_contacts(session)
        assert [c.counterparty_id for c in listed] == ["CP-1", "CP-2"]
        assert [c.masked_phone for c in listed] == ["+…87", "+…23"]
        assert all(NUMBER not in repr(c) and OTHER not in repr(c) for c in listed)

        assert remove_contact(session, "CP-1") is True
        assert remove_contact(session, "CP-1") is False
        assert session.query(CounterpartyContactORM).count() == 1


def test_reprs_never_show_the_number(session_factory):
    with session_factory() as session:
        row = set_contact(session, "CP-1", "Jane", NUMBER)
        recipient = active_contact(session, "CP-1")
        assert NUMBER not in repr(row) and "0987" not in repr(row)
        assert NUMBER not in repr(recipient)


def test_version_is_naive_whole_seconds():
    stamp = datetime(2026, 10, 6, 12, 0, 1, 999999, tzinfo=UTC)
    assert contact_version(stamp) == "2026-10-06T12:00:01"


# --- CLI --------------------------------------------------------------------------


def _prompt(*answers: str):
    queue = list(answers)
    prompts: list[str] = []

    def prompt(text: str) -> str:
        prompts.append(text)
        return queue.pop(0)

    prompt.prompts = prompts  # type: ignore[attr-defined]
    return prompt


def test_cli_set_reads_the_number_hidden_twice_and_prints_no_digits(session_factory, capsys):
    prompt = _prompt(NUMBER, "+1 555 010 0987")

    code = main(
        ["set", "--counterparty", "CP-1", "--name", "Jane Doe"],
        session_factory=session_factory,
        prompt=prompt,
    )

    out = capsys.readouterr().out
    assert code == 0
    assert len(prompt.prompts) == 2 and all("hidden" in p for p in prompt.prompts)
    assert "Jane Doe" in out and "active" in out
    assert not any(ch.isdigit() for ch in out.replace("CP-1", ""))  # no digits of the number
    with session_factory() as session:
        assert active_contact(session, "CP-1").phone == NUMBER  # type: ignore[union-attr]


def test_cli_set_refuses_mismatched_or_invalid_entries(session_factory, capsys):
    mismatch = main(
        ["set", "--counterparty", "CP-1", "--name", "Jane"],
        session_factory=session_factory,
        prompt=_prompt(NUMBER, OTHER),
    )
    invalid = main(
        ["set", "--counterparty", "CP-1", "--name", "Jane"],
        session_factory=session_factory,
        prompt=_prompt("5550100987"),
    )

    out = capsys.readouterr().out
    assert (mismatch, invalid) == (2, 2)
    assert "differ" in out and "E.164" in out
    assert "0100987" not in out and "900123" not in out
    with session_factory() as session:
        assert list_contacts(session) == []


def test_cli_set_inactive_list_and_remove(session_factory, capsys):
    main(
        ["set", "--counterparty", "CP-2", "--name", "Bob", "--inactive"],
        session_factory=session_factory,
        prompt=_prompt(OTHER, OTHER),
    )
    main(["list"], session_factory=session_factory)
    main(["remove", "--counterparty", "CP-2"], session_factory=session_factory)
    main(["remove", "--counterparty", "CP-2"], session_factory=session_factory)
    main(["list"], session_factory=session_factory)

    out = capsys.readouterr().out
    assert "CP-2\twhatsapp\tBob\t+…23\tinactive" in out
    assert "Removed CP-2's WhatsApp contact." in out
    assert "CP-2 has no WhatsApp contact." in out
    assert "No contacts" in out
    assert "900123" not in out


def test_cli_unknown_counterparty_is_an_error(session_factory, capsys):
    code = main(
        ["set", "--counterparty", "CP-9", "--name", "X"],
        session_factory=session_factory,
        prompt=_prompt(NUMBER, NUMBER),
    )

    assert code == 2
    assert "unknown counterparty CP-9" in capsys.readouterr().out


def test_cli_builds_its_session_factory_from_settings(monkeypatch, session_factory, capsys):
    monkeypatch.setattr(
        "persistence.db.engine.get_session_factory", lambda settings: session_factory
    )

    assert contacts.main(["list"]) == 0
    assert "No contacts" in capsys.readouterr().out
