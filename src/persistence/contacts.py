"""Per-counterparty WhatsApp contacts (MM-143, ADR-0016 amendment 2026-10-06).

A margin-call notice goes to the counterparty's **active** contact. A
counterparty without one falls back to the WHATSAPP_RECIPIENT default, so the
demo keeps working for counterparties nobody has mapped yet; the send records
which of the two it used.

Phone numbers are confidential personal data (data catalog `llm: deny`):
nothing here logs or prints one. The admin CLI reads the number from a hidden
prompt, shows only its last two digits, and the routing record a notice keeps
holds the contact's id and version -- never the number.

    python -m persistence.contacts set --counterparty CP-1 --name "Jane Doe"
    python -m persistence.contacts list
    python -m persistence.contacts remove --counterparty CP-1

Meta's free test number delivers only to verified recipients (at most five):
add and verify a number in the Meta app before mapping it here.
"""

import argparse
import getpass
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from persistence.db.models import CounterpartyContactORM, CounterpartyORM

WHATSAPP = "whatsapp"
# E.164: "+", a country code that doesn't start with 0, at most 15 digits.
E164 = re.compile(r"^\+[1-9]\d{7,14}$")
_SEPARATORS = re.compile(r"[\s\-().]")


class ContactError(ValueError):
    """A contact can't be stored. Never carries the number itself."""


def validate_e164(raw: str) -> str:
    """The number in E.164 form ("+15550100999"), spaces, dashes, dots and
    brackets removed. Raises ContactError (without the number) otherwise."""
    number = _SEPARATORS.sub("", raw or "")
    if not E164.fullmatch(number):
        raise ContactError(
            "not an E.164 number: expected '+', the country code and the number, "
            "8 to 15 digits in all"
        )
    return number


def mask_last2(number: str) -> str:
    """The only form a number is ever shown in by the CLI: "+…99"."""
    digits = "".join(ch for ch in number if ch.isdigit())
    return f"+…{digits[-2:]}" if len(digits) >= 2 else "+…"


def contact_version(updated_at: datetime) -> str:
    """A contact's version: its last update, to the second (SQL Server's
    DATETIME doesn't keep microseconds, so seconds round-trip on both)."""
    return updated_at.replace(tzinfo=None, microsecond=0).isoformat()


@dataclass(frozen=True)
class ContactRecipient:
    """Where a notice is routed. `phone` is the number in E.164 form; it is
    used for the send only and kept out of repr, logs and stored state."""

    contact_id: int
    version: str
    phone: str = field(repr=False)


@dataclass(frozen=True)
class ContactSummary:
    counterparty_id: str
    contact_name: str
    channel: str
    masked_phone: str
    active: bool
    updated_at: str


