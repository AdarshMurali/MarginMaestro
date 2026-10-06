"""Dimension rows shared by the backfill and the live load (MM-139/140/141)."""

import calendar
from collections.abc import Iterator
from datetime import date, timedelta

from persistence.generators.securities import CRYPTO_TICKERS, ETF_TICKERS, asset_class_for
from persistence.models import AssetClass
from warehouse.schemas import BOOK_KEY, Book
from warehouse.sp500 import Constituent

CALENDAR_START = date(2021, 1, 1)
CALENDAR_END = date(2030, 12, 31)


def dim_date_rows(start: date = CALENDAR_START, end: date = CALENDAR_END) -> Iterator[tuple]:
    day = start
    while day <= end:
        quarter = (day.month - 1) // 3 + 1
        last = calendar.monthrange(day.year, day.month)[1]
        yield (
            day,
            day.year,
            quarter,
            day.month,
            day.isoweekday(),
            day.isoweekday() <= 5,
            day.day == last,
            f"{day.year}-Q{quarter}",
            f"{day.year}-{day.month:02d}",
        )
        day += timedelta(days=1)


def sector_for(ticker: str, constituents: dict[str, Constituent]) -> str:
    if ticker in constituents:
        return constituents[ticker].gics_sector
    if ticker in ETF_TICKERS:
        return "ETF"
    if ticker in CRYPTO_TICKERS:
        return "Crypto"
    return "Unknown"


def instrument_rows(
    book: Book, tickers: list[str], constituents: dict[str, Constituent]
) -> Iterator[tuple]:
    for ticker in sorted(set(tickers)):
        c = constituents.get(ticker)
        asset_class = AssetClass.EQUITY if c is not None else asset_class_for(ticker)
        yield (
            BOOK_KEY[book],
            book.value,
            ticker,
            c.security if c else None,
            asset_class.value,
            sector_for(ticker, constituents),
            c.gics_sub_industry if c else None,
            c is not None,
        )
