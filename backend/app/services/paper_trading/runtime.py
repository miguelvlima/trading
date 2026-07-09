from __future__ import annotations

import asyncio
import itertools
import threading
from datetime import UTC, datetime

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Instrument, MarketBar, PaperOrder, PaperPortfolio
from app.db.session import SessionLocal
from app.services.data_feed.types import IndexQuote, StreamingProvider, Tick
from app.services.paper_trading.engine import PaperEngine
from app.services.paper_trading.events import EventHub, hub as global_hub
from app.services.paper_trading.quotes import QuoteCache
from app.services.paper_trading.types import STATUS_APPROVED, RiskSettings
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
            "Mercado fechado — sem cotações novas (normal fora do horário 13:30–20:00 UTC). "
            "O engine retoma quando o mercado abrir."
        )
    if status.feed_age_seconds is not None:
        return f"Feed de dados {status.feed_status} (idade {status.feed_age_seconds:.0f}s)."
    return "Feed de dados indisponível — sem ticks recebidos; verifica o IB Gateway."


# Rotating suffix per runtime start: a stop->start within seconds would reuse a
# client id the Gateway still considers connected (error 326), like the WS
# sessions in realtime_ws.py. Range base+300..base+499 stays clear of theirs.
_engine_client_seq = itertools.count()


def _build_streaming_provider(settings: Settings, portfolio_id: int) -> StreamingProvider | None:
    """IBKR streaming provider for one engine runtime; None without ib/Gateway.

    Mirrors the realtime WS factory but with its own client-id range (base+300+)
    so engine sessions never collide with the worker or browser WS sessions.
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
        client_id=settings.ibkr_client_id + 300 + (next(_engine_client_seq) % 200),
        market_data_type=settings.ibkr_market_data_type,
    )


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

    @property
    def has_provider(self) -> bool:
        return self._provider is not None

    # -- provider sinks (provider thread; must stay non-blocking, no DB) ---------

    def _on_tick(self, tick: Tick) -> None:
        self.quotes.update_from_tick(tick)

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
            self.tracked_symbols = list(
                risk.symbols or self._settings.realtime_feed_symbol_list
            )
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

    def _poll_once(self) -> None:
        db = SessionLocal()
        try:
            portfolio = db.get(PaperPortfolio, self.portfolio_id)
            if portfolio is None or not portfolio.engine_running:
                return
            risk = RiskSettings.from_json(portfolio.risk_settings)

            self.engine.check_protective_exits(db, portfolio)
            self._retry_approved_orders(db, portfolio)
            self.engine.expire_stale_proposals(db, portfolio)
            self._evaluate_signals(db, portfolio, risk)
            self._broadcast_state(db, portfolio, risk)
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

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
        for symbol in self.tracked_symbols:
            quote = self.quotes.get(symbol)
            if quote is None or quote.last is None or float(quote.last) <= 0:
                # No reference quote yet (startup gap / feed down). Do NOT mark
                # the bar as handled: on a 1d timeframe that would burn the
                # signal until tomorrow over a few missing ticks. Retry next poll.
                continue
            bars = load_strategy_bars(
                db, symbol, risk.timeframe, self._settings.paper_engine_bars_limit
            )
            if len(bars) < 30:
                continue
            last_ts = bars[-1].timestamp
            for strategy in strategies:
                key = (symbol, strategy)
                if self._last_signal_bar.get(key) == last_ts:
                    continue
                try:
                    signals = run_strategy(strategy, symbol, bars)
                except ValueError:
                    continue
                latest = [s for s in signals if s.timestamp == last_ts]
                self._last_signal_bar[key] = last_ts
                if not latest:
                    continue
                best = max(latest, key=lambda s: s.strength)
                self.engine.propose_from_signal(
                    db,
                    portfolio,
                    symbol=symbol,
                    direction=best.direction,
                    strength=best.strength,
                    strategy=best.strategy,
                    rationale=best.rationale,
                    signal_timestamp=best.timestamp,
                )

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
            opened_at, strategy, rationale = self.engine.entry_context(db, pos.symbol)
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
                    "strategy": strategy,
                    "rationale": rationale,
                }
            )
        self._hub.publish(
            self.portfolio_id,
            {
                "type": "engine_state",
                "status": status.__dict__,
                "pnl": pnl,
                "positions": positions,
                "at": datetime.now(UTC).isoformat(),
            },
        )


class RuntimeRegistry:
    """Running engine runtimes per portfolio (process-wide singleton)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._runtimes: dict[int, PaperEngineRuntime] = {}

    def get(self, portfolio_id: int) -> PaperEngineRuntime | None:
        with self._lock:
            return self._runtimes.get(portfolio_id)

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


registry = RuntimeRegistry()