def active_contact(
    session: Session, counterparty_id: str, channel: str = WHATSAPP
) -> ContactRecipient | None:
    """The counterparty's active contact on `channel`, or None (the caller
    then uses the WHATSAPP_RECIPIENT default)."""
    row = session.execute(
        select(CounterpartyContactORM).where(
            CounterpartyContactORM.counterparty_id == counterparty_id,
            CounterpartyContactORM.channel == channel,
            CounterpartyContactORM.active.is_(True),
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    return ContactRecipient(
        contact_id=row.id, version=contact_version(row.updated_at), phone=row.phone_e164
    )


def contact_phone_if_unchanged(session: Session, contact_id: int, version: str) -> str | None:
    """The number of contact `contact_id`, only while it is still the version
    a notice was sent to (not edited, deactivated or removed since)."""
    row = session.get(CounterpartyContactORM, contact_id)
    if row is None or not row.active or contact_version(row.updated_at) != version:
        return None
    return row.phone_e164


def _next_update_time(previous: datetime | None) -> datetime:
    """Now (naive UTC, whole seconds), and always later than `previous`, so
    every change gives the contact a new version."""
    now = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    if previous is not None and now <= previous.replace(microsecond=0):
        return previous.replace(microsecond=0) + timedelta(seconds=1)
    return now


def set_contact(
    session: Session,
    counterparty_id: str,
    contact_name: str,
    phone: str,
    *,
    channel: str = WHATSAPP,
    active: bool = True,
) -> CounterpartyContactORM:
    """Creates or replaces the counterparty's contact on `channel`. Commits."""
    number = validate_e164(phone)
    name = contact_name.strip()
    if not name:
        raise ContactError("the contact name is empty")
    if session.get(CounterpartyORM, counterparty_id) is None:
        raise ContactError(f"unknown counterparty {counterparty_id}")
    row = session.execute(
        select(CounterpartyContactORM).where(
            CounterpartyContactORM.counterparty_id == counterparty_id,
            CounterpartyContactORM.channel == channel,
        )
    ).scalar_one_or_none()
    if row is None:
        row = CounterpartyContactORM(
            counterparty_id=counterparty_id,
            channel=channel,
            contact_name=name,
            phone_e164=number,
            active=active,
            updated_at=_next_update_time(None),
        )
        session.add(row)
    else:
        row.contact_name = name
        row.phone_e164 = number
        row.active = active
        row.updated_at = _next_update_time(row.updated_at)
    session.commit()
    return row


def list_contacts(session: Session) -> list[ContactSummary]:
    rows = session.execute(
        select(CounterpartyContactORM).order_by(
            CounterpartyContactORM.counterparty_id, CounterpartyContactORM.channel
        )
    ).scalars()
    return [
        ContactSummary(
            counterparty_id=row.counterparty_id,
            contact_name=row.contact_name,
            channel=row.channel,
            masked_phone=mask_last2(row.phone_e164),
            active=row.active,
            updated_at=contact_version(row.updated_at),
        )
        for row in rows
    ]


def remove_contact(session: Session, counterparty_id: str, channel: str = WHATSAPP) -> bool:
    """Deletes the contact (the number is not kept). Its notices then route
    to the default again, and an Acknowledge to a notice sent to it no longer
    counts. Returns False if there was none. Commits."""
    row = session.execute(
        select(CounterpartyContactORM).where(
            CounterpartyContactORM.counterparty_id == counterparty_id,
            CounterpartyContactORM.channel == channel,
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    session.delete(row)
    session.commit()
    return True


# --- admin CLI --------------------------------------------------------------------


def _read_number(prompt: Callable[[str], str]) -> str:
    """Reads the number twice from a hidden prompt; never echoes it."""
    first = validate_e164(prompt("WhatsApp number in E.164 form (hidden): "))
    second = validate_e164(prompt("Repeat the number (hidden): "))
    if first != second:
        raise ContactError("the two entries differ")
    return first


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m persistence.contacts",
        description="Per-counterparty WhatsApp contacts (numbers are read from a hidden prompt).",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    set_cmd = commands.add_parser("set", help="add or replace a counterparty's contact")
    set_cmd.add_argument("--counterparty", required=True, help="e.g. CP-1")
    set_cmd.add_argument("--name", required=True, help="the contact's name")
    set_cmd.add_argument(
        "--inactive", action="store_true", help="store it disabled (notices use the default)"
    )
    commands.add_parser("list", help="list contacts (numbers masked)")
    remove_cmd = commands.add_parser("remove", help="delete a counterparty's contact")
    remove_cmd.add_argument("--counterparty", required=True)
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    session_factory: Callable[[], Session] | None = None,
    prompt: Callable[[str], str] = getpass.getpass,
) -> int:
    args = _parser().parse_args(argv)
    if session_factory is None:
        from config.settings import get_settings
        from persistence.db.engine import get_session_factory

        session_factory = get_session_factory(get_settings())

    try:
        with session_factory() as session:
            if args.command == "set":
                number = _read_number(prompt)
                row = set_contact(
                    session, args.counterparty, args.name, number, active=not args.inactive
                )
                state = "active" if row.active else "inactive"
                print(
                    f"Saved {args.counterparty} WhatsApp contact {row.contact_name} "
                    f"({mask_last2(number)}, {state})."
                )
            elif args.command == "list":
                contacts = list_contacts(session)
                if not contacts:
                    print("No contacts: every counterparty uses the WHATSAPP_RECIPIENT default.")
                for c in contacts:
                    state = "active" if c.active else "inactive"
                    print(
                        f"{c.counterparty_id}\t{c.channel}\t{c.contact_name}\t"
                        f"{c.masked_phone}\t{state}\tupdated {c.updated_at}"
                    )
            elif remove_contact(session, args.counterparty):
                print(f"Removed {args.counterparty}'s WhatsApp contact.")
            else:
                print(f"{args.counterparty} has no WhatsApp contact.")
    except ContactError as exc:
        print(f"Error: {exc}")
        return 2
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
