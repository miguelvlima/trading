from app.services.backtest_recommendation_values import compute_suggested_values, enrich_recommendation


def test_compute_suggested_values_stop_loss() -> None:
    values = compute_suggested_values(
        "stop_loss_pct",
        {"stop_loss_pct": 2.0},
        ["macd_crossover"],
    )
    assert values == {"stop_loss_pct": 2.5}


def test_compute_suggested_values_tp_sl_combo() -> None:
    values = compute_suggested_values(
        "take_profit_pct / stop_loss_pct",
        {"stop_loss_pct": 2.0, "take_profit_pct": 3.0},
        ["macd_crossover"],
    )
    assert values == {"stop_loss_pct": 2.5, "take_profit_pct": 4.0}


def test_compute_suggested_values_consensus() -> None:
    values = compute_suggested_values(
        "min_consensus_strength",
        {"min_consensus_strength": 0.2},
        ["macd_crossover", "rsi_reversal"],
    )
    assert values == {"min_consensus_strength_pct": 30}


def test_enrich_recommendation_without_param_hint() -> None:
    original = {
        "area": "regime_change",
        "suggestion": "Mudar timeframe",
        "rationale": "Histórico negativo",
    }
    enriched = enrich_recommendation(original, {}, ["macd_crossover"])
    assert enriched == original


def test_enrich_recommendation_adds_suggested_values() -> None:
    original = {
        "area": "stop_loss_pct",
        "suggestion": "Aumentar SL",
        "rationale": "Stops frequentes",
        "param_hint": "stop_loss_pct",
    }
    enriched = enrich_recommendation(original, {"stop_loss_pct": 1.5}, ["macd_crossover"])
    assert enriched["suggested_values"] == {"stop_loss_pct": 2.0}
