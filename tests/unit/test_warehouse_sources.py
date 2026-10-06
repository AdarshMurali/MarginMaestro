"""MM-140: the simulated book's inputs -- the S&P 500 snapshot, the price
history download/cache, and the synthetic book generator."""

from datetime import date
from itertools import pairwise
from unittest.mock import MagicMock

import numpy as np
import pytest

from persistence.models import CounterpartyTier
from warehouse import history, sp500
from warehouse.dims import dim_date_rows, instrument_rows, sector_for
from warehouse.history import (
    HistoryError,
    build_matrix,
    download_closes,
    load_cache,
    load_history,
    save_cache,
)
from warehouse.schemas import Book
from warehouse.simulated_book import (
    BASE_THRESHOLD,
    MTA_RANGE,
    OPEN_END,
    generate_book,
    generate_counterparty,
)
from warehouse.sp500 import Constituent, SnapshotError

# --- S&P 500 snapshot ----------------------------------------------------------------


def _page(rows: int) -> str:
    body = "".join(
        f"<tr><td><a>T{i}.B</a></td><td>Co {i}</td><td>Sector {i % 11}</td>"
        f"<td>Sub {i}</td><td>X, Y</td><td>2001-01-0{i % 9 + 1}</td><td>1</td><td>1900</td></tr>"
        for i in range(rows)
    )
    return (
        '<table id="other"><tr><td>ignored</td></tr></table>'
        '<table class="wikitable" id="constituents"><tbody><tr><th>Symbol</th><th>Security</th>'
        "<th>GICS Sector</th><th>GICS Sub-Industry</th><th>Headquarters Location</th>"
        f"<th>Date added</th><th>CIK</th><th>Founded</th></tr>{body}</tbody></table>"
    )


def test_wikipedia_table_is_parsed_into_yahoo_symbols():
    constituents = sp500.parse_wikipedia(_page(460))
    assert len(constituents) == 460
    assert constituents[0] == Constituent(
        symbol="T0-B",
        security="Co 0",
        gics_sector="Sector 0",
        gics_sub_industry="Sub 0",
        date_added="2001-01-01",
    )


def test_a_page_without_the_table_or_with_too_few_rows_fails():
    with pytest.raises(SnapshotError, match="no table"):
        sp500.parse_wikipedia("<html></html>")
    with pytest.raises(SnapshotError, match="expected about 500"):
        sp500.parse_wikipedia(_page(10))
    with pytest.raises(SnapshotError, match="header"):
        sp500.parse_wikipedia(_page(460).replace("GICS Sector", "Sector"))


def test_csv_round_trip_keeps_source_and_date():
    constituents = sp500.parse_wikipedia(_page(460))
    text = sp500.to_csv(constituents, "2026-10-06")
    assert sp500.parse_csv(text) == constituents
    assert sp500.snapshot_metadata(text) == {"source": sp500.SOURCE_URL, "fetched": "2026-10-06"}


def test_duplicate_symbols_fail():
    constituents = sp500.parse_wikipedia(_page(460))
    with pytest.raises(SnapshotError, match="duplicate"):
        sp500.parse_csv(sp500.to_csv(constituents + constituents[:1], "x"))
    with pytest.raises(SnapshotError, match="columns"):
        sp500.parse_csv("a,b\n1,2\n")


def test_the_committed_snapshot():
    constituents = sp500.load_constituents()
    assert 495 <= len(constituents) <= 510
    symbols = {c.symbol for c in constituents}
    assert {"AAPL", "MSFT", "BRK-B"} <= symbols
    assert sp500.sector_map(constituents)["AAPL"] == "Information Technology"
    meta = sp500.snapshot_metadata(sp500.SNAPSHOT_PATH.read_text(encoding="utf-8"))
    assert meta["source"].startswith("https://en.wikipedia.org/")


def test_missing_snapshot_fails_loud(tmp_path):
    with pytest.raises(SnapshotError, match="cannot read"):
        sp500.load_constituents(tmp_path / "none.csv")


def test_refresh_writes_the_fixed_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(sp500, "SNAPSHOT_PATH", tmp_path / "snap.csv")
    http = MagicMock()
    http.get.return_value.text = _page(460)
    assert sp500.refresh_snapshot(http) == 460
    assert len(sp500.load_constituents(tmp_path / "snap.csv")) == 460


def test_sp500_cli(monkeypatch, capsys):
    sp500.main([])
    assert "constituents, fetched" in capsys.readouterr().out
    monkeypatch.setattr(sp500, "refresh_snapshot", lambda: 7)
    sp500.main(["--refresh"])
    assert "wrote 7" in capsys.readouterr().out


