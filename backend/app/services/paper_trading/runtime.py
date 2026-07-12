from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime
from decimal import Decimal

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import (
    Instrument,
    MarketBar,
    PaperEquityPoint,
    PaperOrder,
    PaperPortfolio,
    PaperPosition,
    PaperTrade,
)
from app.db.session import SessionLocal
from app.services.data_feed.client_ids import next_engine_client_id
from app.services.data_feed.types import IndexQuote, StreamingProvider, Tick
from app.services.paper_trading.bar_aggregator import AggregatedBar, BarAggregator
from app.services.paper_trading.engine import PaperEngine
from app.services.paper_trading.events import EventHub, hub as global_hub
from app.services.paper_trading.quotes import QuoteCache
from app.services.paper_trading.types import (
    OPEN_STATUSES,
    STATUS_APPROVED,
    STATUS_PROPOSED,
    RiskSettings,
)
from app.services.strategy_engine import BarInput, run_strategy

logger = structlog.get_logger(__name__)

_LIVENESS_BY_MD_TYPE = {1: "REAL-TIME", 2: "FROZEN", 3: "DELAYED", 4: "DELAYED-FROZEN"}


def _feed_problem_message(status) -> str:
    """Ledger message that tells the user WHY the feed is not fresh."""
    if status.feed_reason == "no_provider":
        return (
            "Sem ligação ao IB Gateway — o engine não recebe cotações. "
            "Confirma que o Gateway está aberto e o provider configurado."
        )
    if status.feed_reason == "market_closed":
        return (
            "Mercado fechado — sem cotações novas (normal fora do horário 09:30–16:00 de Nova Iorque). "
            "O engine retoma quando o mercado abrir."
        )
    if status.feed_age_seconds is not None:
        return f"Feed de dados {status.feed_status} (idade {status.feed_age_seconds:.0f}s)."
    return "Feed de dados indisponível — sem ticks recebidos; verifica o IB Gateway."


def _build_streaming_provider(settings: Settings, portfolio_id: int) -> StreamingProvider | None:
    """IBKR streaming provider for one engine runtime; None without ib/Gateway.

    Mirrors the realtime WS factory but with its own client-id range (base+300+)
    so engine sessions never collide with the worker or browser WS sessions.
    Ids are pid-seeded (client_ids.py) so a second backend process or a
    --reload restart never reuses an id the Gateway still holds (error 326).
    """
    if settings.realtime_feed_provider.strip().lower() not in {"ibkr", "ib"}:
        return None
    try:
        from app.services.data_feed.providers.ibkr_provider import IBKRStreamingProvider
    except ImportError:
        logger.error("paper_engine_streaming_unavailable", hint="pip install ib_insync")
        return None
    return IBKRStreamingProvider(
        host=settings.ibkr_gateway_host,
        port=settings.ibkr_gateway_port,
        client_id=next_engine_client_id(settings.ibkr_client_id),
        market_data_type=settings.ibkr_market_data_type,
    )


# IBKR delayed market-data lines are a finite resource (~100); keep a margin
# for the realtime tab and worker. Priority order below decides who survives.
MAX_TRACKED_SYMBOLS = 24


