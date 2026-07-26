from datetime import date, datetime

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class CounterpartyORM(Base):
    __tablename__ = "counterparties"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    type: Mapped[str] = mapped_column(String(50))
    country: Mapped[str] = mapped_column(String(100))

    portfolios: Mapped[list["PortfolioORM"]] = relationship(
        back_populates="counterparty", cascade="all, delete-orphan"
    )
    ratings: Mapped[list["RatingORM"]] = relationship(
        back_populates="counterparty", cascade="all, delete-orphan"
    )
    collateral_items: Mapped[list["CollateralItemORM"]] = relationship(
        back_populates="counterparty", cascade="all, delete-orphan"
    )
    tickets: Mapped[list["TicketORM"]] = relationship(
        back_populates="counterparty", cascade="all, delete-orphan"
    )


class PortfolioORM(Base):
    __tablename__ = "portfolios"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    counterparty_id: Mapped[str] = mapped_column(ForeignKey("counterparties.id"))
    currency: Mapped[str] = mapped_column(String(10), default="USD")

    counterparty: Mapped["CounterpartyORM"] = relationship(back_populates="portfolios")
    positions: Mapped[list["PositionORM"]] = relationship(
        back_populates="portfolio", cascade="all, delete-orphan"
    )


class PositionORM(Base):
    __tablename__ = "positions"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(ForeignKey("portfolios.id"))
    ticker: Mapped[str] = mapped_column(String(20))
    asset_class: Mapped[str] = mapped_column(String(20))
    quantity: Mapped[float]
    trade_date: Mapped[date]

    portfolio: Mapped["PortfolioORM"] = relationship(back_populates="positions")


class RatingORM(Base):
    __tablename__ = "ratings"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    counterparty_id: Mapped[str] = mapped_column(ForeignKey("counterparties.id"))
    grade: Mapped[str] = mapped_column(String(5))
    rating_date: Mapped[date]

    counterparty: Mapped["CounterpartyORM"] = relationship(back_populates="ratings")


class CollateralItemORM(Base):
    __tablename__ = "collateral_items"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    counterparty_id: Mapped[str] = mapped_column(ForeignKey("counterparties.id"))
    collateral_type: Mapped[str] = mapped_column(String(20))
    ticker: Mapped[str | None] = mapped_column(String(20), nullable=True)
    value_usd: Mapped[float]
    haircut_pct: Mapped[float]

    counterparty: Mapped["CounterpartyORM"] = relationship(back_populates="collateral_items")


class AuditLogORM(Base):
    """Immutable record of an agent/orchestration action (MM-91, Phase 9)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    correlation_id: Mapped[str] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime]


class PriceHistoryORM(Base):
    """Daily EOD price snapshot per ticker (MM-15 batch loader)."""

    __tablename__ = "price_history"

    ticker: Mapped[str] = mapped_column(String(20), primary_key=True)
    price_date: Mapped[date] = mapped_column(primary_key=True)
    price: Mapped[float]
    currency: Mapped[str] = mapped_column(String(10), default="USD")
    source: Mapped[str] = mapped_column(String(20))


class ReferenceRateORM(Base):
    """Daily FRED reference rate/yield/VIX snapshot (MM-15 batch loader)."""

    __tablename__ = "reference_rates"

    series_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    rate_date: Mapped[date] = mapped_column(primary_key=True)
    value: Mapped[float]


class TicketORM(Base):
    """Escalation ticket state (MM-62, Phase 6)."""

    __tablename__ = "tickets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    counterparty_id: Mapped[str] = mapped_column(ForeignKey("counterparties.id"))
    status: Mapped[str] = mapped_column(String(20))
    external_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime]
    resolved_at: Mapped[datetime | None] = mapped_column(nullable=True)

    counterparty: Mapped["CounterpartyORM"] = relationship(back_populates="tickets")
