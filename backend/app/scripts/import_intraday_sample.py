"""Barras 5m determinísticas para dev/testes e walk-forward das estratégias.

Gera (sem rede) sessões intraday sintéticas para 3 símbolos com personalidades
diferentes — tendência, reversão à média e volatilidade — importa-as para
MarketBar (idempotente) e corre um walk-forward que compara as estratégias
intraday novas (ORB, VWAP, duplo topo/fundo) com as antigas, imprimindo as
métricas no mesmo formato dos backtests persistidos.

Uso:
    python -m app.scripts.import_intraday_sample [--sessions 10] [--skip-backtests]
"""

from __future__ import annotations

import argparse
import math
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Instrument, MarketBar
from app.services.backtest_engine import (
    BacktestConfig,
    aggregate_signals,
    run_backtest_with_walkforward,
)
from app.services.strategy_engine import BarInput, run_strategy

TIMEFRAME = "5m"
BARS_PER_SESSION = 78  # 09:30-16:00 NY = 6.5h of 5m bars
SESSION_OPEN_UTC = time(13, 30)  # summer (EDT); synthetic data, DST is irrelevant
DEFAULT_START_DAY = date(2026, 6, 22)  # a Monday

# Three personalities so every strategy family has something to chew on:
# steady trender (ORB), mean-reverter (VWAP/RSI) and a volatile swinger
# (double top/bottom). Values are (base price, trend per session %, intraday
# wave amplitude, noise amplitude).
SYMBOL_PROFILES: dict[str, tuple[float, float, float, float]] = {
    "AAPL": (190.0, 0.6, 0.35, 0.25),
    "MSFT": (420.0, -0.1, 1.6, 0.35),
    "NVDA": (130.0, 0.3, 0.9, 0.75),
}

NEW_STRATEGIES = ("opening_range_breakout", "vwap_reversion", "double_top_bottom")
OLD_STRATEGIES = (
    "rsi_mean_reversion",
    "macd_crossover",
    "sma_ema_crossover",
    "bollinger_breakout",
)


@dataclass(frozen=True)
class SampleBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


def _session_days(start_day: date, sessions: int) -> list[date]:
    days: list[date] = []
    current = start_day
    while len(days) < sessions:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return days


def generate_intraday_bars(
    symbol: str, *, sessions: int = 10, start_day: date = DEFAULT_START_DAY
) -> list[SampleBar]:
    """Deterministic 5m bars: same symbol + sessions -> identical output.

    Each session mixes a slow trend, an intraday sine wave (fuel for VWAP
    deviations) and seeded noise; every third session gets an afternoon
    push so opening-range breakouts genuinely occur in the sample.
    """
    base, trend_pct, wave, noise_amp = SYMBOL_PROFILES.get(
        symbol, (100.0, 0.2, 0.5, 0.3)
    )
    rng = random.Random(f"intraday-sample:{symbol}")
    bars: list[SampleBar] = []
    previous_close = base

    for session_index, day in enumerate(_session_days(start_day, sessions)):
        session_start = datetime.combine(day, SESSION_OPEN_UTC, tzinfo=UTC)
        session_base = base * (1.0 + trend_pct / 100.0 * session_index)
        for bar_index in range(BARS_PER_SESSION):
            level = session_base + wave * math.sin(2.0 * math.pi * bar_index / 26.0)
            if session_index % 3 == 0 and bar_index >= 42:
                level += wave * 2.0  # afternoon breakout push
            close = level + noise_amp * rng.uniform(-1.0, 1.0)
            open_ = previous_close
            spread_up = abs(noise_amp * rng.uniform(0.0, 1.0)) + 0.05
            spread_down = abs(noise_amp * rng.uniform(0.0, 1.0)) + 0.05
            bars.append(
                SampleBar(
                    timestamp=session_start + timedelta(minutes=5 * bar_index),
                    open=round(open_, 4),
                    high=round(max(open_, close) + spread_up, 4),
                    low=round(min(open_, close) - spread_down, 4),
                    close=round(close, 4),
                    volume=float(5_000 + rng.randrange(0, 3_000)),
                )
            )
            previous_close = close
    return bars


def import_intraday_sample(
    db: Session, *, sessions: int = 10, start_day: date = DEFAULT_START_DAY
) -> dict[str, int]:
    """Upsert-by-absence: only missing (instrument, 5m, timestamp) rows are
    inserted, so re-running the script never duplicates or rewrites bars."""
    imported: dict[str, int] = {}
    for symbol in SYMBOL_PROFILES:
        instrument = db.execute(
            select(Instrument).where(Instrument.symbol == symbol)
        ).scalar_one_or_none()
        if instrument is None:
            instrument = Instrument(symbol=symbol, name=None, currency="USD")
            db.add(instrument)
            db.flush()

        existing = {
            row
            for row in db.execute(
                select(MarketBar.timestamp).where(
                    MarketBar.instrument_id == instrument.id,
                    MarketBar.timeframe == TIMEFRAME,
                )
            ).scalars()
        }
        count = 0
        for bar in generate_intraday_bars(symbol, sessions=sessions, start_day=start_day):
            key = bar.timestamp.replace(tzinfo=None)
            if bar.timestamp in existing or key in existing:
                continue
            db.add(
                MarketBar(
                    instrument_id=instrument.id,
                    timeframe=TIMEFRAME,
                    timestamp=bar.timestamp,
                    open=Decimal(str(bar.open)),
                    high=Decimal(str(bar.high)),
                    low=Decimal(str(bar.low)),
                    close=Decimal(str(bar.close)),
                    volume=Decimal(str(bar.volume)),
                )
            )
            count += 1
        imported[symbol] = count
    db.commit()
    return imported