# --- price history -------------------------------------------------------------------------


D1, D2, D3, D4 = date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 4), date(2024, 1, 5)


def test_downloads_in_batches_and_retries_the_missing(monkeypatch):
    monkeypatch.setattr(history, "BATCH_SIZE", 2)
    calls = []

    def downloader(tickers, start, end):
        calls.append(list(tickers))
        if len(calls) == 1:
            raise RuntimeError("rate limited")
        return {t: {D1: 1.0} for t in tickers if t != "C" or len(calls) > 3}

    result = download_closes(["A", "B", "C"], D1, D2, downloader, sleep=lambda s: None)
    assert set(result) == {"A", "B", "C"}
    assert calls[0] == ["A", "B"] and calls[1] == ["A", "B"]
    assert calls[2:] == [["C"], ["C"]]


def test_tickers_that_never_download_are_left_out():
    result = download_closes(["A"], D1, D2, lambda t, s, e: {}, sleep=lambda s: None)
    assert result == {}


def test_matrix_alignment_and_forward_fill():
    closes = {
        "A": {D1: 1.0, D2: 2.0, D4: 4.0},  # D3 missing -> filled with 2.0
        "B": {D1: 10.0, D2: 11.0, D3: 12.0, D4: 13.0},
        "LATE": {D3: 5.0, D4: 6.0},  # listed later: earlier days stay NaN
    }
    vix = {D1: 20.0, D2: 21.0, D3: 22.0, D4: 23.0}
    matrix = build_matrix(closes, ["A", "B", "LATE", "NONE"], vix)
    assert matrix.tickers == ["A", "B", "LATE"]
    assert matrix.dates == [D1, D2, D3, D4]
    assert list(matrix.column("A")) == [1.0, 2.0, 2.0, 4.0]
    assert np.isnan(matrix.column("LATE")[:2]).all()
    assert list(matrix.vix) == [20.0, 21.0, 22.0, 23.0]
    sliced = matrix.slice_dates(D2, D3)
    assert sliced.dates == [D2, D3] and sliced.closes.shape == (2, 3)


def test_forward_fill_stops_after_the_limit(monkeypatch):
    monkeypatch.setattr(history, "MAX_FILL_DAYS", 1)
    closes = {"A": {D1: 1.0}, "B": {D: 1.0 for D in (D1, D2, D3, D4)}}
    matrix = build_matrix(closes, ["A", "B"], {D: 20.0 for D in (D1, D2, D3, D4)})
    column = matrix.column("A")
    assert column[1] == 1.0 and np.isnan(column[2])


def test_dates_without_vix_or_enough_closes_are_dropped():
    closes = {"A": {D1: 1.0, D2: 2.0}, "B": {D1: 1.0}}
    matrix = build_matrix(closes, ["A", "B"], {D1: 20.0})
    assert matrix.dates == [D1]
    with pytest.raises(HistoryError):
        build_matrix({}, ["A"], {D1: 20.0})
    with pytest.raises(HistoryError):
        build_matrix({"A": {D1: 1.0}}, ["A"], {D2: 20.0})


def test_cache_round_trip_and_load_history(tmp_path):
    path = tmp_path / "closes.csv.gz"
    closes = {"A": {D1: 1.5, D2: 1.25}, history.VIX_SYMBOL: {D1: 20.0, D2: 21.0}}
    save_cache(path, closes)
    assert load_cache(path) == closes
    matrix = load_history(["A"], D1, D2, downloader=MagicMock(), cache=path)
    assert list(matrix.column("A")) == [1.5, 1.25]


def test_load_history_downloads_once_then_caches(tmp_path):
    path = tmp_path / "c.csv.gz"
    downloader = MagicMock(return_value={"A": {D1: 1.0}, history.VIX_SYMBOL: {D1: 20.0}})
    load_history(["A"], D1, D1, downloader=downloader, cache=path)
    load_history(["A"], D1, D1, downloader=downloader, cache=path)
    downloader.assert_called_once()
    assert history.cache_path(D1, D2).name == "closes_20240102_20240103.csv.gz"


def test_no_vix_is_fatal(tmp_path, monkeypatch):
    monkeypatch.setattr(history.time, "sleep", lambda s: None)
    with pytest.raises(HistoryError, match="VIX"):
        load_history(
            ["A"], D1, D1, downloader=lambda t, s, e: {"A": {D1: 1.0}}, cache=tmp_path / "x.gz"
        )


def test_fred_rates_are_skipped_without_a_key(monkeypatch):
    settings = MagicMock(fred_api_key=None)
    assert history.fetch_fred_rates(D1, D2, settings) == {}


