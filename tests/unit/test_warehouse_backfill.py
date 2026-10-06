"""MM-140: the simulated book's backfill on a tiny hand-checked fixture --
3 tickers, 5 counterparties, 10 trading days -- asserting exact numbers
worked out by hand from the calc rules (VM, SIMM-proxy IM, thresholds with
rating triggers, MTA, call settlement and month-end returns)."""

import csv
import gzip
from datetime import date
from itertools import pairwise
from unittest.mock import MagicMock

import numpy as np
import pytest

from persistence.models import AssetClass, CounterpartyTier, CounterpartyType, RatingGrade
from warehouse import backfill
from warehouse.backfill import (
    Chunk,
    ChunkFiles,
    Inputs,
    Simulation,
    all_chunks,
    chunk_named,
    exposure_rows,
    logical_bytes,
    position_rows,
    write_chunks,
)
from warehouse.history import PriceMatrix
from warehouse.schemas import (
    FACT_DAILY_EXPOSURE,
    FACT_MARGIN_CALL,
    FACT_POSITION_DAILY,
    FACT_PRICE_DAILY,
    SIM_END_DATE,
    SIM_START_DATE,
    BookDateError,
)
from warehouse.simulated_book import (
    OPEN_END,
    CsaVersion,
    SimCounterparty,
    SimPosition,
    SimulatedBook,
)

NAN = float("nan")
# t0 is only the prior close; t3 (Jan 31) is a month end.
DATES = [
    date(2024, 1, 26),
    date(2024, 1, 29),
    date(2024, 1, 30),
    date(2024, 1, 31),
    date(2024, 2, 1),
    date(2024, 2, 2),
    date(2024, 2, 5),
    date(2024, 2, 6),
    date(2024, 2, 7),
    date(2024, 2, 8),
    date(2024, 2, 9),
]
A = [100, 110, 99, 120, 120, 120, 120, 120, 120, 120, 120]
B = [50, 45, 45, 45, 45, 45, 45, 45, 45, 45, 45]
C = [NAN, NAN, 10, 12, 12, 12, 12, 12, 12, 12, 12]  # first close at t2
VIX = [20, 20, 30, 40, 40, 40, 40, 40, 40, 40, 40]
HAIRCUTS = {"cash": 0.0, "treasury": 0.02, "corporate": None, "mmf": None}


def _prices() -> PriceMatrix:
    return PriceMatrix(
        dates=list(DATES),
        tickers=["A", "B", "C"],
        closes=np.array([A, B, C], dtype=float).T,
        vix=np.array(VIX, dtype=float),
    )


def _csa(threshold, mta, trigger=RatingGrade.B, version=1, start=DATES[0], end=OPEN_END):
    return CsaVersion(version, start, end, threshold, mta, trigger, 0.0, HAIRCUTS, "initial")


def _cp(index, csa, rating=RatingGrade.A, tier=CounterpartyTier.STANDARD, factor=1.0):
    return SimCounterparty(
        index=index,
        id=f"SIM-{index + 1:04d}",
        name=f"SIM Test Capital {index + 1:04d}",
        type=CounterpartyType.HEDGE_FUND,
        country="Ireland",
        tier=tier,
        ratings=[(DATES[0], rating)],
        csa_versions=csa if isinstance(csa, list) else [csa],
        collateral_factor=factor,
    )


def _pos(cp, n, ticker, qty):
    return SimPosition(f"SIM-{cp + 1:04d}-P{n:03d}", cp, ticker, AssetClass.EQUITY, float(qty))


def _book() -> SimulatedBook:
    return SimulatedBook(
        counterparties=[
            _cp(0, _csa(100_000, 100)),
            # CCC is below the B trigger: threshold 200,000 -> 0.
            _cp(1, _csa(200_000, 1_000), rating=RatingGrade.CCC, factor=0.5),
            _cp(2, _csa(50_000, 10_000)),
            # Renegotiated on Jan 31: threshold 500,000 -> 0.
            _cp(
                3,
                [
                    _csa(500_000, 1_000, end=date(2024, 1, 30)),
                    _csa(0, 1_000, version=2, start=date(2024, 1, 31)),
                ],
            ),
            _cp(4, _csa(0, 1_000), tier=CounterpartyTier.ELITE),
        ],
        positions=[
            _pos(0, 1, "A", 10_000),
            _pos(1, 1, "B", -5_000),
            _pos(2, 1, "A", 1_000),
            _pos(2, 2, "C", 2_000),
            _pos(3, 1, "B", 100),
            _pos(4, 1, "B", 10_000),
        ],
    )


