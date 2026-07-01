from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.api.dependencies.auth import get_current_user
from app.db.dependencies import get_db_session
from app.db.models import BacktestRun, BacktestRunInsight, BacktestTrade, Instrument, MarketBar, User
from app.schemas.backtests import (
    BacktestLessonResponse,
    BacktestRecommendationResponse,
    BacktestRunDetailResponse,
    BacktestRunInsightResponse,
    BacktestRunRequest,
    BacktestRunSummaryResponse,
    BacktestTradeResponse,
)
from app.services.backtest_engine import (
    BacktestConfig,
    aggregate_signals,
    run_backtest_with_walkforward,
)
from app.services.backtest_export import render_equity_csv, render_trades_csv
from app.services.backtest_concrete_pivots import materialize_recommendations
from app.services.backtest_insight_guards import filter_recommendations_for_symbol_streak
from app.services.backtest_insight_engine import build_backtest_insight
from app.services.backtest_insight_types import PriorRunSnapshot
from app.services.backtest_recommendation_policy import is_protected_winning_run
from app.services.backtest_recommendation_probe import load_symbol_bars
from app.services.market_bar_availability import bar_counts_for_timeframes
from app.services.strategy_engine import BarInput, get_available_strategies, run_strategy

router = APIRouter(prefix="/backtests", tags=["backtests"])


def _to_trade_response(item: BacktestTrade) -> BacktestTradeResponse:
    return BacktestTradeResponse(
        id=item.id,
        direction=item.direction,
        entry_timestamp=item.entry_timestamp,
        exit_timestamp=item.exit_timestamp,
        entry_price=float(item.entry_price),
        exit_price=float(item.exit_price),
        quantity=float(item.quantity),
        gross_pnl=float(item.gross_pnl),
        fee_paid=float(item.fee_paid),
        net_pnl=float(item.net_pnl),
        return_pct=float(item.return_pct),
        bars_held=item.bars_held,
        entry_reason=item.entry_reason,
        exit_reason=item.exit_reason,
    )


def _run_config(result_summary: object) -> dict[str, object]:
    if not isinstance(result_summary, dict):
        return {}
    config = result_summary.get("config")
    return config if isinstance(config, dict) else {}


def _prepare_recommendations(
    db: Session,
    raw_recommendations: object,
    *,
    symbol: str,
    config: dict[str, object],
    strategy_names: list[str],
    timeframe: str,
    recent_symbol_pnls: list[float] | None = None,
    trades_count: int | None = None,
    net_pnl_pct: float | None = None,
    profit_factor: float | None = None,
) -> list[dict[str, object]]:
    if is_protected_winning_run(
        trades_count=trades_count,
        net_pnl_pct=net_pnl_pct,
        profit_factor=profit_factor,
    ):
        return []

    if not isinstance(raw_recommendations, list):
        return []
    dict_items = [entry for entry in raw_recommendations if isinstance(entry, dict)]
    filtered = (
        filter_recommendations_for_symbol_streak(dict_items, recent_symbol_pnls)
        if recent_symbol_pnls
        else dict_items
    )
    bar_counts = bar_counts_for_timeframes(db, symbol=symbol, timeframes=["1d", "1w"])
    bars = load_symbol_bars(db, symbol=symbol, timeframe=timeframe)
    return materialize_recommendations(
        filtered,
        config=config,
        strategy_names=strategy_names,
        timeframe=timeframe,
        recent_pnls_newest_first=recent_symbol_pnls,
        bar_counts=bar_counts,
        bars=bars,
        symbol=symbol,
        trades_count=trades_count,
        current_pnl_pct=net_pnl_pct,
        profit_factor=profit_factor,
    )