def test_fred_rates_with_a_key(monkeypatch):
    from persistence import fred_feed

    feed = MagicMock()
    observation = fred_feed.RateObservation(series_id="DGS10", date=D1, value=4.2)

    def series(series_id, start, end):
        if series_id == "SOFR":
            raise fred_feed.RateDataUnavailableError("down")
        return [observation]

    feed.get_series.side_effect = series
    monkeypatch.setattr(fred_feed, "FredFeed", lambda settings: feed)
    rates = history.fetch_fred_rates(D1, D2, MagicMock())
    assert "SOFR" not in rates and rates["DGS10"] == {D1: 4.2}


# --- the simulated book ----------------------------------------------------------------------

START, END = date(2021, 8, 1), date(2026, 7, 31)


def test_counterparties_are_deterministic_and_clearly_synthetic():
    first = generate_counterparty(41, 7, START, END)
    again = generate_counterparty(41, 7, START, END)
    assert first == again
    assert first.id == "SIM-0042"
    assert first.name.startswith("SIM ") and first.name.endswith("0042")


def test_csa_terms_are_shaped_like_the_seeded_csas():
    book = [generate_counterparty(i, 3, START, END) for i in range(300)]
    for cp in book:
        versions = cp.csa_versions
        assert versions[0].valid_from == START and versions[-1].valid_to == OPEN_END
        for before, after in pairwise(versions):
            assert (after.valid_from - before.valid_to).days == 1
        for v in versions:
            assert v.threshold % 5_000 == 0 and v.mta % 1_000 == 0
            assert 5_000 <= v.threshold <= 1.4 * 1.25 * 1.25**5 * max(BASE_THRESHOLD.values())
            assert v.trigger_threshold == 0.0
            assert any(h is not None for h in v.haircuts.values())
        assert MTA_RANGE[0] <= versions[0].mta <= MTA_RANGE[1]
    elite = sum(cp.tier is CounterpartyTier.ELITE for cp in book) / len(book)
    assert 0.08 < elite < 0.25
    assert any(len(cp.csa_versions) > 1 for cp in book)
    assert any(len(cp.ratings) > 1 for cp in book)


def test_ratings_and_terms_by_date():
    cp = next(
        c
        for c in (generate_counterparty(i, 3, START, END) for i in range(200))
        if len(c.ratings) > 1 and len(c.csa_versions) > 1
    )
    changed_on, grade = cp.ratings[1]
    assert cp.rating_on(changed_on) == grade
    assert cp.rating_on(START) == cp.ratings[0][1]
    second = cp.csa_versions[1]
    assert cp.csa_on(second.valid_from) == second
    assert cp.csa_on(date(2000, 1, 1)) == cp.csa_versions[0]


def test_positions_are_sized_on_the_first_close():
    tickers = ["A", "B", "C", "D"]
    book = generate_book(
        tickers, {"A": 10.0, "B": 100.0, "C": 1_000.0}, START, END, seed=1, count=20
    )
    assert len(book.counterparties) == 20
    assert {p.ticker for p in book.positions} <= {"A", "B", "C"}  # D is unpriced
    for p in book.positions:
        assert p.quantity != 0
        notional = abs(p.quantity) * {"A": 10.0, "B": 100.0, "C": 1_000.0}[p.ticker]
        assert notional <= 250_000 * 1.5 + 1_000
    ids = [p.position_id for p in book.positions]
    assert len(ids) == len(set(ids))


# --- dimensions ------------------------------------------------------------------------------


def test_calendar_rows():
    rows = list(dim_date_rows(date(2024, 1, 31), date(2024, 2, 3)))
    assert rows[0] == (date(2024, 1, 31), 2024, 1, 1, 3, True, True, "2024-Q1", "2024-01")
    assert rows[-1][4:6] == (6, False)


def test_instrument_rows_and_sectors():
    constituents = {
        "AAPL": Constituent(
            symbol="AAPL",
            security="Apple",
            gics_sector="Information Technology",
            gics_sub_industry="Hardware",
            date_added="1982",
        )
    }
    rows = {
        r[2]: r for r in instrument_rows(Book.LIVE, ["AAPL", "SPY", "BTC-USD", "ZZZ"], constituents)
    }
    assert rows["AAPL"] == (
        1,
        "live",
        "AAPL",
        "Apple",
        "equity",
        "Information Technology",
        "Hardware",
        True,
    )
    assert rows["SPY"][4:6] == ("etf", "ETF")
    assert rows["BTC-USD"][4:6] == ("crypto", "Crypto")
    assert sector_for("ZZZ", constituents) == "Unknown"