@pytest.fixture(autouse=True)
def _every_sla_met(monkeypatch):
    # Lifecycle draws are random; make settlement deterministic: always T+1.
    monkeypatch.setattr(
        backfill,
        "SLA_MET_CHANCE",
        {CounterpartyTier.STANDARD: 1.0, CounterpartyTier.ELITE: 1.0},
    )


def _days():
    return {day.as_of: day for day in Simulation(_book(), _prices()).days()}


# --- the numbers, by hand ------------------------------------------------------------


def test_day_one_exposure_threshold_and_opening_collateral():
    day = _days()[DATES[1]]

    # CP0, 10,000 A, 100 -> 110, VIX 20 (multiplier 1.0).
    assert day.variation_margin[0] == 10_000 * 110 - 10_000 * 100  # 100,000
    assert day.initial_margin[0] == pytest.approx(0.15 * 1_100_000 * 1.0)  # 165,000
    assert day.exposure[0] == pytest.approx(265_000)
    # Opening collateral = factor x required = 1.0 x (265,000 - 100,000).
    assert day.collateral[0] == pytest.approx(165_000)
    assert not day.breached[0]

    # CP1, short 5,000 B, 50 -> 45: VM +25,000, IM 0.15 x 225,000 = 33,750.
    assert day.exposure[1] == pytest.approx(25_000 + 33_750)
    # Rated CCC, below the B trigger: the threshold falls to 0.
    assert day.threshold[1] == 0.0
    # Opening collateral 0.5 x 58,750 = 29,375 -> short 29,375 >= MTA 1,000.
    assert day.collateral[1] == pytest.approx(29_375)
    assert day.breached[1] and day.call_raised[1]
    assert day.call_due[1] == pytest.approx(29_375)

    # CP2 holds C, which has no prior close yet: only the A position counts.
    assert day.exposure[2] == pytest.approx(1_000 * 10 + 0.15 * 110_000)
    # Below its 50,000 threshold: nothing required, the 10,000 floor applies.
    assert day.required[2] == 0.0
    assert day.collateral[2] == pytest.approx(10_000)


def test_a_volatility_jump_breaches_and_the_call_settles_next_day():
    days = _days()
    d2, d3, d4 = days[DATES[2]], days[DATES[3]], days[DATES[4]]

    # Day 2: A 110 -> 99, VIX 30 (x1.5): VM -110,000, IM 0.15 x 990,000 x 1.5.
    assert d2.exposure[0] == pytest.approx(-110_000 + 222_750)
    assert not d2.breached[0]

    # Day 3: A 99 -> 120, VIX 40 (x2.0): VM 210,000, IM 360,000 -> 570,000.
    assert d3.exposure[0] == pytest.approx(570_000)
    assert d3.required[0] == pytest.approx(470_000)
    assert d3.call_due[0] == pytest.approx(470_000 - 165_000)  # 305,000
    assert d3.call_raised[0]

    # Day 4: the 305,000 was delivered; A flat, VIX 40: exposure = IM 360,000.
    assert d4.collateral[0] == pytest.approx(165_000 + 305_000)
    assert d4.exposure[0] == pytest.approx(360_000)
    assert not d4.breached[0]


def test_a_ticker_enters_on_its_second_priced_day():
    d3 = _days()[DATES[3]]

    # CP2: A 99 -> 120 and C 10 -> 12 (C first priced at t2), VIX 40.
    assert d3.variation_margin[2] == pytest.approx(1_000 * 21 + 2_000 * 2)
    assert d3.initial_margin[2] == pytest.approx((0.15 * 120_000 + 0.15 * 24_000) * 2.0)


def test_an_open_call_blocks_a_second_one_until_settled():
    days = _days()

    # CP1 is called on day 1 (29,375) and settles on day 2; on day 2 it is
    # short again only if exposure rose -- B is flat, VIX 30 lifts IM:
    # IM 0.15 x 225,000 x 1.5 = 50,625, VM 0 -> required 50,625;
    # collateral 29,375 + 29,375 = 58,750 covers it.
    d2 = days[DATES[2]]
    assert d2.collateral[1] == pytest.approx(58_750)
    assert not d2.breached[1]
    # Day 3: VIX 40 -> IM 67,500 > 58,750 by 8,750 >= MTA: a new call.
    d3 = days[DATES[3]]
    assert d3.call_due[1] == pytest.approx(67_500 - 58_750)
    assert d3.call_raised[1]


