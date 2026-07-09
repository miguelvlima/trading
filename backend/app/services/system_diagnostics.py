"""Aggregated runtime diagnostics for the Configuração → Sistema panel.

One place that answers "está tudo a postos para a app correr?": database,
IB Gateway socket, feed worker, freshness of persisted bars, paper engine and
the effective environment. Every check is read-only and side-effect free — no
new IBKR client sessions are opened (that would burn client ids and market-data
lines), only a bare TCP probe against the Gateway port.

Checks accept their dependencies (session, settings, port prober, clock) so the
whole module is unit-testable offline, mirroring the rest of the codebase.
"""

from __future__ import annotations

import socket
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.models import Instrument, MarketBar, PaperPortfolio
from app.services.data_feed.service import DataFeedService
from app.services.data_feed.types import timeframe_seconds
from app.services.paper_trading.runtime import registry

STATUS_OK = "ok"
STATUS_WARN = "warn"
STATUS_FAIL = "fail"

_SEVERITY = {STATUS_OK: 0, STATUS_WARN: 1, STATUS_FAIL: 2}


@dataclass(frozen=True)
class CheckResult:
    """One diagnostic verdict, ready to serialize to the frontend."""

    key: str
    label: str
    status: str
    detail: str
    hint: str | None = None
    data: dict = field(default_factory=dict)


def worst_status(results: list[CheckResult]) -> str:
    if not results:
        return STATUS_WARN
    return max((r.status for r in results), key=lambda s: _SEVERITY.get(s, 1))


# Mirrors frontend/src/market/dataFreshness.ts — keep the two in sync so the
# painel Sistema and the chart warnings never disagree about "obsoleto".
STALE_THRESHOLDS: dict[str, timedelta] = {
    "1m": timedelta(hours=2),
    "5m": timedelta(hours=6),
    "15m": timedelta(hours=12),
    "30m": timedelta(hours=24),
    "1h": timedelta(days=2),
    "4h": timedelta(days=3),
    "1d": timedelta(days=3),
    "1w": timedelta(days=14),
}
DEFAULT_STALE_THRESHOLD = timedelta(days=3)


def freshness_verdict(
    timeframe: str, last_bar: datetime | None, now: datetime
) -> tuple[str, float | None]:
    """(status, age_seconds) for a symbol/timeframe series; missing bars => fail."""
    if last_bar is None:
        return STATUS_FAIL, None
    if last_bar.tzinfo is None:
        last_bar = last_bar.replace(tzinfo=UTC)
    age = (now - last_bar).total_seconds()
    threshold = STALE_THRESHOLDS.get(timeframe, DEFAULT_STALE_THRESHOLD)
    return (STATUS_WARN if age > threshold.total_seconds() else STATUS_OK), age


PortProbe = Callable[[str, int, float], bool]


