"""BarAggregator: ticks -> barras intraday fechadas, tudo offline.

Cobre o alinhamento dos buckets ao relógio UTC, o contrato de drain (só
períodos terminados), o volume como delta do cumulativo da sessão, a
thread-safety do update e a integração runtime -> MarketBar -> strategy bars.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import Instrument, MarketBar, PaperPortfolio, User
from app.services.data_feed.types import Tick
from app.services.paper_trading.bar_aggregator import BarAggregator
from app.services.paper_trading.runtime import PaperEngineRuntime, load_strategy_bars

T0 = datetime(2026, 7, 6, 15, 0, 0, tzinfo=UTC)  # Monday 15:00:00 UTC


def tick(
    symbol: str,
    at: datetime,
    *,
    last: float | None = None,
    volume: float | None = None,
) -> Tick:
    return Tick(
        symbol=symbol,
        timestamp=at,
        last=Decimal(str(last)) if last is not None else None,
        volume=Decimal(str(volume)) if volume is not None else None,
    )


def test_same_minute_ticks_build_one_1m_bar() -> None:
    agg = BarAggregator(timeframes=("1m",))
    agg.update_from_tick(tick("AAPL", T0 + timedelta(seconds=1), last=100.0))
    agg.update_from_tick(tick("AAPL", T0 + timedelta(seconds=20), last=102.5))
    agg.update_from_tick(tick("AAPL", T0 + timedelta(seconds=40), last=99.5))
    agg.update_from_tick(tick("AAPL", T0 + timedelta(seconds=59), last=101.0))

    bars = agg.drain_closed_bars(T0 + timedelta(minutes=1))
    assert len(bars) == 1
    bar = bars[0]
    assert bar.symbol == "AAPL"
    assert bar.timeframe == "1m"
    assert bar.timestamp == T0
    assert bar.open == 100.0
    assert bar.high == 102.5
    assert bar.low == 99.5
    assert bar.close == 101.0


def test_next_minute_tick_leaves_forming_bucket_out_of_drain() -> None:
    agg = BarAggregator(timeframes=("1m",))
    agg.update_from_tick(tick("AAPL", T0 + timedelta(seconds=10), last=100.0))
    agg.update_from_tick(tick("AAPL", T0 + timedelta(seconds=70), last=105.0))  # next minute

    bars = agg.drain_closed_bars(T0 + timedelta(seconds=75))
    assert [bar.timestamp for bar in bars] == [T0]
    assert bars[0].close == 100.0

    # The forming bucket only comes out once its own period ends.
    assert agg.drain_closed_bars(T0 + timedelta(seconds=90)) == []
    later = agg.drain_closed_bars(T0 + timedelta(minutes=2))
    assert [bar.timestamp for bar in later] == [T0 + timedelta(minutes=1)]
    assert later[0].open == 105.0


def test_5m_buckets_align_to_multiple_of_five() -> None:
    agg = BarAggregator(timeframes=("5m",))
    at = datetime(2026, 7, 6, 15, 7, 30, tzinfo=UTC)  # inside the 15:05 bucket
    agg.update_from_tick(tick("MSFT", at, last=300.0))

    bars = agg.drain_closed_bars(datetime(2026, 7, 6, 15, 10, 0, tzinfo=UTC))
    assert len(bars) == 1
    assert bars[0].timestamp == datetime(2026, 7, 6, 15, 5, 0, tzinfo=UTC)


def test_ticks_without_last_are_ignored_for_ohlc() -> None:
    agg = BarAggregator(timeframes=("1m",))
    agg.update_from_tick(tick("AAPL", T0 + timedelta(seconds=5), volume=1000.0))  # no last
    assert agg.drain_closed_bars(T0 + timedelta(minutes=5)) == []

    agg.update_from_tick(tick("AAPL", T0 + timedelta(minutes=5, seconds=1), last=100.0))
    bars = agg.drain_closed_bars(T0 + timedelta(minutes=10))
    assert len(bars) == 1
    assert bars[0].open == 100.0


def test_volume_is_delta_of_cumulative_session_volume() -> None:
    """Tick.volume é o cumulativo da sessão — a barra recebe apenas o delta."""
    agg = BarAggregator(timeframes=("1m",))
    # First reading sets the baseline; its cumulative total must NOT be copied.
    agg.update_from_tick(tick("AAPL", T0 + timedelta(seconds=1), last=100.0, volume=50_000.0))
    agg.update_from_tick(tick("AAPL", T0 + timedelta(seconds=30), last=101.0, volume=50_300.0))
    agg.update_from_tick(tick("AAPL", T0 + timedelta(seconds=50), last=100.5, volume=50_500.0))

    bars = agg.drain_closed_bars(T0 + timedelta(minutes=1))
    assert len(bars) == 1
    assert bars[0].volume == pytest.approx(500.0)


def test_update_from_tick_is_thread_safe() -> None:
    """Threads concorrentes não perdem ticks nem corrompem buckets partilhados.

    Cada thread alimenta o SEU símbolo: o volume cumulativo de sessão só é
    coerente por símbolo (leituras fora de ordem parecem resets), por isso a
    concorrência real acontece entre símbolos no dict/lock partilhados.
    """
    agg = BarAggregator(timeframes=("1m",))
    threads_n, ticks_per_thread = 8, 200

    def feed(symbol: str) -> None:
        for step in range(1, ticks_per_thread + 1):
            agg.update_from_tick(
                tick(symbol, T0 + timedelta(seconds=30), last=100.0, volume=step * 10.0)
            )

    workers = [
        threading.Thread(target=feed, args=(f"SYM{index}",)) for index in range(threads_n)
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()

    bars = agg.drain_closed_bars(T0 + timedelta(minutes=1))
    assert len(bars) == threads_n  # one bar per symbol, none lost
    for bar in bars:
        # First reading is the unknown baseline (delta 0); the rest sum fully.
        assert bar.volume == pytest.approx((ticks_per_thread - 1) * 10.0)


# -- runtime integration -------------------------------------------------------


def build_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'test_bar_aggregator.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_runtime_persists_1m_bars_readable_by_strategies(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    with factory() as session:
        user = User(email="bars@example.com", password_hash="hash")
        session.add(user)
        session.flush()
        portfolio = PaperPortfolio(
            owner_user_id=user.id,
            initial_cash=Decimal("100000"),
            cash=Decimal("100000"),
            equity=Decimal("100000"),
            risk_settings={"timeframe": "1m", "symbols": ["AAPL"]},
            engine_running=True,
        )
        session.add(portfolio)
        session.commit()
        portfolio_id = portfolio.id

    settings = SimpleNamespace(
        ibkr_market_data_type=1,
        paper_engine_poll_seconds=5.0,
        paper_engine_bars_limit=300,
        paper_engine_intraday_enabled=True,
        realtime_feed_provider="none",
        realtime_feed_symbol_list=["SPY"],
    )
    runtime = PaperEngineRuntime(
        portfolio_id, settings=settings, provider=None, poll_seconds=5.0
    )
    assert runtime.bar_aggregator is not None

    # Ticks arrive on the provider thread via _on_tick (two closed minutes).
    runtime._on_tick(tick("AAPL", T0 + timedelta(seconds=5), last=100.0))
    runtime._on_tick(tick("AAPL", T0 + timedelta(seconds=45), last=101.0))
    runtime._on_tick(tick("AAPL", T0 + timedelta(seconds=80), last=102.0))

    with factory() as session:
        runtime._persist_intraday_bars(session)
        session.commit()

        instrument = session.execute(
            select(Instrument).where(Instrument.symbol == "AAPL")
        ).scalar_one()  # created on demand, csv_importer style
        rows = list(
            session.execute(
                select(MarketBar)
                .where(
                    MarketBar.instrument_id == instrument.id,
                    MarketBar.timeframe == "1m",
                )
                .order_by(MarketBar.timestamp)
            ).scalars()
        )
        # SQLite hands back naive datetimes; normalize before comparing.
        stamps = [row.timestamp.replace(tzinfo=UTC) for row in rows]
        assert stamps == [T0, T0 + timedelta(minutes=1)]
        assert float(rows[0].open) == 100.0
        assert float(rows[0].close) == 101.0

        bars = load_strategy_bars(session, "AAPL", "1m", limit=300)
        assert [bar.close for bar in bars] == [101.0, 102.0]

        # Idempotent: draining nothing / re-running the poll adds no duplicates.
        runtime._persist_intraday_bars(session)
        session.commit()
        count = len(
            list(
                session.execute(
                    select(MarketBar).where(
                        MarketBar.instrument_id == instrument.id,
                        MarketBar.timeframe == "1m",
                    )
                ).scalars()
            )
        )
        assert count == 2