def compute_tracked_symbols(
    db: Session, risk: RiskSettings, settings: Settings, portfolio_id: int
) -> list[str]:
    """Default follow list for the paper engine.

    Union, in priority order: symbols with something OPEN (positions or
    proposed/approved orders — these NEED quotes), the user's manual picks,
    symbols with positive realized-PnL history, and everything followed in the
    Mercado tab. Manual picks ADD to the defaults, they don't replace them.
    """
    open_symbols = set(
        db.execute(
            select(PaperPosition.symbol).where(
                PaperPosition.portfolio_id == portfolio_id,
                PaperPosition.quantity > 0,
            )
        ).scalars()
    ) | set(
        db.execute(
            select(PaperOrder.symbol).where(
                PaperOrder.portfolio_id == portfolio_id,
                PaperOrder.status.in_(OPEN_STATUSES),
            )
        ).scalars()
    )
    positive_history = {
        symbol
        for symbol, total in db.execute(
            select(PaperTrade.symbol, func.sum(PaperTrade.realized_pnl))
            .where(
                PaperTrade.portfolio_id == portfolio_id,
                PaperTrade.realized_pnl.is_not(None),
            )
            .group_by(PaperTrade.symbol)
        )
        if total is not None and float(total) > 0
    }
    followed = set(
        db.execute(select(Instrument.symbol).where(Instrument.followed.is_(True))).scalars()
    )

    ordered: list[str] = []
    for group in (
        sorted(open_symbols),
        [s.upper() for s in risk.symbols],
        sorted(positive_history),
        sorted(followed),
    ):
        for symbol in group:
            normalized = symbol.upper()
            if normalized not in ordered:
                ordered.append(normalized)

    if not ordered:
        ordered = [s.upper() for s in settings.realtime_feed_symbol_list]
    if len(ordered) > MAX_TRACKED_SYMBOLS:
        logger.warning(
            "paper_tracked_symbols_capped",
            portfolio_id=portfolio_id,
            kept=MAX_TRACKED_SYMBOLS,
            dropped=ordered[MAX_TRACKED_SYMBOLS:],
        )
        ordered = ordered[:MAX_TRACKED_SYMBOLS]
    return ordered


def load_strategy_bars(
    db: Session, symbol: str, timeframe: str, limit: int
) -> list[BarInput]:
    """Most recent CLOSED bars for the strategies, oldest first.

    The engine evaluates closed bars only (no forming bar): the anti-lookahead
    contract stays intact and a proposal never rides a candle that could still
    reverse. Freshness of the *fill* is guarded separately by the QuoteCache.
    """
    rows = list(
        db.execute(
            select(MarketBar)
            .join(Instrument, MarketBar.instrument_id == Instrument.id)
            .where(Instrument.symbol == symbol.upper(), MarketBar.timeframe == timeframe)
            .order_by(MarketBar.timestamp.desc())
            .limit(limit)
        ).scalars()
    )
    return [
        BarInput(
            timestamp=row.timestamp,
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume),
        )
        for row in reversed(rows)
    ]


