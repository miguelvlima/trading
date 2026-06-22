from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Instrument(Base):
    __tablename__ = "instruments"
    __table_args__ = (UniqueConstraint("symbol", name="uq_instruments_symbol"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    exchange: Mapped[str | None] = mapped_column(String(64), nullable=True)
    currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    market_bars: Mapped[list["MarketBar"]] = relationship(
        back_populates="instrument", cascade="all, delete-orphan"
    )


class MarketBar(Base):
    __tablename__ = "market_bars"
    __table_args__ = (
        UniqueConstraint(
            "instrument_id",
            "timeframe",
            "timestamp",
            name="uq_market_bars_instrument_timeframe_timestamp",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    instrument_id: Mapped[int] = mapped_column(
        ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    timeframe: Mapped[str] = mapped_column(String(16), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    open: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(18, 8), nullable=False)
    volume: Mapped[Decimal] = mapped_column(Numeric(24, 8), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    instrument: Mapped[Instrument] = relationship(back_populates="market_bars")