def default_port_probe(host: str, port: int, timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# Standard IBKR API ports: 4001/4002 Gateway live/paper, 7496/7497 TWS live/paper.
GATEWAY_KNOWN_PORTS = (4002, 4001, 7497, 7496)


def check_gateway_socket(settings: Settings, probe: PortProbe | None = None) -> CheckResult:
    prober = probe or default_port_probe
    host = settings.ibkr_gateway_host
    port = settings.ibkr_gateway_port
    if prober(host, port, 1.5):
        return CheckResult(
            key="gateway",
            label="IB Gateway (socket)",
            status=STATUS_OK,
            detail=f"Porta {host}:{port} aberta.",
            data={"host": host, "port": port},
        )

    # The configured port is closed; sniff the sibling API ports so the hint
    # can say "o Gateway parece estar noutra porta" instead of just "fechado".
    open_sibling = next(
        (p for p in GATEWAY_KNOWN_PORTS if p != port and prober(host, p, 0.8)),
        None,
    )
    if open_sibling is not None:
        return CheckResult(
            key="gateway",
            label="IB Gateway (socket)",
            status=STATUS_FAIL,
            detail=f"Porta configurada {host}:{port} fechada, mas {open_sibling} está aberta.",
            hint=(
                f"O Gateway parece estar na porta {open_sibling}. Ajusta IBKR_GATEWAY_PORT "
                f"ou o socket port do Gateway (paper=4002, live=4001)."
            ),
            data={"host": host, "port": port, "open_sibling_port": open_sibling},
        )
    return CheckResult(
        key="gateway",
        label="IB Gateway (socket)",
        status=STATUS_FAIL,
        detail=f"Porta {host}:{port} fechada e nenhuma porta IBKR conhecida aberta.",
        hint="Abre o IB Gateway (paper) e confirma o socket port em Configure → API → Settings.",
        data={"host": host, "port": port},
    )


def _alembic_heads() -> set[str] | None:
    """Repo migration heads, or None when the alembic scripts are unavailable."""
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        ini = Path(__file__).resolve().parents[2] / "alembic.ini"
        if not ini.exists():
            return None
        script = ScriptDirectory.from_config(Config(str(ini)))
        return set(script.get_heads())
    except Exception:  # noqa: BLE001 - diagnostics must never raise
        return None


def check_database(db: Session) -> CheckResult:
    try:
        db.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001 - report, never raise
        return CheckResult(
            key="database",
            label="Base de dados",
            status=STATUS_FAIL,
            detail=f"Ligação falhou: {exc}",
            hint="Confirma o Postgres (docker: trading_postgres) e o DATABASE_URL.",
        )

    instruments = db.execute(select(func.count(Instrument.id))).scalar_one()
    latest_bar = db.execute(select(func.max(MarketBar.timestamp))).scalar_one_or_none()

    revision: str | None = None
    try:
        revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    except Exception:  # noqa: BLE001 - table may not exist (fresh/test DB)
        revision = None

    data = {
        "instruments": int(instruments),
        "latest_bar": latest_bar.isoformat() if latest_bar is not None else None,
        "revision": revision,
    }
    if revision is None:
        return CheckResult(
            key="database",
            label="Base de dados",
            status=STATUS_WARN,
            detail="Ligação OK, mas sem registo de migrações (alembic_version).",
            hint="Corre `alembic upgrade head` no backend.",
            data=data,
        )

    heads = _alembic_heads()
    if heads is not None and revision not in heads:
        return CheckResult(
            key="database",
            label="Base de dados",
            status=STATUS_WARN,
            detail=f"Migração da BD ({revision}) difere do head do repositório.",
            hint="Corre `alembic upgrade head` no backend.",
            data={**data, "heads": sorted(heads)},
        )
    return CheckResult(
        key="database",
        label="Base de dados",
        status=STATUS_OK,
        detail=f"Ligação OK · {instruments} instrumentos · migração {revision}.",
        data=data,
    )


def check_feed_worker(db: Session, settings: Settings) -> CheckResult:
    timeframe = settings.realtime_feed_timeframe
    stale_after = settings.realtime_feed_stale_after_seconds
    interval = timeframe_seconds(timeframe)
    if interval is not None:
        # Same 3-interval rule as /realtime/health: a 1d feed is naturally a
        # day "behind", a flat threshold would always read stale.
        stale_after = max(stale_after, int(3 * interval))

    service = DataFeedService(db, provider_name=settings.realtime_feed_provider)
    health = service.get_health(
        settings.realtime_feed_symbol_list, timeframe, stale_after_seconds=stale_after
    )
    status_map = {"running": STATUS_OK, "stale": STATUS_WARN, "empty": STATUS_WARN}
    status = status_map.get(health.status, STATUS_FAIL)
    lag = f" · lag {int(health.lag_seconds)}s" if health.lag_seconds is not None else ""
    detail = (
        f"Estado '{health.status}' ({health.provider}) para "
        f"{', '.join(health.tracked_symbols)} em {timeframe}{lag}."
    )
    hint = None
    if status != STATUS_OK:
        hint = "Confirma o worker de ingestão e a ligação IBKR; vê os erros recentes."
    return CheckResult(
        key="feed_worker",
        label="Feed worker (ingestão)",
        status=status,
        detail=detail,
        hint=hint,
        data={
            "provider": health.provider,
            "status": health.status,
            "lag_seconds": health.lag_seconds,
            "recent_errors": list(health.recent_errors),
        },
    )


_FRESHNESS_MAX_LISTED = 6


def check_bar_freshness(
    db: Session, settings: Settings, now: datetime | None = None
) -> CheckResult:
    now = now or datetime.now(UTC)
    timeframes = [tf for tf in settings.realtime_feed_timeframe_list if tf in STALE_THRESHOLDS]
    followed = (
        db.execute(
            select(Instrument.symbol).where(Instrument.followed.is_(True)).order_by(
                Instrument.symbol
            )
        )
        .scalars()
        .all()
    )
    if not followed or not timeframes:
        return CheckResult(
            key="bar_freshness",
            label="Frescura das barras na BD",
            status=STATUS_WARN,
            detail="Sem instrumentos seguidos (ou timeframes) para verificar.",
            hint="Segue pelo menos um símbolo na barra de pesquisa do Mercado.",
        )

    rows = db.execute(
        select(Instrument.symbol, MarketBar.timeframe, func.max(MarketBar.timestamp))
        .join(Instrument, MarketBar.instrument_id == Instrument.id)
        .where(Instrument.symbol.in_(followed), MarketBar.timeframe.in_(timeframes))
        .group_by(Instrument.symbol, MarketBar.timeframe)
    ).all()
    latest = {(symbol, timeframe): ts for symbol, timeframe, ts in rows}

    problems: list[str] = []
    total = 0
    for symbol in followed:
        for timeframe in timeframes:
            total += 1
            verdict, age = freshness_verdict(timeframe, latest.get((symbol, timeframe)), now)
            if verdict == STATUS_FAIL:
                problems.append(f"{symbol} {timeframe} (sem barras)")
            elif verdict == STATUS_WARN:
                problems.append(f"{symbol} {timeframe} (há {_format_age(age)})")

    if not problems:
        return CheckResult(
            key="bar_freshness",
            label="Frescura das barras na BD",
            status=STATUS_OK,
            detail=f"{total} séries seguidas dentro dos limiares de frescura.",
            data={"series_total": total},
        )
    listed = ", ".join(problems[:_FRESHNESS_MAX_LISTED])
    more = f" (+{len(problems) - _FRESHNESS_MAX_LISTED})" if len(problems) > _FRESHNESS_MAX_LISTED else ""
    return CheckResult(
        key="bar_freshness",
        label="Frescura das barras na BD",
        status=STATUS_WARN,
        detail=f"{len(problems)} de {total} séries obsoletas ou vazias: {listed}{more}.",
        hint=(
            "Liga o feed IBKR / worker, ou acrescenta os símbolos a "
            "REALTIME_FEED_SYMBOLS para serem persistidos."
        ),
        data={"series_total": total, "series_stale": len(problems), "problems": problems},
    )


def _format_age(age_seconds: float | None) -> str:
    if age_seconds is None:
        return "—"
    if age_seconds >= 172_800:
        return f"{int(age_seconds // 86_400)} dia(s)"
    if age_seconds >= 7_200:
        return f"{int(age_seconds // 3_600)} h"
    return f"{int(age_seconds // 60)} min"


def check_paper_engine(db: Session) -> CheckResult:
    portfolios = db.execute(select(PaperPortfolio)).scalars().all()
    running_ids = set(registry.running_ids())
    flagged = [p for p in portfolios if p.engine_running]
    kill_switch = [p for p in portfolios if p.kill_switch_active]
    # Flag na BD sem runtime em memória = engine perdido num restart.
    orphaned = [p for p in flagged if p.id not in running_ids]

    data = {
        "portfolios": len(portfolios),
        "running": len(running_ids),
        "kill_switch_active": len(kill_switch),
    }
    if kill_switch:
        return CheckResult(
            key="paper_engine",
            label="Engine paper trading",
            status=STATUS_WARN,
            detail=f"Kill switch ativo em {len(kill_switch)} portfolio(s).",
            hint="Vê o motivo no cockpit Paper e faz reset ao kill switch se fizer sentido.",
            data=data,
        )
    if orphaned:
        return CheckResult(
            key="paper_engine",
            label="Engine paper trading",
            status=STATUS_WARN,
            detail=f"{len(orphaned)} portfolio(s) marcados como ligados mas sem runtime em memória.",
            hint="Reinicia o engine no cockpit Paper (o backend terá reiniciado entretanto).",
            data=data,
        )
    detail = (
        f"{len(running_ids)} engine(s) a correr."
        if running_ids
        else "Engine parado (nenhum runtime ativo)."
    )
    return CheckResult(
        key="paper_engine",
        label="Engine paper trading",
        status=STATUS_OK,
        detail=detail,
        data=data,
    )


_MARKET_DATA_TYPE_LABELS = {1: "live", 2: "frozen", 3: "delayed", 4: "delayed-frozen"}


def check_environment(settings: Settings) -> CheckResult:
    md_type = _MARKET_DATA_TYPE_LABELS.get(settings.ibkr_market_data_type, "?")
    return CheckResult(
        key="environment",
        label="Ambiente",
        status=STATUS_OK,
        detail=(
            f"Modo {settings.mode.upper()} · provider {settings.realtime_feed_provider} · "
            f"market data {md_type} · Gateway {settings.ibkr_gateway_host}:"
            f"{settings.ibkr_gateway_port}."
        ),
        data={
            "mode": settings.mode.upper(),
            "env": settings.env,
            "provider": settings.realtime_feed_provider,
            "market_data_type": md_type,
            "gateway_host": settings.ibkr_gateway_host,
            "gateway_port": settings.ibkr_gateway_port,
            "client_ids": [settings.ibkr_client_id],
            "feed_symbols": settings.realtime_feed_symbol_list,
            "feed_timeframes": settings.realtime_feed_timeframe_list,
            "cors_origins": settings.cors_origins,
        },
    )


def run_all_checks(
    db: Session,
    settings: Settings,
    *,
    probe: PortProbe | None = None,
    now: datetime | None = None,
) -> list[CheckResult]:
    """All diagnostics, worst problems first. Never raises — a broken check
    reports itself as a failed CheckResult instead of taking the endpoint down."""
    checks: list[CheckResult] = []
    for factory in (
        lambda: check_database(db),
        lambda: check_gateway_socket(settings, probe),
        lambda: check_feed_worker(db, settings),
        lambda: check_bar_freshness(db, settings, now),
        lambda: check_paper_engine(db),
        lambda: check_environment(settings),
    ):
        try:
            checks.append(factory())
        except Exception as exc:  # noqa: BLE001 - diagnostics must never raise
            checks.append(
                CheckResult(
                    key="internal",
                    label="Diagnóstico",
                    status=STATUS_FAIL,
                    detail=f"Verificação rebentou: {exc}",
                )
            )
    checks.sort(key=lambda c: -_SEVERITY.get(c.status, 1))
    return checks
