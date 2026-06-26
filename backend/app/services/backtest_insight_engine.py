from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class PriorRunSnapshot:
    run_id: int
    created_at: datetime
    net_pnl_pct: float
    win_rate: float
    profit_factor: float
    trades_count: int


@dataclass
class InsightPayload:
    narrative_summary: str
    timeline: list[dict[str, Any]]
    failure_modes: list[dict[str, Any]]
    lessons: list[dict[str, Any]]
    recommendations: list[dict[str, Any]]
    prior_runs_context: dict[str, Any]


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _trade_dict(trade: Any) -> dict[str, Any]:
    return {
        "direction": trade.direction,
        "entry_timestamp": trade.entry_timestamp.isoformat(),
        "exit_timestamp": trade.exit_timestamp.isoformat(),
        "net_pnl": round(float(trade.net_pnl), 2),
        "return_pct": round(float(trade.return_pct) * 100, 2),
        "bars_held": trade.bars_held,
        "entry_reason": trade.entry_reason,
        "exit_reason": trade.exit_reason,
    }


def build_backtest_insight(
    *,
    symbol: str,
    timeframe: str,
    strategy_names: list[str],
    metrics: Any,
    trades: list[Any],
    result_summary: dict[str, object],
    config: dict[str, object],
    prior_runs: list[PriorRunSnapshot],
) -> InsightPayload:
    timeline: list[dict[str, Any]] = []
    failure_modes: list[dict[str, Any]] = []
    lessons: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []
    step = 1

    net_pnl_pct = float(metrics.net_pnl_pct)
    win_rate = float(metrics.win_rate)
    profit_factor = float(metrics.profit_factor)
    max_dd = float(metrics.max_drawdown_pct)
    trades_count = int(metrics.trades_count)

    timeline.append(
        {
            "step": step,
            "phase": "setup",
            "title": "Configuração e período",
            "detail": (
                f"Simulação em {symbol} ({timeframe}) com {', '.join(strategy_names)}. "
                f"{metrics.bars_processed} barras processadas, {trades_count} trades executados."
            ),
            "severity": "info",
        }
    )
    step += 1

    benchmark_return = result_summary.get("benchmark_return_pct")
    alpha = result_summary.get("alpha_vs_benchmark_pct")
    if isinstance(benchmark_return, (int, float)):
        timeline.append(
            {
                "step": step,
                "phase": "benchmark",
                "title": "Comparação com buy & hold",
                "detail": (
                    f"Estratégia {_pct(net_pnl_pct)} vs benchmark {_pct(float(benchmark_return))}. "
                    f"Alpha {_pct(float(alpha)) if isinstance(alpha, (int, float)) else 'n/d'}."
                ),
                "severity": "info" if net_pnl_pct >= float(benchmark_return) else "warn",
            }
        )
        step += 1
        if net_pnl_pct < float(benchmark_return):
            failure_modes.append(
                {
                    "code": "underperformed_benchmark",
                    "title": "Performance inferior ao passivo",
                    "detail": (
                        "O resultado líquido ficou abaixo de comprar e manter o ativo no mesmo período."
                    ),
                    "severity": "warn",
                }
            )
            lessons.append(
                {
                    "title": "Alpha negativo",
                    "detail": "A combinação actual não justifica o risco activo face ao buy & hold.",
                    "priority": "high",
                }
            )
            recommendations.append(
                {
                    "area": "strategy_selection",
                    "suggestion": "Testar outra estratégia ou filtrar entradas com consenso mais exigente.",
                    "rationale": "Alpha negativo sugere sinal fraco para este universo temporal.",
                }
            )

    if net_pnl_pct <= 0:
        failure_modes.append(
            {
                "code": "negative_pnl",
                "title": "Resultado líquido negativo",
                "detail": f"PnL total {_pct(net_pnl_pct)} com drawdown máximo {_pct(max_dd)}.",
                "severity": "critical",
            }
        )

    if profit_factor < 1.0 and trades_count > 0:
        failure_modes.append(
            {
                "code": "profit_factor_below_one",
                "title": "Profit factor < 1",
                "detail": f"Perdas brutas superam ganhos (PF {profit_factor:.2f}).",
                "severity": "critical",
            }
        )
        recommendations.append(
            {
                "area": "risk_reward",
                "suggestion": "Rever relação TP/SL ou reduzir trades de baixa força de sinal.",
                "rationale": "PF < 1 indica expectativa negativa por trade.",
                "param_hint": "take_profit_pct / stop_loss_pct",
            }
        )

    losers = [t for t in trades if float(t.net_pnl) < 0]
    winners = [t for t in trades if float(t.net_pnl) >= 0]
    sl_exits = [t for t in trades if "stop" in t.exit_reason.lower()]
    tp_exits = [t for t in trades if "take" in t.exit_reason.lower() or "profit" in t.exit_reason.lower()]

    if losers:
        worst = min(losers, key=lambda t: float(t.net_pnl))
        timeline.append(
            {
                "step": step,
                "phase": "trade",
                "title": "Pior trade",
                "detail": (
                    f"{worst.direction} {_trade_dict(worst)['entry_timestamp'][:10]}: "
                    f"{worst.net_pnl:.2f} ({worst.exit_reason})."
                ),
                "severity": "warn",
                "trade": _trade_dict(worst),
            }
        )
        step += 1

    if sl_exits and len(sl_exits) > len(winners):
        failure_modes.append(
            {
                "code": "frequent_stop_loss",
                "title": "Muitas saídas por stop-loss",
                "detail": f"{len(sl_exits)} de {trades_count} trades fecharam por SL.",
                "severity": "warn",
                "trade_ids": [],
            }
        )
        lessons.append(
            {
                "title": "Stops apertados ou entradas precoces",
                "detail": "Stop-loss frequente pode indicar ruído ou confirmação insuficiente na entrada.",
                "priority": "medium",
            }
        )
        stop_loss = config.get("stop_loss_pct")
        if isinstance(stop_loss, (int, float)):
            recommendations.append(
                {
                    "area": "stop_loss_pct",
                    "suggestion": f"Aumentar SL de {stop_loss}% ou exigir entry_confirmation_bars > 1.",
                    "rationale": "Reduzir stops prematuros em mercado ruidoso.",
                    "param_hint": "stop_loss_pct",
                }
            )

    if tp_exits and win_rate < 0.45:
        lessons.append(
            {
                "title": "Ganhos limitados apesar de TP",
                "detail": "Win rate baixo mesmo com take-profit activo — entradas podem estar desalinhadas.",
                "priority": "medium",
            }
        )

    walkforward = result_summary.get("walkforward")
    if isinstance(walkforward, dict):
        out_sample = walkforward.get("out_sample")
        in_sample = walkforward.get("in_sample")
        if isinstance(out_sample, dict) and isinstance(in_sample, dict):
            out_pnl = out_sample.get("net_pnl_pct")
            in_pnl = in_sample.get("net_pnl_pct")
            if isinstance(out_pnl, (int, float)) and isinstance(in_pnl, (int, float)):
                timeline.append(
                    {
                        "step": step,
                        "phase": "walkforward",
                        "title": "Walk-forward in vs out",
                        "detail": f"In-sample {_pct(float(in_pnl))}, out-of-sample {_pct(float(out_pnl))}.",
                        "severity": "warn" if float(out_pnl) < float(in_pnl) * 0.5 else "info",
                    }
                )
                step += 1
                if float(out_pnl) < 0 and float(in_pnl) > 0:
                    failure_modes.append(
                        {
                            "code": "walkforward_degradation",
                            "title": "Degradação out-of-sample",
                            "detail": "Bom in-sample mas negativo fora da amostra — possível overfitting.",
                            "severity": "critical",
                        }
                    )
                    lessons.append(
                        {
                            "title": "Overfitting provável",
                            "detail": "Parâmetros podem estar optimizados ao ruído do período de treino.",
                            "priority": "high",
                        }
                    )

    prior_context: dict[str, Any] = {"runs_considered": len(prior_runs), "snapshots": []}
    if prior_runs:
        prior_context["snapshots"] = [
            {
                "run_id": item.run_id,
                "created_at": item.created_at.isoformat(),
                "net_pnl_pct": item.net_pnl_pct,
                "win_rate": item.win_rate,
                "profit_factor": item.profit_factor,
                "trades_count": item.trades_count,
            }
            for item in prior_runs
        ]
        avg_prior_pnl = sum(item.net_pnl_pct for item in prior_runs) / len(prior_runs)
        timeline.append(
            {
                "step": step,
                "phase": "history",
                "title": "Runs anteriores (mesmo símbolo/estratégias)",
                "detail": (
                    f"{len(prior_runs)} runs anteriores com PnL médio {_pct(avg_prior_pnl)}. "
                    f"Este run: {_pct(net_pnl_pct)}."
                ),
                "severity": "info",
            }
        )
        step += 1
        if avg_prior_pnl < 0 and net_pnl_pct < 0:
            lessons.append(
                {
                    "title": "Padrão recorrente de perda",
                    "detail": (
                        "Vários runs com a mesma configuração falharam — não é um outlier isolado."
                    ),
                    "priority": "high",
                }
            )
            recommendations.append(
                {
                    "area": "regime_change",
                    "suggestion": "Alterar timeframe, janela temporal ou combinação de estratégias.",
                    "rationale": "Histórico de runs sugere incompatibilidade estrutural com o mercado recente.",
                }
            )

    min_strength = config.get("min_consensus_strength") or config.get("min_signal_strength")
    if trades_count > metrics.bars_processed * 0.15 and isinstance(min_strength, (int, float)):
        recommendations.append(
            {
                "area": "min_signal_strength",
                "suggestion": f"Aumentar limiar de força (actual ~{float(min_strength):.0%}).",
                "rationale": "Alta rotação de trades aumenta fees e slippage.",
                "param_hint": "min_consensus_strength",
            }
        )

    if not lessons:
        lessons.append(
            {
                "title": "Resultado aceitável",
                "detail": "Sem falhas estruturais óbvias; focar em refinamento de parâmetros.",
                "priority": "low",
            }
        )

    narrative = (
        f"Run em {symbol} ({timeframe}) com PnL {_pct(net_pnl_pct)}, "
        f"win rate {_pct(win_rate)}, PF {profit_factor:.2f}, DD {_pct(max_dd)}. "
    )
    if failure_modes:
        narrative += f"Identificámos {len(failure_modes)} modo(s) de falha principal. "
    narrative += f"{len(lessons)} lição(ões) e {len(recommendations)} recomendação(ões) para runs futuras."

    return InsightPayload(
        narrative_summary=narrative,
        timeline=timeline,
        failure_modes=failure_modes,
        lessons=lessons,
        recommendations=recommendations,
        prior_runs_context=prior_context,
    )