def test_breach_without_call_while_the_previous_call_is_open(monkeypatch):
    # SLA missed -> settlement two days later, so the day after the call the
    # breach stands but no second call is raised.
    monkeypatch.setattr(
        backfill, "SLA_MET_CHANCE", {CounterpartyTier.STANDARD: 0.0, CounterpartyTier.ELITE: 0.0}
    )
    days = _days()
    d1, d2, d3 = days[DATES[1]], days[DATES[2]], days[DATES[3]]
    assert d1.call_raised[1]
    assert d2.breached[1] and not d2.call_raised[1]
    assert d3.collateral[1] == pytest.approx(29_375 * 2)  # delivered on t3
    escalated = d1.calls[0]
    assert not escalated.sla_met
    assert (escalated.resolved_at - escalated.notified_at).total_seconds() == 3600


def test_csa_renegotiation_changes_the_version_and_threshold():
    days = _days()
    d2, d3 = days[DATES[2]], days[DATES[3]]
    assert (int(d2.csa_version[3]), d2.threshold[3]) == (1, 500_000)
    assert (int(d3.csa_version[3]), d3.threshold[3]) == (2, 0.0)


def test_month_end_returns_excess_collateral():
    book = SimulatedBook(
        counterparties=[_cp(0, _csa(0, 1_000), factor=5.0)],
        positions=[_pos(0, 1, "B", 1_000)],
    )
    prices = _prices().slice_dates(date(2024, 1, 30), date(2024, 2, 1))
    days = list(Simulation(book, prices).days())
    jan31, feb1 = days
    # Jan 31: B flat, VIX 40 -> exposure = IM = 0.15 x 45,000 x 2 = 13,500.
    assert jan31.required[0] == pytest.approx(13_500)
    assert jan31.collateral[0] == pytest.approx(5 * 13_500)
    # Month end: the 54,000 excess (>= MTA) is returned -> Feb 1 holds 13,500.
    assert feb1.collateral[0] == pytest.approx(13_500)


def test_elite_calls_carry_the_managers_second_signature():
    calls = [c for d in _days().values() for c in d.calls]
    elite = [c for c in calls if c.counterparty_index == 4]
    standard = [c for c in calls if c.counterparty_index != 4]
    assert elite and all(c.manager_approved_at is not None for c in elite)
    assert all(c.manager_approved_at is None for c in standard)
    for call in calls:
        assert call.raised_at < call.approved_at < call.notified_at < call.resolved_at
        # 16:45 New York is 21:45 UTC in winter.
        assert (call.raised_at.hour, call.raised_at.minute) == (21, 45)


def test_simulation_is_deterministic():
    first = [c.approved_at for d in _days().values() for c in d.calls]
    second = [c.approved_at for d in _days().values() for c in d.calls]
    assert first == second


# --- rows -----------------------------------------------------------------------------


def test_exposure_rows_match_the_schema_and_the_numbers():
    sim = Simulation(_book(), _prices())
    day = next(d for d in sim.days() if d.as_of == DATES[3])
    rows = list(exposure_rows(sim, day))
    assert len(rows) == 5
    row = dict(zip(FACT_DAILY_EXPOSURE.column_names, rows[0], strict=True))
    assert row["book"] == "historical-sim"
    assert row["counterparty_id"] == "SIM-0001"
    assert row["exposure"] == pytest.approx(570_000)
    assert row["headroom"] == pytest.approx(100_000 + 165_000 - 570_000)
    assert row["call_due"] == pytest.approx(305_000)
    assert row["breached"] is True and row["call_raised"] is True
    assert row["rating"] == "A" and row["csa_version"] == 1


def test_position_rows_skip_unpriced_positions():
    sim = Simulation(_book(), _prices())
    days = {d.as_of: d for d in sim.days()}
    assert "C" not in {r[4] for r in position_rows(sim, days[DATES[1]])}
    rows = {r[3]: r for r in position_rows(sim, days[DATES[3]])}
    assert rows["SIM-0003-P002"][6:] == (2_000, 12.0, 24_000.0)


def test_fast_position_writer_matches_the_reference_rows(tmp_path):
    sim = Simulation(_book(), _prices())
    day = next(d for d in sim.days() if d.as_of == DATES[3])
    files = ChunkFiles(Chunk("2024-Q1", date(2024, 1, 1), date(2024, 3, 31)), tmp_path)
    files.write_positions(sim, day)
    files.close()
    with gzip.open(files.paths[FACT_POSITION_DAILY.name], "rt", encoding="utf-8") as handle:
        written = list(csv.reader(handle))[1:]
    reference = [[backfill._fmt(v) for v in row] for row in position_rows(sim, day)]
    assert written == reference
    expected_bytes = sum(logical_bytes(FACT_POSITION_DAILY, r) for r in position_rows(sim, day))
    assert files.stats[FACT_POSITION_DAILY.name].logical_bytes == expected_bytes


