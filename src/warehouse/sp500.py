"""The S&P 500 universe of the simulated historical book (MM-140).

A committed snapshot (`warehouse/data/sp500_constituents.csv`) is the source,
so the backfill is reproducible: the same tickers and GICS sectors every run.
`python -m warehouse.sp500 --refresh` re-downloads Wikipedia's "List of S&P
500 companies" table and rewrites that one file (fixed path, never from
argv). Parsed with the standard library's HTML parser -- no lxml dependency.

Survivorship bias: these are the *current* constituents, back-tested over
five years. Companies that left the index in that window (acquired,
delisted, bankrupt) are missing, and companies added later are held before
they joined it. The warehouse README documents this.
"""

import argparse
import csv
import io
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

import httpx
from pydantic import BaseModel

SOURCE_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
SNAPSHOT_PATH = Path(__file__).resolve().parent / "data" / "sp500_constituents.csv"
COLUMNS = ["symbol", "security", "gics_sector", "gics_sub_industry", "date_added"]
USER_AGENT = "MarginMaestro/0.1 (portfolio project; S&P 500 snapshot)"


class Constituent(BaseModel):
    symbol: str  # Yahoo Finance form: BRK.B -> BRK-B
    security: str
    gics_sector: str
    gics_sub_industry: str
    date_added: str


class SnapshotError(ValueError):
    """The snapshot is missing, malformed or implausibly small."""


class _ConstituentsTable(HTMLParser):
    """Collects the cell text of the table with id="constituents"."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._depth = 0  # table nesting depth inside the constituents table
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            if self._depth or dict(attrs).get("id") == "constituents":
                self._depth += 1
            return
        if self._depth != 1:
            return
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "table" and self._depth:
            self._depth -= 1
            return
        if self._depth != 1:
            return
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def parse_wikipedia(html: str) -> list[Constituent]:
    parser = _ConstituentsTable()
    parser.feed(html)
    if not parser.rows:
        raise SnapshotError("no table with id 'constituents' in the page")
    header, *body = parser.rows
    try:
        index = {
            "symbol": header.index("Symbol"),
            "security": header.index("Security"),
            "gics_sector": header.index("GICS Sector"),
            "gics_sub_industry": header.index("GICS Sub-Industry"),
            "date_added": header.index("Date added"),
        }
    except ValueError as exc:
        raise SnapshotError(f"unexpected constituents header: {header}") from exc
    constituents = [
        Constituent(
            symbol=row[index["symbol"]].replace(".", "-"),
            security=row[index["security"]],
            gics_sector=row[index["gics_sector"]],
            gics_sub_industry=row[index["gics_sub_industry"]],
            date_added=row[index["date_added"]],
        )
        for row in body
        if len(row) >= len(header)
    ]
    _check(constituents)
    return constituents


def _check(constituents: list[Constituent]) -> None:
    symbols = [c.symbol for c in constituents]
    if len(symbols) < 450:
        raise SnapshotError(f"only {len(symbols)} constituents; expected about 500")
    if len(set(symbols)) != len(symbols):
        raise SnapshotError("duplicate symbols in the constituents list")


def to_csv(constituents: list[Constituent], fetched_on: str) -> str:
    out = io.StringIO()
    out.write(f"# source: {SOURCE_URL}\n# fetched: {fetched_on}\n")
    writer = csv.DictWriter(out, fieldnames=COLUMNS, lineterminator="\n")
    writer.writeheader()
    for constituent in constituents:
        writer.writerow(constituent.model_dump())
    return out.getvalue()


def parse_csv(text: str) -> list[Constituent]:
    lines = [line for line in text.splitlines() if not line.startswith("#")]
    reader = csv.DictReader(lines)
    if reader.fieldnames != COLUMNS:
        raise SnapshotError(f"unexpected snapshot columns: {reader.fieldnames}")
    constituents = [Constituent.model_validate(row) for row in reader]
    _check(constituents)
    return constituents


def snapshot_metadata(text: str) -> dict[str, str]:
    """The `# key: value` header lines (source and fetch date)."""
    meta = {}
    for line in text.splitlines():
        if not line.startswith("#"):
            break
        key, _, value = line.lstrip("# ").partition(":")
        meta[key.strip()] = value.strip()
    return meta


def load_constituents(path: Path = SNAPSHOT_PATH) -> list[Constituent]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SnapshotError(f"cannot read the S&P 500 snapshot at {path}: {exc}") from exc
    return parse_csv(text)


def sector_map(constituents: list[Constituent] | None = None) -> dict[str, str]:
    return {c.symbol: c.gics_sector for c in (constituents or load_constituents())}


def refresh_snapshot(client: httpx.Client | None = None) -> int:
    """Downloads the current list and rewrites the committed snapshot."""
    http = client or httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT})
    response = http.get(SOURCE_URL)
    response.raise_for_status()
    constituents = parse_wikipedia(response.text)
    SNAPSHOT_PATH.write_text(
        to_csv(constituents, datetime.now(UTC).date().isoformat()), encoding="utf-8"
    )
    return len(constituents)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="S&P 500 constituents snapshot (MM-140)")
    parser.add_argument(
        "--refresh", action="store_true", help="re-download from Wikipedia and rewrite the snapshot"
    )
    args = parser.parse_args(argv)
    if args.refresh:
        print(f"wrote {refresh_snapshot()} constituents to {SNAPSHOT_PATH.name}")
    else:
        constituents = load_constituents()
        meta = snapshot_metadata(SNAPSHOT_PATH.read_text(encoding="utf-8"))
        print(f"{len(constituents)} constituents, fetched {meta.get('fetched')}")


if __name__ == "__main__":
    main()
