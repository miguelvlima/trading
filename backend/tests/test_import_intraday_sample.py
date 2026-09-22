"""Dados 5m de amostra (Fase 5): geração determinística, import idempotente
e walk-forward das estratégias novas vs antigas, tudo offline."""

from __future__ import annotations

from datetime import UTC
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.db.models import MarketBar
from app.scripts.import_intraday_sample import (
    BARS_PER_SESSION,
    NEW_STRATEGIES,
    OLD_STRATEGIES,
    SYMBOL_PROFILES,
    generate_intraday_bars,
    import_intraday_sample,
    run_walkforward_comparison,
)
from app.services.backtest_concrete_pivots import suggest_alternative_timeframe


def build_session_factory(tmp_path: Path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'test_intraday_sample.db'}")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


def test_generator_is_deterministic_and_session_aligned() -> None:
    first = generate_intraday_bars("AAPL", sessions=3)
    second = generate_intraday_bars("AAPL", sessions=3)
    assert first == second  # same input -> byte-identical sample
    assert len(first) == 3 * BARS_PER_SESSION

    for bar in first:
        assert bar.timestamp.tzinfo is UTC
        assert bar.timestamp.minute % 5 == 0 and bar.timestamp.second == 0
        assert bar.timestamp.weekday() < 5  # sessions skip weekends
        assert bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high
        assert bar.volume > 0

    # Different symbols get different price paths.
    other = generate_intraday_bars("NVDA", sessions=3)
    assert [b.close for b in other] != [b.close for b in first]


def test_import_is_idempotent(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    with factory() as session:
        first = import_intraday_sample(session, sessions=2)
        assert set(first) == set(SYMBOL_PROFILES)
        assert all(count == 2 * BARS_PER_SESSION for count in first.values())

        second = import_intraday_sample(session, sessions=2)
        assert all(count == 0 for count in second.values())  # nothing re-imported

        total = session.execute(
            select(func.count()).select_from(MarketBar).where(MarketBar.timeframe == "5m")
        ).scalar_one()
        assert total == len(SYMBOL_PROFILES) * 2 * BARS_PER_SESSION


def test_walkforward_comparison_covers_new_and_old_strategies(tmp_path: Path) -> None:
    factory = build_session_factory(tmp_path)
    with factory() as session:
        import_intraday_sample(session, sessions=6)
        results = run_walkforward_comparison(session)

    expected = len(SYMBOL_PROFILES) * (len(NEW_STRATEGIES) + len(OLD_STRATEGIES))
    assert len(results) == expected

    for row in results:
        assert row["timeframe"] == "5m"
        assert row["bars_processed"] == 6 * BARS_PER_SESSION
        for metric in ("trades_count", "net_pnl_pct", "win_rate", "profit_factor", "max_drawdown_pct"):
            assert metric in row
        assert row["walkforward"] is not None  # the holdout split actually ran

    # The sample data must actually exercise the pipeline: at least one
    # strategy trades, including at least one of the NEW intraday ones.
    assert sum(row["trades_count"] for row in results) > 0
    new_trades = sum(r["trades_count"] for r in results if r["group"] == "nova")
    assert new_trades > 0


def test_intraday_timeframes_have_intraday_alternatives() -> None:
    assert suggest_alternative_timeframe("1m") == "5m"
    assert suggest_alternative_timeframe("5m") == "1m"
    assert suggest_alternative_timeframe("1d") == "1w"