class PaperEngineRuntime:
    """Async runtime for one running portfolio engine.

    Owns the streaming provider (ticks -> QuoteCache on the provider thread) and
    a periodic asyncio task that does all DB work: evaluate strategies on closed
    bars, propose orders, retry approved-but-deferred fills, run protective
    exits, expire stale proposals and broadcast status/PnL over the hub.
    """

    def __init__(
        self,
        portfolio_id: int,
        *,
        settings: Settings,
        hub: EventHub | None = None,
        provider: StreamingProvider | None = None,
        poll_seconds: float | None = None,
    ) -> None:
        self.portfolio_id = portfolio_id
        self._settings = settings
        self._hub = hub or global_hub
        self.quotes = QuoteCache()
        self.quotes.set_liveness(
            _LIVENESS_BY_MD_TYPE.get(settings.ibkr_market_data_type, "UNKNOWN")
        )
        self.engine = PaperEngine(portfolio_id, quotes=self.quotes, hub=self._hub)
        self._provider = provider if provider is not None else _build_streaming_provider(
            settings, portfolio_id
        )
        self._poll_seconds = poll_seconds or settings.paper_engine_poll_seconds
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.tracked_symbols: list[str] = []
        # Last bar timestamp already turned into a proposal, per (symbol, strategy):
        # prevents re-proposing the same signal every poll.
        self._last_signal_bar: dict[tuple[str, str], datetime] = {}
        self._feed_was_stale = False
        # Summary of the latest strategy sweep, surfaced so the cockpit can
        # explain WHY there are no proposals instead of just looking idle.
        self.last_evaluation: dict[str, object] | None = None
        # Last outcome per (symbol, strategy) plus a per-symbol view refreshed
        # every poll — feeds the live signal monitor in the cockpit sidebar.
        self._signal_results: dict[tuple[str, str], dict[str, object]] = {}
        self.last_signals: dict[str, dict[str, object]] = {}
        self._last_equity_point_at: datetime | None = None
        # Tick -> intraday MarketBar pipeline: fed on the provider thread,
        # drained/persisted by the poll loop. Without it, strategies on a
        # "1m"/"5m" timeframe would never see a new closed bar.
        self.bar_aggregator: BarAggregator | None = (
            BarAggregator()
            if getattr(settings, "paper_engine_intraday_enabled", True)
            else None
        )

    @property
    def has_provider(self) -> bool:
        return self._provider is not None

    @property
    def poll_seconds(self) -> float:
        return self._poll_seconds

    # -- provider sinks (provider thread; must stay non-blocking, no DB) ---------

    def _on_tick(self, tick: Tick) -> None:
        self.quotes.update_from_tick(tick)
        if self.bar_aggregator is not None:
            self.bar_aggregator.update_from_tick(tick)

    def _on_index(self, quote: IndexQuote) -> None:  # engine does not use indices
        return

    # -- lifecycle ----------------------------------------------------------------

    async def start(self) -> None:
        if self._task is not None:
            return
        session = SessionLocal()
        try:
            portfolio = session.get(PaperPortfolio, self.portfolio_id)
            risk = RiskSettings.from_json(portfolio.risk_settings if portfolio else None)
            self.tracked_symbols = self._desired_symbols(session, risk)
        finally:
            session.close()

        if self._provider is not None:
            self._provider.start(self._on_tick, self._on_index)
            for symbol in self.tracked_symbols:
                self._provider.subscribe(symbol)
        else:
            logger.warning(
                "paper_engine_no_stream_provider", portfolio_id=self.portfolio_id
            )

        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name=f"paper-engine-{self.portfolio_id}")
        logger.info(
            "paper_engine_runtime_started",
            portfolio_id=self.portfolio_id,
            symbols=self.tracked_symbols,
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._provider is not None:
            await asyncio.to_thread(self._provider.stop)
        logger.info("paper_engine_runtime_stopped", portfolio_id=self.portfolio_id)

    # -- periodic work ---------------------------------------------------------------

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(self._poll_once)
            except Exception as exc:  # noqa: BLE001 - the loop must survive anything
                logger.error(
                    "paper_engine_poll_error",
                    portfolio_id=self.portfolio_id,
                    error=str(exc),
                )
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self._poll_seconds)
            except TimeoutError:
                continue

    def _desired_symbols(self, db: Session, risk: RiskSettings) -> list[str]:
        return compute_tracked_symbols(db, risk, self._settings, self.portfolio_id)

    def _sync_tracked_symbols(self, db: Session, risk: RiskSettings) -> None:
        """Apply cockpit edits to the followed symbols without a backend restart.

        ``tracked_symbols`` is captured at start() while risk-settings edits only
        touch the DB row, so the runtime reconciles the diff every poll: new
        symbols get a live market-data line, removed ones free theirs and drop
        their cached signal state so the sidebar stops showing them.
        """
        desired = self._desired_symbols(db, risk)
        if desired == self.tracked_symbols:
            return
        current = set(self.tracked_symbols)
        added = [s for s in desired if s not in current]
        removed = [s for s in current if s not in desired]
        if self._provider is not None:
            for symbol in added:
                self._provider.subscribe(symbol)
            for symbol in removed:
                self._provider.unsubscribe(symbol)
        for symbol in removed:
            self.last_signals.pop(symbol, None)
        self._last_signal_bar = {
            k: v for k, v in self._last_signal_bar.items() if k[0] not in removed
        }
        self._signal_results = {
            k: v for k, v in self._signal_results.items() if k[0] not in removed
        }
        self.tracked_symbols = desired
        logger.info(
            "paper_engine_symbols_updated",
            portfolio_id=self.portfolio_id,
            symbols=desired,
            added=added,
            removed=removed,
        )
        from app.services.paper_trading import events as ev

        ev.record_event(
            db,
            portfolio_id=self.portfolio_id,
            event_type=ev.EVENT_SYMBOLS_UPDATED,
            message=f"Símbolos seguidos atualizados: {', '.join(desired)}.",
            payload={"symbols": desired, "added": added, "removed": removed},
            broadcast=self._hub,
        )

    def _poll_once(self) -> None:
        db = SessionLocal()
        try:
            portfolio = db.get(PaperPortfolio, self.portfolio_id)
            if portfolio is None or not portfolio.engine_running:
                return
            risk = RiskSettings.from_json(portfolio.risk_settings)
            self._sync_tracked_symbols(db, risk)

            self.engine.check_protective_exits(db, portfolio)
            self.engine.flat_eod_sweep(db, portfolio)
            self._retry_approved_orders(db, portfolio)
            self.engine.expire_stale_orders(db, portfolio)
            self._persist_intraday_bars(db)
            self._evaluate_signals(db, portfolio, risk)
            self._broadcast_state(db, portfolio, risk)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _persist_intraday_bars(self, db: Session) -> None:
        """Upsert the closed intraday buckets into MarketBar (idempotent).

        Runs before ``_evaluate_signals`` so a bar that just closed is already
        visible to ``load_strategy_bars`` in the same poll. Uses a portable
        select-then-write upsert keyed on (instrument_id, timeframe, timestamp)
        — a handful of rows per poll, so no need for dialect-specific INSERTs.
        """
        if self.bar_aggregator is None:
            return
        bars = self.bar_aggregator.drain_closed_bars(datetime.now(UTC))
        if not bars:
            return
        instrument_ids: dict[str, int] = {}
        for bar in bars:
            instrument_id = instrument_ids.get(bar.symbol)
            if instrument_id is None:
                instrument_id = self._instrument_id_for(db, bar.symbol)
                instrument_ids[bar.symbol] = instrument_id
            self._upsert_market_bar(db, instrument_id, bar)
        logger.info(
            "paper_engine_intraday_bars_persisted",
            portfolio_id=self.portfolio_id,
            bars=len(bars),
        )

    @staticmethod
    def _instrument_id_for(db: Session, symbol: str) -> int:
        instrument = db.execute(
            select(Instrument).where(Instrument.symbol == symbol)
        ).scalar_one_or_none()
        if instrument is None:
            instrument = Instrument(symbol=symbol, name=None, currency="USD")
            db.add(instrument)
            db.flush()
        return instrument.id

    @staticmethod
    def _upsert_market_bar(db: Session, instrument_id: int, bar: AggregatedBar) -> None:
        row = db.execute(
            select(MarketBar).where(
                MarketBar.instrument_id == instrument_id,
                MarketBar.timeframe == bar.timeframe,
                MarketBar.timestamp == bar.timestamp,
            )
        ).scalar_one_or_none()
        if row is None:
            db.add(
                MarketBar(
                    instrument_id=instrument_id,
                    timeframe=bar.timeframe,
                    timestamp=bar.timestamp,
                    open=Decimal(str(bar.open)),
                    high=Decimal(str(bar.high)),
                    low=Decimal(str(bar.low)),
                    close=Decimal(str(bar.close)),
                    volume=Decimal(str(bar.volume)),
                )
            )
        else:
            row.open = Decimal(str(bar.open))
            row.high = Decimal(str(bar.high))
            row.low = Decimal(str(bar.low))
            row.close = Decimal(str(bar.close))
            row.volume = Decimal(str(bar.volume))
        db.flush()

    def _retry_approved_orders(self, db: Session, portfolio: PaperPortfolio) -> None:
        approved = list(
            db.execute(
                select(PaperOrder).where(
                    PaperOrder.portfolio_id == self.portfolio_id,
                    PaperOrder.status == STATUS_APPROVED,
                )
            ).scalars()
        )
        for order in approved:
            self.engine.try_fill_order(db, portfolio, order)

    def _evaluate_signals(
        self, db: Session, portfolio: PaperPortfolio, risk: RiskSettings
    ) -> None:
        from app.services.strategy_engine import get_available_strategies

        strategies = list(risk.strategies) or get_available_strategies()
        counts = {"no_quote": 0, "no_bars": 0, "evaluated": 0, "signals": 0, "proposals": 0}
        for symbol in self.tracked_symbols:
            quote = self.quotes.get(symbol)
            if quote is None or quote.last is None or float(quote.last) <= 0:
                # No reference quote yet (startup gap / feed down). Do NOT mark
                # the bar as handled: on a 1d timeframe that would burn the
                # signal until tomorrow over a few missing ticks. Retry next poll.
                counts["no_quote"] += 1
                # Still publish the monitor view so the cockpit shows the
                # engine IS checking this symbol, just waiting for a quote.
                self.last_signals[symbol] = {
                    "checked_at": datetime.now(UTC).isoformat(),
                    "bar_time": None,
                    "no_quote": True,
                    "signals": [
                        self._signal_results.get(
                            (symbol, strategy),
                            {"strategy": strategy, "outcome": "pending"},
                        )
                        for strategy in strategies
                    ],
                }
                continue
            bars = load_strategy_bars(
                db, symbol, risk.timeframe, self._settings.paper_engine_bars_limit
            )
            if len(bars) < 30:
                counts["no_bars"] += 1
                continue
            counts["evaluated"] += 1
            last_ts = bars[-1].timestamp
            for strategy in strategies:
                key = (symbol, strategy)
                if self._last_signal_bar.get(key) == last_ts:
                    continue  # bar unchanged: the stored result still stands
                try:
                    signals = run_strategy(strategy, symbol, bars)
                except ValueError:
                    self._signal_results[key] = {"strategy": strategy, "outcome": "error"}
                    continue
                latest = [s for s in signals if s.timestamp == last_ts]
                self._last_signal_bar[key] = last_ts
                if not latest:
                    self._signal_results[key] = {"strategy": strategy, "outcome": "none"}
                    continue
                counts["signals"] += 1
                best = max(latest, key=lambda s: s.strength)
                order = self.engine.propose_from_signal(
                    db,
                    portfolio,
                    symbol=symbol,
                    direction=best.direction,
                    strength=best.strength,
                    strategy=best.strategy,
                    rationale=best.rationale,
                    signal_timestamp=best.timestamp,
                )
                if order is not None and order.status == STATUS_PROPOSED:
                    counts["proposals"] += 1
                    outcome = "proposed"
                elif order is not None:
                    outcome = "vetoed"
                else:
                    outcome = "skipped"
                self._signal_results[key] = {
                    "strategy": strategy,
                    "direction": best.direction,
                    "strength": best.strength,
                    "outcome": outcome,
                }
            # Per-symbol view refreshed EVERY poll (checked_at advances even
            # when the bar is unchanged) so the cockpit shows the true cadence.
            self.last_signals[symbol] = {
                "checked_at": datetime.now(UTC).isoformat(),
                "bar_time": last_ts.isoformat(),
                "signals": [
                    self._signal_results.get(
                        (symbol, strategy), {"strategy": strategy, "outcome": "pending"}
                    )
                    for strategy in strategies
                ],
            }
        self.last_evaluation = {
            "at": datetime.now(UTC).isoformat(),
            "symbols_total": len(self.tracked_symbols),
            "strategies": len(strategies),
            "timeframe": risk.timeframe,
            **counts,
        }

    def _broadcast_state(
        self, db: Session, portfolio: PaperPortfolio, risk: RiskSettings
    ) -> None:
        status = self.engine.status(
            db,
            portfolio,
            tracked_symbols=self.tracked_symbols,
            has_provider=self.has_provider,
        )
        if status.feed_status != "fresh" and not self._feed_was_stale:
            self._feed_was_stale = True
            from app.services.paper_trading import events as ev

            ev.record_event(
                db,
                portfolio_id=self.portfolio_id,
                event_type=ev.EVENT_FEED_STALE,
                message=_feed_problem_message(status),
                severity="warn",
                broadcast=self._hub,
            )
        elif status.feed_status == "fresh" and self._feed_was_stale:
            self._feed_was_stale = False
            from app.services.paper_trading import events as ev

            ev.record_event(
                db,
                portfolio_id=self.portfolio_id,
                event_type=ev.EVENT_FEED_RECOVERED,
                message="Feed de dados recuperado.",
                broadcast=self._hub,
            )

        pnl = self.engine.pnl_snapshot(db, portfolio)
        positions = []
        for pos in self.engine._positions(db):
            provenance = self.engine.position_provenance(db, pos)
            opened_at = provenance["opened_at"]
            positions.append(
                {
                    "symbol": pos.symbol,
                    "quantity": float(pos.quantity),
                    "avg_entry_price": float(pos.avg_entry_price),
                    "last_price": self.engine._mark_price(pos),
                    "unrealized_pnl": (
                        (self.engine._mark_price(pos) - float(pos.avg_entry_price))
                        * float(pos.quantity)
                    ),
                    "opened_at": opened_at.isoformat() if opened_at else None,
                    "strategy": provenance["strategy"],
                    "rationale": provenance["rationale"],
                    "stop_price": provenance["stop_price"],
                    "take_profit_price": provenance["take_profit_price"],
                }
            )

        now = datetime.now(UTC)
        self._persist_equity_point(db, pnl, now)
        self._hub.publish(
            self.portfolio_id,
            {
                "type": "engine_state",
                "status": {
                    **status.__dict__,
                    "last_evaluation": self.last_evaluation,
                    "poll_seconds": self._poll_seconds,
                },
                "pnl": pnl,
                "positions": positions,
                "signals": self.last_signals,
                "at": now.isoformat(),
            },
        )

    _EQUITY_POINT_INTERVAL_SECONDS = 60.0

    def _persist_equity_point(
        self, db: Session, pnl: dict[str, float], now: datetime
    ) -> None:
        """At most one snapshot per minute — enough resolution for the curve."""
        last = self._last_equity_point_at
        if last is not None and (now - last).total_seconds() < self._EQUITY_POINT_INTERVAL_SECONDS:
            return
        self._last_equity_point_at = now
        db.add(
            PaperEquityPoint(
                portfolio_id=self.portfolio_id,
                equity=pnl["equity"],
                cash=pnl["cash"],
                at=now,
            )
        )