def _to_insight_response(
    item: BacktestRunInsight,
    *,
    db: Session,
    run_config: dict[str, object] | None = None,
    recent_symbol_pnls: list[float] | None = None,
    trades_count: int | None = None,
    net_pnl_pct: float | None = None,
    profit_factor: float | None = None,
) -> BacktestRunInsightResponse:
    config = run_config if run_config is not None else {}
    recommendations = _prepare_recommendations(
        db,
        item.recommendations,
        symbol=item.symbol,
        config=config,
        strategy_names=item.strategy_names,
        timeframe=item.timeframe,
        recent_symbol_pnls=recent_symbol_pnls,
        trades_count=trades_count,
        net_pnl_pct=net_pnl_pct,
        profit_factor=profit_factor,
    )
    return BacktestRunInsightResponse(
        id=item.id,
        run_id=item.run_id,
        narrative_summary=item.narrative_summary,
        timeline=item.timeline,
        failure_modes=item.failure_modes,
        lessons=item.lessons,
        recommendations=recommendations,
        prior_runs_context=item.prior_runs_context,
        created_at=item.created_at,
    )


def _recent_symbol_pnls(
    db: Session,
    *,
    owner_user_id: int,
    symbol: str,
    limit: int = 5,
) -> list[float]:
    rows = db.execute(
        select(BacktestRun.net_pnl_pct)
        .where(
            BacktestRun.owner_user_id == owner_user_id,
            BacktestRun.symbol == symbol,
        )
        .order_by(BacktestRun.created_at.desc())
        .limit(limit)
    ).scalars().all()
    return [float(value) for value in rows]


def _to_run_detail(
    db: Session,
    run: BacktestRun,
    trades: list[BacktestTrade],
    insight: BacktestRunInsight | None = None,
    *,
    symbol_run_number: int | None = None,
    recent_symbol_pnls: list[float] | None = None,
) -> BacktestRunDetailResponse:
    return BacktestRunDetailResponse(
        **_to_run_summary(run, symbol_run_number=symbol_run_number).model_dump(),
        trades=[_to_trade_response(item) for item in trades],
        insight=_to_insight_response(
            insight,
            db=db,
            run_config=_run_config(run.result_summary),
            recent_symbol_pnls=recent_symbol_pnls,
            trades_count=run.trades_count,
            net_pnl_pct=float(run.net_pnl_pct),
            profit_factor=float(run.profit_factor),
        )
        if insight is not None
        else None,
    )


def _fetch_prior_run_snapshots(
    db: Session,
    *,
    owner_user_id: int,
    symbol: str,
    exclude_run_id: int,
    limit: int = 5,
) -> list[PriorRunSnapshot]:
    rows = db.execute(
        select(BacktestRun)
        .where(
            BacktestRun.owner_user_id == owner_user_id,
            BacktestRun.symbol == symbol,
            BacktestRun.id != exclude_run_id,
        )
        .order_by(BacktestRun.created_at.desc())
        .limit(limit)
    ).scalars().all()
    return [
        PriorRunSnapshot(
            run_id=item.id,
            created_at=item.created_at,
            net_pnl_pct=float(item.net_pnl_pct),
            win_rate=float(item.win_rate),
            profit_factor=float(item.profit_factor),
            trades_count=item.trades_count,
            stop_loss_pct=_config_float(item.result_summary, "stop_loss_pct"),
            take_profit_pct=_config_float(item.result_summary, "take_profit_pct"),
            min_consensus_strength=_config_float(item.result_summary, "min_consensus_strength"),
        )
        for item in rows
    ]


def _config_float(result_summary: object, key: str) -> float | None:
    if not isinstance(result_summary, dict):
        return None
    config = result_summary.get("config")
    if not isinstance(config, dict):
        return None
    value = config.get(key)
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _symbol_run_numbers_for_user(db: Session, owner_user_id: int) -> dict[int, int]:
    from sqlalchemy import func

    stmt = select(
        BacktestRun.id,
        func.row_number()
        .over(
            partition_by=BacktestRun.symbol,
            order_by=(BacktestRun.created_at.asc(), BacktestRun.id.asc()),
        )
        .label("symbol_run_number"),
    ).where(BacktestRun.owner_user_id == owner_user_id)
    return {int(row.id): int(row.symbol_run_number) for row in db.execute(stmt).all()}