def _load_bars(db: Session, symbol: str) -> list[BarInput]:
    rows = db.execute(
        select(MarketBar)
        .join(Instrument, MarketBar.instrument_id == Instrument.id)
        .where(Instrument.symbol == symbol, MarketBar.timeframe == TIMEFRAME)
        .order_by(MarketBar.timestamp.asc())
    ).scalars()
    return [
        BarInput(
            timestamp=row.timestamp,
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume),
        )
        for row in rows
    ]


def _walkforward_config() -> BacktestConfig:
    # Mirrors the paper-engine defaults so the comparison reflects live use.
    return BacktestConfig(
        initial_capital=100_000.0,
        fee_bps=1.0,
        fee_model="ibkr_us_tiered",
        slippage_bps=5.0,
        position_size_pct=10.0,
        position_sizing_model="fixed_pct",
        risk_per_trade_pct=1.0,
        entry_confirmation_bars=0,
        execution_timing="next_open",
        exit_mode="tp_sl_or_opposite",
        stop_loss_pct=2.0,
        take_profit_pct=4.0,
        max_bars_in_trade=None,
        benchmark_enabled=False,
        slippage_model="fixed",
    )


def run_walkforward_comparison(
    db: Session, *, min_signal_strength: float = 0.3
) -> list[dict[str, object]]:
    """Walk-forward (holdout 30%) por símbolo × estratégia, novas vs antigas.

    Devolve as métricas com os mesmos nomes dos BacktestRun persistidos, para
    a comparação ser lida da mesma forma que qualquer backtest do cockpit.
    """
    config = _walkforward_config()
    results: list[dict[str, object]] = []
    for symbol in SYMBOL_PROFILES:
        bars = _load_bars(db, symbol)
        if not bars:
            continue
        for group, strategies in (("nova", NEW_STRATEGIES), ("antiga", OLD_STRATEGIES)):
            for strategy in strategies:
                signals = run_strategy(strategy, symbol=symbol, bars=bars)
                aggregated = aggregate_signals(
                    per_strategy={
                        strategy: [(s.timestamp, s.direction, s.strength) for s in signals]
                    },
                    min_signal_strength=min_signal_strength,
                )
                output = run_backtest_with_walkforward(
                    bars=bars,
                    aggregated_signals=aggregated,
                    config=config,
                    split_pct=30.0,
                )
                walkforward = output.summary.get("walkforward")
                results.append(
                    {
                        "symbol": symbol,
                        "strategy": strategy,
                        "group": group,
                        "timeframe": TIMEFRAME,
                        "bars_processed": output.metrics.bars_processed,
                        "trades_count": output.metrics.trades_count,
                        "net_pnl_pct": output.metrics.net_pnl_pct,
                        "win_rate": output.metrics.win_rate,
                        "profit_factor": output.metrics.profit_factor,
                        "max_drawdown_pct": output.metrics.max_drawdown_pct,
                        "walkforward": walkforward if isinstance(walkforward, dict) else None,
                    }
                )
    return results


def _print_comparison(results: list[dict[str, object]]) -> None:
    header = (
        f"{'símbolo':<8} {'estratégia':<24} {'grupo':<7} {'trades':>6} "
        f"{'pnl%':>8} {'win%':>6} {'PF':>6} {'DD%':>7}"
    )
    print(header)
    print("-" * len(header))
    for row in sorted(results, key=lambda r: (r["symbol"], r["group"], r["strategy"])):
        print(
            f"{row['symbol']:<8} {row['strategy']:<24} {row['group']:<7} "
            f"{row['trades_count']:>6} {row['net_pnl_pct']:>8.2f} "
            f"{row['win_rate'] * 100:>6.1f} {row['profit_factor']:>6.2f} "
            f"{row['max_drawdown_pct']:>7.2f}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Importa barras 5m sintéticas e compara estratégias intraday."
    )
    parser.add_argument("--sessions", type=int, default=10, help="Sessões por símbolo")
    parser.add_argument(
        "--skip-backtests",
        action="store_true",
        help="Só importa as barras, sem correr o walk-forward",
    )
    args = parser.parse_args()

    from app.db.session import SessionLocal

    with SessionLocal() as db:
        imported = import_intraday_sample(db, sessions=args.sessions)
        for symbol, count in imported.items():
            total = args.sessions * BARS_PER_SESSION
            print(f"{symbol}: {count} barras 5m novas importadas (de {total} geradas).")
        if not args.skip_backtests:
            print()
            _print_comparison(run_walkforward_comparison(db))


if __name__ == "__main__":
    main()
