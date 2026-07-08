import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { fmtPrice } from "../realtime/format";
import {
  approvePaperOrder,
  createPaperPortfolio,
  getEngineStatus,
  getPaperEvents,
  getPaperOrders,
  getPaperPnl,
  getPaperPortfolio,
  getPaperPositions,
  rejectPaperOrder,
  resetKillSwitch,
  startEngine,
  stopEngine,
  PaperApiError,
  type EngineStatusWire,
  type PaperOrder,
  type PaperPortfolio,
} from "./api";
import { affectsPendingOrders, eventTone } from "./streamReducer";
import { usePaperStream } from "./usePaperStream";

type PaperPageProps = {
  apiBaseUrl: string;
  authToken: string;
};

function fmtTime(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return "—";
  return parsed.toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function fmtMoney(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  });
}

function fmtSigned(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${fmtMoney(value)}`;
}

function pnlClass(value: number | null | undefined): string {
  if (value === null || value === undefined || value === 0) return "";
  return value > 0 ? "rt-up" : "rt-down";
}

// -- status bar ---------------------------------------------------------------

function FeedDot({ status }: { status: EngineStatusWire | null }) {
  const level =
    status === null || status.feed_status === "unavailable"
      ? "down"
      : status.feed_status === "stale"
        ? "warn"
        : "up";
  const label =
    status === null
      ? "sem estado"
      : status.feed_status === "fresh"
        ? `fresco (${status.feed_age_seconds?.toFixed(0) ?? "?"}s)`
        : status.feed_status === "stale"
          ? `obsoleto (${status.feed_age_seconds?.toFixed(0) ?? "?"}s)`
          : "indisponível";
  return (
    <span className={`pp-feed pp-feed-${level}`}>
      <i className="rt-dot" /> Feed {label}
    </span>
  );
}

function StatusBar({
  status,
  wsStatus,
  onStart,
  onStop,
  onResetKillSwitch,
  busy,
}: {
  status: EngineStatusWire | null;
  wsStatus: "connecting" | "open" | "closed";
  onStart: () => void;
  onStop: () => void;
  onResetKillSwitch: () => void;
  busy: boolean;
}) {
  const running = status?.running ?? false;
  return (
    <div className="pp-statusbar">
      <span className={running ? "pp-engine pp-engine-on" : "pp-engine pp-engine-off"}>
        <i className="rt-dot" /> Engine {running ? "LIGADO" : "PARADO"}
      </span>
      <button
        type="button"
        className="pp-btn"
        disabled={busy}
        onClick={running ? onStop : onStart}
      >
        {running ? "Parar" : "Iniciar"}
      </button>
      <FeedDot status={status} />
      {status?.data_liveness === "DELAYED" && (
        <span className="pp-badge pp-badge-warn">DADOS ATRASADOS ~15 min</span>
      )}
      <span className="pp-muted">
        Sessão: {status?.market_session === "rth" ? "mercado aberto" : "fechado"}
      </span>
      {status?.cooldown_until && (
        <span className="pp-badge pp-badge-warn">
          cooldown até {fmtTime(status.cooldown_until)}
        </span>
      )}
      <span className={wsStatus === "open" ? "pp-muted" : "pp-badge pp-badge-warn"}>
        WS {wsStatus === "open" ? "ligado" : wsStatus === "connecting" ? "a ligar…" : "desligado — a religar"}
      </span>
      {status?.kill_switch_active && (
        <span className="pp-killswitch">
          KILL SWITCH — {status.kill_switch_reason ?? "ativo"}
          <button type="button" className="pp-btn pp-btn-danger" onClick={onResetKillSwitch}>
            Rearmar
          </button>
        </span>
      )}
    </div>
  );
}

// -- pending orders -------------------------------------------------------------

function PendingOrderCard({
  order,
  onApprove,
  onReject,
  busy,
}: {
  order: PaperOrder;
  onApprove: (id: number) => void;
  onReject: (id: number) => void;
  busy: boolean;
}) {
  const signal = order.signal_snapshot as {
    strategy?: string;
    rationale?: string;
    strength?: number;
  };
  const risk = order.risk_snapshot as { position_pct_of_equity?: number | null };
  return (
    <div className="rt-card pp-order-card">
      <div className="rt-card-h">
        <span className="rt-card-t">
          <b className={order.side === "BUY" ? "rt-up" : "rt-down"}>{order.side}</b>{" "}
          {order.quantity.toLocaleString()} {order.symbol} @ mercado
        </span>
        <span className="pp-muted">{fmtTime(order.proposed_at)}</span>
      </div>
      {signal.rationale && (
        <p className="pp-order-rationale">
          {signal.strategy ? `${signal.strategy}: ` : ""}
          {signal.rationale}
        </p>
      )}
      <div className="pp-order-meta">
        {order.stop_loss_pct !== null && <span>stop {order.stop_loss_pct.toFixed(1)}%</span>}
        {order.take_profit_pct !== null && <span>TP {order.take_profit_pct.toFixed(1)}%</span>}
        {typeof risk.position_pct_of_equity === "number" && (
          <span>{risk.position_pct_of_equity.toFixed(1)}% do portfolio</span>
        )}
        <span className="pp-muted">{order.data_liveness}</span>
      </div>
      <div className="pp-order-actions">
        <button
          type="button"
          className="pp-btn pp-btn-approve"
          disabled={busy}
          onClick={() => onApprove(order.id)}
        >
          Aprovar
        </button>
        <button
          type="button"
          className="pp-btn pp-btn-reject"
          disabled={busy}
          onClick={() => onReject(order.id)}
        >
          Rejeitar
        </button>
      </div>
    </div>
  );
}

// -- equity sparkline -------------------------------------------------------------

function EquitySparkline({ points }: { points: Array<{ at: string; equity: number }> }) {
  if (points.length < 2) {
    return <p className="pp-muted">A curva intraday aparece com o engine ligado.</p>;
  }
  const values = points.map((point) => point.equity);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const width = 560;
  const height = 96;
  const step = width / (points.length - 1);
  const path = points
    .map((point, index) => {
      const x = index * step;
      const y = height - ((point.equity - min) / span) * (height - 8) - 4;
      return `${index === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`;
    })
    .join(" ");
  const rising = values[values.length - 1] >= values[0];
  return (
    <svg
      className="pp-sparkline"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label="Curva de equity intraday"
    >
      <path d={path} fill="none" strokeWidth="2" className={rising ? "pp-line-up" : "pp-line-down"} />
    </svg>
  );
}

// -- page ------------------------------------------------------------------------

export function PaperPage({ apiBaseUrl, authToken }: PaperPageProps) {
  const [portfolio, setPortfolio] = useState<PaperPortfolio | null>(null);
  const [portfolioMissing, setPortfolioMissing] = useState(false);
  const [initialCash, setInitialCash] = useState("100000");
  const [pending, setPending] = useState<PaperOrder[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [restStatus, setRestStatus] = useState<EngineStatusWire | null>(null);

  const hasPortfolio = portfolio !== null;
  const { state, dispatch, status: wsStatus, error: wsError } = usePaperStream(
    apiBaseUrl,
    authToken,
    hasPortfolio,
  );
  const status = state.status ?? restStatus;

  const fail = useCallback((err: unknown) => {
    setError(err instanceof Error ? err.message : String(err));
  }, []);

  const loadPortfolio = useCallback(async () => {
    try {
      const loaded = await getPaperPortfolio(apiBaseUrl, authToken);
      setPortfolio(loaded);
      setPortfolioMissing(false);
    } catch (err) {
      if (err instanceof PaperApiError && err.status === 404) {
        setPortfolioMissing(true);
      } else {
        fail(err);
      }
    }
  }, [apiBaseUrl, authToken, fail]);

  const refreshPending = useCallback(async () => {
    try {
      setPending(await getPaperOrders(apiBaseUrl, authToken, "proposed"));
    } catch (err) {
      fail(err);
    }
  }, [apiBaseUrl, authToken, fail]);

  // Initial load: portfolio, then seed the cockpit from REST.
  useEffect(() => {
    void loadPortfolio();
  }, [loadPortfolio]);

  useEffect(() => {
    if (!hasPortfolio) return;
    void (async () => {
      try {
        const [events, engineStatus, pnl, positions] = await Promise.all([
          getPaperEvents(apiBaseUrl, authToken, 50),
          getEngineStatus(apiBaseUrl, authToken),
          getPaperPnl(apiBaseUrl, authToken),
          getPaperPositions(apiBaseUrl, authToken),
        ]);
        dispatch({ kind: "seed_events", events });
        setRestStatus(engineStatus);
        dispatch({
          kind: "seed_state",
          pnl,
          positions: positions.map((position) => ({
            symbol: position.symbol,
            quantity: position.quantity,
            avg_entry_price: position.avg_entry_price,
            last_price: position.last_price,
            unrealized_pnl: position.unrealized_pnl,
          })),
        });
        await refreshPending();
      } catch (err) {
        fail(err);
      }
    })();
  }, [hasPortfolio, apiBaseUrl, authToken, dispatch, refreshPending, fail]);

  // Refetch the pending panel when an order-lifecycle event streams in.
  const lastHandledEvent = useRef<number | null>(null);
  useEffect(() => {
    const newest = state.events[0];
    if (!newest || newest.id === lastHandledEvent.current) return;
    lastHandledEvent.current = newest.id;
    if (affectsPendingOrders(newest.event_type)) void refreshPending();
  }, [state.events, refreshPending]);

  const act = useCallback(
    async (action: () => Promise<unknown>, refresh = true) => {
      setBusy(true);
      setError(null);
      try {
        await action();
        if (refresh) {
          await refreshPending();
          setRestStatus(await getEngineStatus(apiBaseUrl, authToken));
        }
      } catch (err) {
        fail(err);
      } finally {
        setBusy(false);
      }
    },
    [apiBaseUrl, authToken, refreshPending, fail],
  );

  const totalUnrealized = useMemo(
    () =>
      state.positions.reduce(
        (sum, position) => sum + (position.unrealized_pnl ?? 0),
        0,
      ),
    [state.positions],
  );

  if (portfolioMissing) {
    return (
      <div className="rt-page pp-page">
        <div className="rt-card pp-setup-card">
          <div className="rt-card-h">
            <span className="rt-card-t">Paper Trading</span>
          </div>
          <p>
            Ainda não tens um portfolio virtual. Define o cash inicial e cria um —
            nenhuma ordem real é enviada em circunstância alguma.
          </p>
          <div className="pp-setup-row">
            <input
              className="pp-input"
              type="number"
              min={1000}
              step={1000}
              value={initialCash}
              onChange={(event) => setInitialCash(event.target.value)}
            />
            <button
              type="button"
              className="pp-btn pp-btn-approve"
              disabled={busy}
              onClick={() =>
                void act(async () => {
                  const created = await createPaperPortfolio(
                    apiBaseUrl,
                    authToken,
                    Number(initialCash) || 100_000,
                  );
                  setPortfolio(created);
                  setPortfolioMissing(false);
                }, false)
              }
            >
              Criar portfolio
            </button>
          </div>
          {error && <p className="pp-error">{error}</p>}
        </div>
      </div>
    );
  }

  return (
    <div className="rt-page pp-page">
      <StatusBar
        status={status}
        wsStatus={wsStatus}
        busy={busy}
        onStart={() => void act(() => startEngine(apiBaseUrl, authToken))}
        onStop={() => void act(() => stopEngine(apiBaseUrl, authToken))}
        onResetKillSwitch={() => void act(() => resetKillSwitch(apiBaseUrl, authToken))}
      />
      {(error || wsError) && <p className="pp-error">{error ?? wsError}</p>}

      <div className="pp-grid">
        <section className="rt-card pp-panel">
          <div className="rt-card-h">
            <span className="rt-card-t">Ordens pendentes</span>
            <span className="rt-badge">{pending.length}</span>
          </div>
          {pending.length === 0 ? (
            <p className="pp-muted">
              {status?.running
                ? "Sem propostas por decidir. O engine propõe quando houver sinal."
                : "Engine parado — liga-o para receber propostas de ordens."}
            </p>
          ) : (
            pending.map((order) => (
              <PendingOrderCard
                key={order.id}
                order={order}
                busy={busy}
                onApprove={(id) => void act(() => approvePaperOrder(apiBaseUrl, authToken, id))}
                onReject={(id) => void act(() => rejectPaperOrder(apiBaseUrl, authToken, id))}
              />
            ))
          )}
        </section>

        <section className="rt-card pp-panel pp-panel-feed">
          <div className="rt-card-h">
            <span className="rt-card-t">Atividade do engine</span>
            <span className="rt-badge rt-badge-live">● AO VIVO</span>
          </div>
          <ul className="pp-feed-list">
            {state.events.length === 0 && (
              <li className="pp-muted">Sem eventos ainda.</li>
            )}
            {state.events.map((event) => (
              <li key={event.id} className={`pp-event pp-event-${eventTone(event)}`}>
                <span className="pp-event-time">{fmtTime(event.created_at)}</span>
                {event.symbol && <span className="pp-event-symbol">{event.symbol}</span>}
                <span className="pp-event-msg">{event.message}</span>
              </li>
            ))}
          </ul>
        </section>

        <section className="rt-card pp-panel">
          <div className="rt-card-h">
            <span className="rt-card-t">Posições abertas</span>
          </div>
          {state.positions.length === 0 ? (
            <p className="pp-muted">Sem posições abertas.</p>
          ) : (
            <table className="pp-table">
              <thead>
                <tr>
                  <th>Símbolo</th>
                  <th>Qtd</th>
                  <th>P. médio</th>
                  <th>Último</th>
                  <th>PnL n/ realizado</th>
                </tr>
              </thead>
              <tbody>
                {state.positions.map((position) => (
                  <tr key={position.symbol}>
                    <td>{position.symbol}</td>
                    <td>{position.quantity.toLocaleString()}</td>
                    <td>{fmtPrice(position.avg_entry_price)}</td>
                    <td>{position.last_price !== null ? fmtPrice(position.last_price) : "—"}</td>
                    <td className={pnlClass(position.unrealized_pnl)}>
                      {fmtSigned(position.unrealized_pnl)}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td colSpan={4}>Total</td>
                  <td className={pnlClass(totalUnrealized)}>{fmtSigned(totalUnrealized)}</td>
                </tr>
              </tfoot>
            </table>
          )}
        </section>

        <section className="rt-card pp-panel">
          <div className="rt-card-h">
            <span className="rt-card-t">Equity intraday</span>
          </div>
          <EquitySparkline points={state.equitySeries} />
          <div className="pp-stats">
            <div className="pp-stat">
              <span className="rt-k">Equity</span>
              <span className="rt-v pp-stat-v">{fmtMoney(state.pnl?.equity)}</span>
            </div>
            <div className="pp-stat">
              <span className="rt-k">PnL do dia</span>
              <span className={`rt-v pp-stat-v ${pnlClass(state.pnl?.day_pnl)}`}>
                {fmtSigned(state.pnl?.day_pnl)}
              </span>
            </div>
            <div className="pp-stat">
              <span className="rt-k">Realizado hoje</span>
              <span className={`rt-v pp-stat-v ${pnlClass(state.pnl?.realized_pnl_today)}`}>
                {fmtSigned(state.pnl?.realized_pnl_today)}
              </span>
            </div>
            <div className="pp-stat">
              <span className="rt-k">Fees hoje</span>
              <span className="rt-v pp-stat-v">{fmtMoney(state.pnl?.fees_today)}</span>
            </div>
            <div className="pp-stat">
              <span className="rt-k">Trades hoje</span>
              <span className="rt-v pp-stat-v">{state.pnl?.trades_today ?? "—"}</span>
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