def _persist_run_insight(
    db: Session,
    *,
    run_model: BacktestRun,
    strategies: list[str],
    output_metrics: object,
    trade_models: list[BacktestTrade],
    result_summary: dict[str, object],
    owner_user_id: int,
) -> BacktestRunInsight:
    config_block = result_summary.get("config")
    config = config_block if isinstance(config_block, dict) else {}
    prior_runs = _fetch_prior_run_snapshots(
        db,
        owner_user_id=owner_user_id,
        symbol=run_model.symbol,
        exclude_run_id=run_model.id,
    )
    bar_counts = bar_counts_for_timeframes(db, symbol=run_model.symbol, timeframes=["1d", "1w"])
    bars = load_symbol_bars(db, symbol=run_model.symbol, timeframe=run_model.timeframe)
    insight_payload = build_backtest_insight(
        symbol=run_model.symbol,
        timeframe=run_model.timeframe,
        strategy_names=strategies,
        metrics=output_metrics,
        trades=trade_models,
        result_summary=result_summary,
        config=config,
        prior_runs=prior_runs,
        bar_counts=bar_counts,
        bars=bars,
    )
    insight_model = BacktestRunInsight(
        run_id=run_model.id,
        owner_user_id=owner_user_id,
        symbol=run_model.symbol,
        timeframe=run_model.timeframe,
        strategy_names=strategies,
        narrative_summary=insight_payload.narrative_summary,
        timeline=insight_payload.timeline,
        failure_modes=insight_payload.failure_modes,
        lessons=insight_payload.lessons,
        recommendations=insight_payload.recommendations,
        prior_runs_context=insight_payload.prior_runs_context,
        created_at=datetime.now(UTC),
    )
    db.add(insight_model)
    return insight_model


def _to_run_summary(item: BacktestRun, *, symbol_run_number: int | None = None) -> BacktestRunSummaryResponse:
    insight_summary = None
    if item.insight is not None and item.insight.narrative_summary:
        insight_summary = item.insight.narrative_summary
    return BacktestRunSummaryResponse(
        id=item.id,
        owner_user_id=item.owner_user_id,
        symbol=item.symbol,
        timeframe=item.timeframe,
        strategy_names=item.strategy_names,
        start_at=item.start_at,
        end_at=item.end_at,
        initial_capital=float(item.initial_capital),
        fee_bps=float(item.fee_bps),
        slippage_bps=float(item.slippage_bps),
        min_signal_strength=float(item.min_signal_strength),
        bars_processed=item.bars_processed,
        trades_count=item.trades_count,
        net_pnl=float(item.net_pnl),
        net_pnl_pct=float(item.net_pnl_pct),
        win_rate=float(item.win_rate),
        profit_factor=float(item.profit_factor),
        max_drawdown_pct=float(item.max_drawdown_pct),
        created_at=item.created_at,
        result_summary=item.result_summary,
        insight_summary=insight_summary,
        symbol_run_number=symbol_run_number,
    )


