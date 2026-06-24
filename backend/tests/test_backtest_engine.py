from datetime import UTC, datetime

from app.services.backtest_engine import aggregate_signals


def test_aggregate_signals_uses_per_strategy_thresholds() -> None:
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    per_strategy = {
        "rsi_mean_reversion": [(ts, "BUY", 0.25)],
        "macd_crossover": [(ts, "BUY", 0.15)],
    }

    aggregated = aggregate_signals(
        per_strategy=per_strategy,
        min_signal_strength=0.1,
        strategy_min_strengths={"rsi_mean_reversion": 0.3, "macd_crossover": 0.2},
        min_consensus_strength=0.1,
    )

    assert aggregated == {}


def test_aggregate_signals_applies_consensus_threshold() -> None:
    ts = datetime(2024, 1, 1, tzinfo=UTC)
    per_strategy = {
        "rsi_mean_reversion": [(ts, "BUY", 0.6)],
        "macd_crossover": [(ts, "SELL", 0.55)],
    }

    aggregated = aggregate_signals(
        per_strategy=per_strategy,
        min_signal_strength=0.1,
        strategy_min_strengths={},
        min_consensus_strength=0.8,
    )

    assert aggregated == {}
