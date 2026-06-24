from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_user
from app.db.dependencies import get_db_session
from app.db.models import BacktestRun, BacktestTrade, Instrument, MarketBar, User
from app.schemas.backtests import (
    BacktestRunDetailResponse,
    BacktestRunRequest,
    BacktestRunSummaryResponse,
    BacktestTradeResponse,
)
from app.services.backtest_engine import (
    BacktestConfig,
    aggregate_signals,
    run_backtest_with_walkforward,
)
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


def _to_run_summary(item: BacktestRun) -> BacktestRunSummaryResponse:
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
    )


@router.get("", response_model=list[BacktestRunSummaryResponse])
def list_backtests(
    symbol: str | None = Query(default=None, min_length=1, max_length=32),
    timeframe: str | None = Query(default=None, min_length=1, max_length=16),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> list[BacktestRunSummaryResponse]:
    query = select(BacktestRun).where(BacktestRun.owner_user_id == current_user.id)
    if symbol:
        query = query.where(BacktestRun.symbol == symbol.upper().strip())
    if timeframe:
        query = query.where(BacktestRun.timeframe == timeframe)
    rows = db.execute(query.order_by(BacktestRun.created_at.desc()).limit(limit)).scalars().all()
    return [_to_run_summary(item) for item in rows]


@router.get("/{run_id}", response_model=BacktestRunDetailResponse)
def get_backtest_run(
    run_id: int,
    db: Session = Depends(get_db_session),
    current_user: User = Depends(get_current_user),
) -> BacktestRunDetailResponse:
    run = db.execute(
        select(BacktestRun).where(
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
    return BacktestRunDetailResponse(
        **_to_run_summary(run).model_dump(),
        trades=[_to_trade_response(item) for item in trades],
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
        slippage_bps=payload.slippage_bps,
        position_size_pct=payload.position_size_pct,
        entry_confirmation_bars=payload.entry_confirmation_bars,
        exit_mode=payload.exit_mode,
        stop_loss_pct=payload.stop_loss_pct,
        take_profit_pct=payload.take_profit_pct,
        max_bars_in_trade=payload.max_bars_in_trade,
        benchmark_enabled=payload.benchmark_enabled,
    )
    output = run_backtest_with_walkforward(
        bars=strategy_bars,
        aggregated_signals=aggregated,
        config=config,
        split_pct=payload.walkforward_split_pct,
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
                "strategy_min_strengths": payload.strategy_min_strengths,
                "min_consensus_strength": payload.min_consensus_strength
                if payload.min_consensus_strength is not None
                else payload.min_signal_strength,
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

    db.commit()
    db.refresh(run_model)
    for model in trade_models:
        db.refresh(model)

    return BacktestRunDetailResponse(
        **_to_run_summary(run_model).model_dump(),
        trades=[_to_trade_response(item) for item in trade_models],
    )