@router.get("", response_model=list[BacktestRunSummaryResponse])
def list_backtests(
    symbol: str | None = Query(default=None, min_length=1, max_length=32),
    timeframe: str | None = Query(default=None, min_length=1, max_length=16),
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> list[BacktestRunSummaryResponse]:
    query = select(BacktestRun).where(BacktestRun.owner_user_id == current_user.id)
    if symbol:
        query = query.where(BacktestRun.symbol == symbol.upper().strip())
    if timeframe:
        query = query.where(BacktestRun.timeframe == timeframe)
    if start is not None:
        query = query.where(BacktestRun.created_at >= start)
    if end is not None:
        query = query.where(BacktestRun.created_at <= end)
    query = query.options(joinedload(BacktestRun.insight)).order_by(BacktestRun.created_at.desc()).limit(limit)
    rows = db.execute(query).scalars().unique().all()
    symbol_run_numbers = _symbol_run_numbers_for_user(db, current_user.id)
    return [
        _to_run_summary(item, symbol_run_number=symbol_run_numbers.get(item.id))
        for item in rows
    ]


@router.get("/lessons", response_model=list[BacktestLessonResponse])
def list_backtest_lessons(
    symbol: str | None = Query(default=None, min_length=1, max_length=32),
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(default=30, ge=1, le=100),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> list[BacktestLessonResponse]:
    query = (
        select(BacktestRunInsight)
        .where(BacktestRunInsight.owner_user_id == current_user.id)
        .order_by(BacktestRunInsight.created_at.desc())
        .limit(limit * 3)
    )
    if symbol:
        query = query.where(BacktestRunInsight.symbol == symbol.upper().strip())
    if start is not None:
        query = query.where(BacktestRunInsight.created_at >= start)
    if end is not None:
        query = query.where(BacktestRunInsight.created_at <= end)

    insights = db.execute(query).scalars().all()
    lessons: list[BacktestLessonResponse] = []
    for insight in insights:
        for lesson in insight.lessons:
            if not isinstance(lesson, dict):
                continue
            title = lesson.get("title")
            detail = lesson.get("detail")
            priority = lesson.get("priority")
            if not isinstance(title, str) or not isinstance(detail, str):
                continue
            lessons.append(
                BacktestLessonResponse(
                    title=title,
                    detail=detail,
                    priority=str(priority) if priority is not None else "medium",
                    symbol=insight.symbol,
                    strategy_names=insight.strategy_names,
                    run_id=insight.run_id,
                    created_at=insight.created_at,
                )
            )
            if len(lessons) >= limit:
                return lessons
    return lessons


@router.get("/recommendations", response_model=list[BacktestRecommendationResponse])
def list_backtest_recommendations(
    symbol: str | None = Query(default=None, min_length=1, max_length=32),
    limit: int = Query(default=12, ge=1, le=100),
    scope: Literal["latest_run", "all"] = Query(default="latest_run"),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> list[BacktestRecommendationResponse]:
    query = (
        select(BacktestRunInsight)
        .where(BacktestRunInsight.owner_user_id == current_user.id)
        .order_by(BacktestRunInsight.created_at.desc())
    )
    if symbol:
        query = query.where(BacktestRunInsight.symbol == symbol.upper().strip())
    if scope == "latest_run" and symbol:
        query = query.limit(1)
    else:
        query = query.limit(limit * 3)

    insights = db.execute(query).scalars().all()
    run_ids = [insight.run_id for insight in insights]
    run_configs: dict[int, dict[str, object]] = {}
    run_trades_count: dict[int, int] = {}
    run_net_pnl_pct: dict[int, float] = {}
    run_profit_factor: dict[int, float] = {}
    if run_ids:
        runs = db.execute(
            select(BacktestRun).where(
                BacktestRun.id.in_(run_ids),
                BacktestRun.owner_user_id == current_user.id,
            )
        ).scalars().all()
        run_configs = {item.id: _run_config(item.result_summary) for item in runs}
        run_trades_count = {item.id: int(item.trades_count) for item in runs}
        run_net_pnl_pct = {item.id: float(item.net_pnl_pct) for item in runs}
        run_profit_factor = {item.id: float(item.profit_factor) for item in runs}

    recommendations: list[BacktestRecommendationResponse] = []
    symbol_pnl_cache: dict[str, list[float]] = {}
    for insight in insights:
        if insight.symbol not in symbol_pnl_cache:
            symbol_pnl_cache[insight.symbol] = _recent_symbol_pnls(
                db,
                owner_user_id=current_user.id,
                symbol=insight.symbol,
            )
        prepared_items = _prepare_recommendations(
            db,
            insight.recommendations,
            symbol=insight.symbol,
            config=run_configs.get(insight.run_id, {}),
            strategy_names=insight.strategy_names,
            timeframe=insight.timeframe,
            recent_symbol_pnls=symbol_pnl_cache[insight.symbol],
            trades_count=run_trades_count.get(insight.run_id),
            net_pnl_pct=run_net_pnl_pct.get(insight.run_id),
            profit_factor=run_profit_factor.get(insight.run_id),
        )
        for item in prepared_items:
            area = item.get("area")
            suggestion = item.get("suggestion")
            rationale = item.get("rationale")
            if not isinstance(area, str) or not isinstance(suggestion, str) or not isinstance(rationale, str):
                continue
            param_hint = item.get("param_hint")
            suggested_values = item.get("suggested_values")
            recommendations.append(
                BacktestRecommendationResponse(
                    area=area,
                    suggestion=suggestion,
                    rationale=rationale,
                    param_hint=str(param_hint) if param_hint is not None else None,
                    suggested_values=suggested_values if isinstance(suggested_values, dict) else None,
                    symbol=insight.symbol,
                    strategy_names=insight.strategy_names,
                    run_id=insight.run_id,
                    created_at=insight.created_at,
                )
            )
            if len(recommendations) >= limit:
                return recommendations
    return recommendations


@router.get("/{run_id}/export")
def export_backtest_run(
    run_id: int,
    export_type: Literal["trades", "equity"] = Query(alias="type"),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> Response:
    run = db.execute(
        select(BacktestRun).where(
            BacktestRun.id == run_id,
            BacktestRun.owner_user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backtest run not found.")

    if export_type == "trades":
        trades = db.execute(
            select(BacktestTrade)
            .where(BacktestTrade.run_id == run.id)
            .order_by(BacktestTrade.entry_timestamp.asc())
        ).scalars().all()
        trade_rows = [
            {
                "direction": item.direction,
                "entry_timestamp": item.entry_timestamp,
                "exit_timestamp": item.exit_timestamp,
                "entry_price": float(item.entry_price),
                "exit_price": float(item.exit_price),
                "quantity": float(item.quantity),
                "gross_pnl": float(item.gross_pnl),
                "fee_paid": float(item.fee_paid),
                "net_pnl": float(item.net_pnl),
                "return_pct": float(item.return_pct),
                "bars_held": item.bars_held,
                "entry_reason": item.entry_reason,
                "exit_reason": item.exit_reason,
            }
            for item in trades
        ]
        csv_content = render_trades_csv(trade_rows)
        filename = f"backtest_{run_id}_trades.csv"
    else:
        summary = run.result_summary if isinstance(run.result_summary, dict) else {}
        equity_curve = summary.get("equity_curve")
        if not isinstance(equity_curve, list):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Equity curve not available for this run.",
            )
        csv_content = render_equity_csv(equity_curve)
        filename = f"backtest_{run_id}_equity.csv"

    return Response(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{run_id}", response_model=BacktestRunDetailResponse)
def get_backtest_run(
    run_id: int,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> BacktestRunDetailResponse:
    run = db.execute(
        select(BacktestRun)
        .options(joinedload(BacktestRun.insight))
        .where(
            BacktestRun.id == run_id,
            BacktestRun.owner_user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backtest run not found.")
    trades = db.execute(
        select(BacktestTrade)
        .where(BacktestTrade.run_id == run.id)
        .order_by(BacktestTrade.entry_timestamp.asc())
    ).scalars().all()
    symbol_run_numbers = _symbol_run_numbers_for_user(db, current_user.id)
    recent_pnls = _recent_symbol_pnls(db, owner_user_id=current_user.id, symbol=run.symbol)
    return _to_run_detail(
        db,
        run,
        trades,
        run.insight,
        symbol_run_number=symbol_run_numbers.get(run.id),
        recent_symbol_pnls=recent_pnls,
    )


@router.post("/run", response_model=BacktestRunDetailResponse, status_code=status.HTTP_201_CREATED)
def run_backtest_simulation(
    payload: BacktestRunRequest,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> BacktestRunDetailResponse:
    symbol = payload.symbol.upper().strip()
    strategies = sorted({name.strip() for name in payload.strategies if name.strip()})
    if not strategies:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least one strategy is required.")

    available_strategies = set(get_available_strategies())
    invalid = sorted(name for name in strategies if name not in available_strategies)
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown strategies: {', '.join(invalid)}",
        )

    instrument = db.execute(select(Instrument).where(Instrument.symbol == symbol)).scalar_one_or_none()
    if instrument is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Instrument not found: {symbol}")

    bar_query = select(MarketBar).where(
        MarketBar.instrument_id == instrument.id,
        MarketBar.timeframe == payload.timeframe,
    )
    if payload.start is not None:
        bar_query = bar_query.where(MarketBar.timestamp >= payload.start)
    if payload.end is not None:
        bar_query = bar_query.where(MarketBar.timestamp <= payload.end)
    bars = db.execute(bar_query.order_by(MarketBar.timestamp.asc()).limit(payload.limit)).scalars().all()
    strategy_bars = [
        BarInput(
            timestamp=bar.timestamp,
            open=float(bar.open),
            high=float(bar.high),
            low=float(bar.low),
            close=float(bar.close),
            volume=float(bar.volume),
        )
        for bar in bars
    ]

    per_strategy_signals: dict[str, list[tuple]] = {}
    for strategy_name in strategies:
        strategy_signals = run_strategy(strategy_name, symbol=symbol, bars=strategy_bars)
        per_strategy_signals[strategy_name] = [
            (item.timestamp, item.direction, item.strength) for item in strategy_signals
        ]

    aggregated = aggregate_signals(
        per_strategy=per_strategy_signals,
        min_signal_strength=payload.min_signal_strength,
        strategy_min_strengths=payload.strategy_min_strengths,
        min_consensus_strength=payload.min_consensus_strength,
    )
    if payload.exit_mode in {"tp_sl_or_opposite", "tp_sl_only"} and (
        payload.stop_loss_pct is None and payload.take_profit_pct is None
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Configure stop-loss or take-profit when using TP/SL exit modes.",
        )

    config = BacktestConfig(
        initial_capital=payload.initial_capital,
        fee_bps=payload.fee_bps,
        fee_model=payload.fee_model,
        slippage_bps=payload.slippage_bps,
        position_size_pct=payload.position_size_pct,
        position_sizing_model=payload.position_sizing_model,
        risk_per_trade_pct=payload.risk_per_trade_pct,
        entry_confirmation_bars=payload.entry_confirmation_bars,
        execution_timing=payload.execution_timing,
        exit_mode=payload.exit_mode,
        stop_loss_pct=payload.stop_loss_pct,
        take_profit_pct=payload.take_profit_pct,
        max_bars_in_trade=payload.max_bars_in_trade,
        benchmark_enabled=payload.benchmark_enabled,
        slippage_model=payload.slippage_model,
    )
    output = run_backtest_with_walkforward(
        bars=strategy_bars,
        aggregated_signals=aggregated,
        config=config,
        split_pct=payload.walkforward_split_pct,
        walkforward_mode=payload.walkforward_mode,
        walkforward_folds=payload.walkforward_folds,
    )

    run_model = BacktestRun(
        owner_user_id=current_user.id,
        instrument_id=instrument.id,
        symbol=symbol,
        timeframe=payload.timeframe,
        strategy_names=strategies,
        start_at=payload.start,
        end_at=payload.end,
        initial_capital=Decimal(f"{payload.initial_capital:.8f}"),
        fee_bps=Decimal(f"{payload.fee_bps:.4f}"),
        slippage_bps=Decimal(f"{payload.slippage_bps:.4f}"),
        min_signal_strength=Decimal(f"{payload.min_signal_strength:.5f}"),
        bars_processed=output.metrics.bars_processed,
        trades_count=output.metrics.trades_count,
        net_pnl=Decimal(f"{output.metrics.net_pnl:.8f}"),
        net_pnl_pct=Decimal(f"{output.metrics.net_pnl_pct:.6f}"),
        win_rate=Decimal(f"{output.metrics.win_rate:.6f}"),
        profit_factor=Decimal(f"{output.metrics.profit_factor:.8f}"),
        max_drawdown_pct=Decimal(f"{output.metrics.max_drawdown_pct:.6f}"),
        result_summary={
            **output.summary,
            "config": {
                **(output.summary.get("config") if isinstance(output.summary.get("config"), dict) else {}),
                "strategies": strategies,
                "fee_bps": payload.fee_bps,
                "fee_model": payload.fee_model,
                "slippage_bps": payload.slippage_bps,
                "slippage_model": payload.slippage_model,
                "initial_capital": payload.initial_capital,
                "limit": payload.limit,
                "walkforward_split_pct": payload.walkforward_split_pct,
                "walkforward_mode": payload.walkforward_mode,
                "walkforward_folds": payload.walkforward_folds,
                "strategy_min_strengths": payload.strategy_min_strengths,
                "min_consensus_strength": payload.min_consensus_strength
                if payload.min_consensus_strength is not None
                else payload.min_signal_strength,
                "position_size_pct": payload.position_size_pct,
                "position_sizing_model": payload.position_sizing_model,
                "risk_per_trade_pct": payload.risk_per_trade_pct,
                "entry_confirmation_bars": payload.entry_confirmation_bars,
                "execution_timing": payload.execution_timing,
                "exit_mode": payload.exit_mode,
                "stop_loss_pct": payload.stop_loss_pct,
                "take_profit_pct": payload.take_profit_pct,
                "max_bars_in_trade": payload.max_bars_in_trade,
                "benchmark_enabled": payload.benchmark_enabled,
                "period_mode": payload.period_mode,
                "chart_window": payload.chart_window,
                "min_signal_strength": payload.min_signal_strength,
            },
        },
    )
    db.add(run_model)
    db.flush()

    trade_models: list[BacktestTrade] = []
    for trade in output.trades:
        model = BacktestTrade(
            run_id=run_model.id,
            direction=trade.direction,
            entry_timestamp=trade.entry_timestamp,
            exit_timestamp=trade.exit_timestamp,
            entry_price=Decimal(f"{trade.entry_price:.8f}"),
            exit_price=Decimal(f"{trade.exit_price:.8f}"),
            quantity=Decimal(f"{trade.quantity:.8f}"),
            gross_pnl=Decimal(f"{trade.gross_pnl:.8f}"),
            fee_paid=Decimal(f"{trade.fee_paid:.8f}"),
            net_pnl=Decimal(f"{trade.net_pnl:.8f}"),
            return_pct=Decimal(f"{trade.return_pct:.6f}"),
            bars_held=trade.bars_held,
            entry_reason=trade.entry_reason[:512],
            exit_reason=trade.exit_reason[:512],
        )
        db.add(model)
        trade_models.append(model)

    result_summary = run_model.result_summary if isinstance(run_model.result_summary, dict) else {}

    insight_model = _persist_run_insight(
        db,
        run_model=run_model,
        strategies=strategies,
        output_metrics=output.metrics,
        trade_models=trade_models,
        result_summary=result_summary,
        owner_user_id=current_user.id,
    )

    db.commit()
    db.refresh(run_model)
    for model in trade_models:
        db.refresh(model)
    db.refresh(insight_model)

    symbol_run_numbers = _symbol_run_numbers_for_user(db, current_user.id)
    recent_pnls = _recent_symbol_pnls(db, owner_user_id=current_user.id, symbol=run_model.symbol)
    return _to_run_detail(
        db,
        run_model,
        trade_models,
        insight_model,
        symbol_run_number=symbol_run_numbers.get(run_model.id),
        recent_symbol_pnls=recent_pnls,
    )


@router.delete("/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_backtest_run(
    run_id: int,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> None:
    run = db.execute(
        select(BacktestRun).where(
            BacktestRun.id == run_id,
            BacktestRun.owner_user_id == current_user.id,
        )
    ).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backtest run not found.")
    db.delete(run)
    db.commit()