class RuntimeRegistry:
    """Running engine runtimes per portfolio (process-wide singleton)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runtimes: dict[int, PaperEngineRuntime] = {}

    def get(self, portfolio_id: int) -> PaperEngineRuntime | None:
        with self._lock:
            return self._runtimes.get(portfolio_id)

    def running_ids(self) -> list[int]:
        with self._lock:
            return list(self._runtimes)

    async def start(self, portfolio_id: int, settings: Settings) -> PaperEngineRuntime:
        with self._lock:
            runtime = self._runtimes.get(portfolio_id)
            if runtime is None:
                runtime = PaperEngineRuntime(portfolio_id, settings=settings)
                self._runtimes[portfolio_id] = runtime
        await runtime.start()
        return runtime

    async def stop(self, portfolio_id: int) -> None:
        with self._lock:
            runtime = self._runtimes.pop(portfolio_id, None)
        if runtime is not None:
            await runtime.stop()

    async def stop_all(self) -> None:
        with self._lock:
            runtimes = list(self._runtimes.values())
            self._runtimes.clear()
        for runtime in runtimes:
            await runtime.stop()


registry = RuntimeRegistry()


async def resume_running_engines(settings: Settings) -> list[int]:
    """Recreate runtimes for portfolios still flagged ``engine_running``.

    The registry lives in process memory: a backend restart loses every
    runtime while the DB flag stays True, so the cockpit shows "Engine LIGADO"
    with feed ``no_provider`` until the user clicks stop/start. Called from
    the app lifespan so engines survive restarts without manual intervention.
    """
    try:
        session = SessionLocal()
        try:
            portfolio_ids = list(
                session.execute(
                    select(PaperPortfolio.id).where(PaperPortfolio.engine_running.is_(True))
                ).scalars()
            )
        finally:
            session.close()
    except Exception as exc:  # noqa: BLE001 - startup must survive a missing DB
        logger.warning("paper_engine_resume_scan_failed", error=str(exc))
        return []

    resumed: list[int] = []
    for portfolio_id in portfolio_ids:
        try:
            await registry.start(portfolio_id, settings)
        except Exception as exc:  # noqa: BLE001 - one bad portfolio must not block the rest
            logger.error(
                "paper_engine_resume_failed", portfolio_id=portfolio_id, error=str(exc)
            )
            continue
        resumed.append(portfolio_id)
        logger.info("paper_engine_resumed", portfolio_id=portfolio_id)
        try:
            session = SessionLocal()
            try:
                from app.services.paper_trading import events as ev

                ev.record_event(
                    session,
                    portfolio_id=portfolio_id,
                    event_type=ev.EVENT_ENGINE_STARTED,
                    message="Engine retomado automaticamente após restart do backend.",
                    broadcast=global_hub,
                )
                session.commit()
            finally:
                session.close()
        except Exception as exc:  # noqa: BLE001 - ledger is best-effort here
            logger.warning(
                "paper_engine_resume_event_failed", portfolio_id=portfolio_id, error=str(exc)
            )
    return resumed