def test_logical_bytes_follow_bigquerys_sizes():
    row = (date(2024, 1, 2), "live", "abc", "XY")
    table = FACT_PRICE_DAILY.model_copy(
        update={"columns": FACT_PRICE_DAILY.columns[:4]}
    )  # date, book, symbol, kind
    assert logical_bytes(table, row) == 8 + (2 + 4) + (2 + 3) + (2 + 2)
    assert logical_bytes(table, (None, "", "a", "b")) == 0 + 2 + 3 + 3


def test_call_rows_use_the_code_rationale():
    sim = Simulation(_book(), _prices())
    day = next(d for d in sim.days() if d.as_of == DATES[3])
    call = next(c for c in day.calls if c.counterparty_index == 0)
    row = dict(zip(FACT_MARGIN_CALL.column_names, backfill.call_row(sim, call), strict=True))
    assert row["call_id"] == "SIM-0001:2024-01-31"
    assert row["trigger_type"] == "daily_margin_run"
    assert row["call_amount"] == pytest.approx(305_000)
    assert row["rationale"].startswith(
        "Daily margin run (simulated). Your exposure of USD 570,000.00"
    )
    assert row["sla_outcome"] == "met" and row["status"] == "sla_met"
    assert row["escalated_at"] is None and row["acknowledged_at"] is not None


def test_price_rows_include_vix_and_fred_rates():
    prices = _prices()
    rows = list(backfill.price_rows(prices, 1, {"DGS10": {DATES[1]: 4.1}}))
    symbols = [r[2] for r in rows]
    assert symbols == ["A", "B", "^VIX", "DGS10"]  # C has no close on t1
    assert rows[-1][3:] == ("rate", 4.1, "fred")


def test_dimension_rows():
    book = _book()
    counterparties = list(backfill.counterparty_rows(book))
    assert counterparties[1][2:] == (
        "SIM-0002", "SIM Test Capital 0002", "Hedge Fund", "Ireland", "standard", "CCC",
    )  # fmt: skip
    csa = list(backfill.csa_rows(book))
    renegotiated = [r for r in csa if r[2] == "SIM-0004"]
    assert [(r[3], r[6]) for r in renegotiated] == [(1, False), (2, True)]


# --- chunks -----------------------------------------------------------------------------


def test_chunks_cover_the_window_by_quarter():
    chunks = all_chunks()
    assert chunks[0] == Chunk("2021-Q3", SIM_START_DATE, date(2021, 9, 30))
    assert chunks[-1] == Chunk("2026-Q3", date(2026, 7, 1), SIM_END_DATE)
    assert len(chunks) == 21
    for before, after in pairwise(chunks):
        assert (after.start - before.end).days == 1


@pytest.mark.parametrize("name", ["2024-q1", "2024-Q5", "../x", "2020-Q1", "2027-Q1"])
def test_bad_chunk_names_are_refused(name):
    with pytest.raises(ValueError):
        chunk_named(name)


def test_write_chunks_streams_only_the_requested_chunk(tmp_path):
    inputs = Inputs(_book(), _prices(), {}, {})
    chunk = Chunk("2024-Q1", date(2024, 2, 1), date(2024, 2, 5))
    [files] = list(write_chunks(inputs, [chunk], tmp_path))
    assert files.stats[FACT_DAILY_EXPOSURE.name].rows == 3 * 5
    with gzip.open(files.paths[FACT_DAILY_EXPOSURE.name], "rt", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert {r["as_of_date"] for r in rows} == {"2024-02-01", "2024-02-02", "2024-02-05"}
    files.remove()
    assert not any(p.exists() for p in files.paths.values())


def test_rewriting_a_chunk_gives_identical_files(tmp_path):
    inputs = Inputs(_book(), _prices(), {}, {})
    chunk = Chunk("2024-Q1", DATES[1], DATES[-1])
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first = list(write_chunks(inputs, [chunk], tmp_path / "a"))
    second = list(write_chunks(inputs, [chunk], tmp_path / "b"))
    for table in (FACT_DAILY_EXPOSURE, FACT_POSITION_DAILY, FACT_MARGIN_CALL):
        with (
            gzip.open(first[0].paths[table.name], "rt") as a,
            gzip.open(second[0].paths[table.name], "rt") as b,
        ):
            assert a.read() == b.read()


def test_a_chunk_outside_the_simulated_window_is_refused(tmp_path):
    inputs = Inputs(_book(), _prices(), {}, {})
    with pytest.raises(BookDateError):
        list(write_chunks(inputs, [Chunk("x", date(2026, 8, 1), date(2026, 9, 30))], tmp_path))


def test_load_chunk_replaces_each_fact_then_refreshes(tmp_path, monkeypatch):
    inputs = Inputs(_book(), _prices(), {}, {})
    chunk = Chunk("2024-Q1", DATES[1], DATES[-1])
    [files] = list(write_chunks(inputs, [chunk], tmp_path))
    client = MagicMock()
    refresh = MagicMock()
    monkeypatch.setattr(backfill, "refresh_reports", refresh)
    backfill.load_chunk(client, files)
    tables = [call.args[0].name for call in client.replace_file.call_args_list]
    assert tables == [t.name for t in backfill.FACT_TABLES]
    assert all(
        call.args[1:3] == (chunk.start, chunk.end) for call in client.replace_file.call_args_list
    )
    refresh.assert_called_once_with(client, chunk.start, chunk.end)


def test_load_dims_writes_both_partitions_and_the_calendar():
    inputs = Inputs(_book(), _prices(), {}, {})
    client = MagicMock()
    stats = backfill.load_dims(client, inputs)
    assert stats["dim_counterparty"].rows == 5
    assert stats["dim_date"].rows == 3652
    replaced = {call.args[0].name: call.args[1:3] for call in client.replace.call_args_list}
    assert replaced == {
        "dim_counterparty": (0, 0),
        "dim_instrument": (0, 0),
        "dim_csa_terms": (0, 0),
    }
    client.overwrite_unpartitioned.assert_called_once()
    assert backfill.load_dims(None, inputs)["dim_csa_terms"].rows == 6


def test_dry_run_prints_sizes_and_loads_nothing(monkeypatch, capsys):
    inputs = Inputs(_book(), _prices(), {}, {})
    monkeypatch.setattr(backfill, "prepare_inputs", lambda seed: inputs)
    client_class = MagicMock()
    monkeypatch.setattr(backfill, "WarehouseClient", client_class)
    backfill.main(["--dims", "--dry-run"])
    out = capsys.readouterr().out
    assert "dim_date" in out and "rows=" in out
    client_class.assert_not_called()


def test_dry_run_of_a_chunk(monkeypatch, capsys):
    inputs = Inputs(_book(), _prices(), {}, {})
    monkeypatch.setattr(backfill, "prepare_inputs", lambda seed: inputs)
    backfill.main(["--chunk", "2024-Q1", "--dry-run"])
    out = capsys.readouterr().out
    assert "chunk 2024-Q1" in out and "dry run" in out
    assert "fact_position_daily" in out


def test_a_real_run_needs_a_project(monkeypatch):
    inputs = Inputs(_book(), _prices(), {}, {})
    monkeypatch.setattr(backfill, "prepare_inputs", lambda seed: inputs)
    monkeypatch.setattr(backfill, "get_settings", lambda: MagicMock(gcp_project_id=None))
    with pytest.raises(SystemExit):
        backfill.main(["--chunk", "2024-Q1"])


def test_a_real_run_loads_dims_and_chunks(monkeypatch, capsys):
    inputs = Inputs(_book(), _prices(), {}, {})
    monkeypatch.setattr(backfill, "prepare_inputs", lambda seed: inputs)
    monkeypatch.setattr(backfill, "get_settings", lambda: MagicMock(gcp_project_id="p"))
    client = MagicMock()
    monkeypatch.setattr(backfill, "WarehouseClient", lambda project: client)
    monkeypatch.setattr(backfill, "all_chunks", lambda: [Chunk("2024-Q1", DATES[1], DATES[-1])])
    monkeypatch.setattr(backfill, "refresh_reports", MagicMock())
    backfill.main(["--all"])
    assert client.replace_file.call_count == 4
    assert "[loaded]" in capsys.readouterr().out


def test_list_prints_the_chunks(capsys):
    backfill.main(["--list"])
    assert "2021-Q3" in capsys.readouterr().out


def test_bad_chunk_on_the_command_line_exits():
    with pytest.raises(SystemExit):
        backfill.main(["--chunk", "Q1-2024"])
