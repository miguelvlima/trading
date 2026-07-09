import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { fetchInstruments } from "../realtime/api";
import { CandleChart } from "../realtime/CandleChart";
import { fmtPrice } from "../realtime/format";
import { useBars } from "../realtime/useBars";
import {
  fetchLimitFor,
  suggestedCandle,
  WINDOW_SECONDS,
  type WindowCode,
} from "../realtime/windowCandle";
import {
  approvePaperOrder,
  cancelPaperOrder,
  closePaperPosition,
  createPaperPortfolio,
  getEngineStatus,
  getPaperEquity,
  getPaperEvents,
  getPaperOrders,
  getPaperPnl,
  getPaperPortfolio,
  getPaperPositions,
  getPaperTrades,
  getStrategies,
  rejectPaperOrder,
  resetKillSwitch,
  resetPaperPortfolio,
  startEngine,
  stopEngine,
  updatePaperRiskSettings,
  PaperApiError,
  type EngineStatusWire,
  type PaperOrder,
  type PaperPortfolio,
  type PaperTradeWire,
  type SymbolSignals,
} from "./api";
import { EquityChart } from "./EquityChart";
import { computeRiskGauges, pnlBars } from "./monitor";
import { affectsPendingOrders, eventTone, type LivePosition } from "./streamReducer";
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

// Local date+time, dropping the date when it is today ("16:57" vs "08/07 16:57").
function fmtWhen(iso: string | null): string {
  if (!iso) return "—";
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return "—";
  const time = parsed.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  const today = new Date();
  if (parsed.toDateString() === today.toDateString()) return time;
  const day = parsed.toLocaleDateString("en-GB", { day: "2-digit", month: "2-digit" });
  return `${day} ${time}`;
}

// Tooltip for the Stop/TP cell: how far each exit sits from the last price.
function exitDistances(position: LivePosition): string | undefined {
  const last = position.last_price;
  if (last === null || last <= 0) return undefined;
  const parts: string[] = [];
  if (position.stop_price !== null) {
    parts.push(`stop a ${(((last - position.stop_price) / last) * 100).toFixed(1)}% abaixo`);
  }
  if (position.take_profit_price !== null) {
    parts.push(
      `TP a ${(((position.take_profit_price - last) / last) * 100).toFixed(1)}% acima`,
    );
  }
  return parts.length > 0 ? parts.join(", ") : undefined;
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

const FEED_REASON_LABEL: Record<string, string> = {
  engine_stopped: "engine parado",
  no_provider: "sem ligação ao IB Gateway",
  market_closed: "mercado fechado — normal a esta hora",
  no_ticks: "sem ticks — verifica o IB Gateway",
};

function FeedDot({ status }: { status: EngineStatusWire | null }) {
  // "market closed" is expected, not a failure — colour it as a warning, not red.
  const expectedOutage = status?.feed_reason === "market_closed";
  const level =
    status === null || (status.feed_status === "unavailable" && !expectedOutage)
      ? "down"
      : status.feed_status !== "fresh"
        ? "warn"
        : "up";
  const reason = status?.feed_reason ? FEED_REASON_LABEL[status.feed_reason] : null;
  const label =
    status === null
      ? "sem estado"
      : status.feed_status === "fresh"
        ? `fresco (${status.feed_age_seconds?.toFixed(0) ?? "?"}s)`
        : status.feed_status === "stale"
          ? `obsoleto (${status.feed_age_seconds?.toFixed(0) ?? "?"}s)${reason ? ` · ${reason}` : ""}`
          : `indisponível${reason ? ` · ${reason}` : ""}`;
  return (
    <span className={`pp-feed pp-feed-${level}`}>
      <i className="rt-dot" /> Feed {label}
    </span>
  );
}

// One line that explains what the last strategy sweep did — the cockpit's
// answer to "why is nothing happening?".
function evaluationText(status: EngineStatusWire | null): string | null {
  const summary = status?.last_evaluation;
  if (!summary) return null;
  const parts: string[] = [
    `${summary.symbols_total} símbolos × ${summary.strategies} estratégias (${summary.timeframe})`,
  ];
  if (summary.proposals > 0) {
    parts.push(`${summary.proposals} proposta${summary.proposals > 1 ? "s" : ""}`);
  } else if (summary.signals > 0) {
    parts.push(`${summary.signals} sinais, nenhum virou proposta (ver atividade)`);
  } else {
    parts.push("sem sinal novo na barra atual");
  }
  if (summary.no_quote > 0) parts.push(`${summary.no_quote} à espera de cotação`);
  if (summary.no_bars > 0) parts.push(`${summary.no_bars} sem histórico de barras`);
  const cadence = status?.poll_seconds
    ? ` Reavalia a cada ${Math.round(status.poll_seconds)}s.`
    : "";
  return `Última avaliação ${fmtTime(summary.at)} — ${parts.join("; ")}.${cadence}`;
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
      {(status?.tracked_symbols?.length ?? 0) > 0 && (
        <span className="pp-symbols" title="Símbolos seguidos pelo engine">
          {status!.tracked_symbols.map((symbol) => (
            <span key={symbol} className="pp-symbol-chip">
              {symbol}
            </span>
          ))}
        </span>
      )}
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

// -- market carousel -------------------------------------------------------------

// Window -> candle pairs: the candle resolution follows the window so the
// chart always shows a comparable number of bars ("velas ajustadas").
const CAROUSEL_WINDOWS: Array<{ code: WindowCode; label: string; trendLabel: string }> = [
  { code: "4h", label: "4H", trendLabel: "últimas 4 horas" },
  { code: "1d", label: "1D", trendLabel: "último dia" },
  { code: "1mo", label: "1M", trendLabel: "último mês" },
  { code: "1y", label: "1A", trendLabel: "último ano" },
];

const SIGNAL_OUTCOME_LABEL: Record<string, { text: string; tone: string }> = {
  proposed: { text: "proposta", tone: "rt-up" },
  vetoed: { text: "veto de risco", tone: "rt-down" },
  skipped: { text: "descartado", tone: "pp-muted" },
  none: { text: "sem sinal", tone: "pp-muted" },
  error: { text: "erro", tone: "rt-down" },
  pending: { text: "por avaliar", tone: "pp-muted" },
};

function MarketCarousel({
  apiBaseUrl,
  authToken,
  symbols,
  positions,
  signals,
}: {
  apiBaseUrl: string;
  authToken: string;
  symbols: string[];
  positions: LivePosition[];
  signals: Record<string, SymbolSignals>;
}) {
  const [index, setIndex] = useState(0);
  const [chartWindow, setChartWindow] = useState<WindowCode>("4h");
  const count = symbols.length;
  const current = count > 0 ? symbols[((index % count) + count) % count] : null;
  const candle = suggestedCandle(chartWindow); // 4h->5m, 1d->5m, 1mo/1y->1d
  const { bars, loading, error } = useBars(
    apiBaseUrl,
    authToken,
    current ?? "",
    candle,
    chartWindow,
    fetchLimitFor(chartWindow, candle),
    20000,
    current !== null,
  );

  const position = positions.find((item) => item.symbol === current) ?? null;
  const lastClose = bars.length > 0 ? Number(bars[bars.length - 1].close) : null;
  const firstOpen = bars.length > 0 ? Number(bars[0].open) : null;
  // Live position price beats the (possibly delayed) last candle close.
  const price = position?.last_price ?? lastClose;
  const trend =
    price !== null && firstOpen !== null && firstOpen > 0
      ? ((price - firstOpen) / firstOpen) * 100
      : null;
  const windowHigh =
    bars.length > 0 ? Math.max(...bars.map((bar) => Number(bar.high))) : null;
  const windowLow =
    bars.length > 0 ? Math.min(...bars.map((bar) => Number(bar.low))) : null;
  const trendLabel =
    CAROUSEL_WINDOWS.find((option) => option.code === chartWindow)?.trendLabel ?? "";

  if (count === 0) return null;
  const step = (delta: number) => setIndex((value) => (value + delta + count) % count);

  return (
    <section className="rt-card pp-panel pp-panel-wide">
      <div className="rt-card-h pp-carousel-head">
        <button
          type="button"
          className="pp-btn pp-btn-sm"
          onClick={() => step(-1)}
          disabled={count < 2}
          aria-label="símbolo anterior"
        >
          ◀
        </button>
        <span className="rt-card-t pp-carousel-title">
          {current} <span className="pp-muted">velas {candle}</span>
        </span>
        <span className="pp-carousel-windows">
          {CAROUSEL_WINDOWS.map((option) => (
            <button
              key={option.code}
              type="button"
              className={`pp-chip ${chartWindow === option.code ? "pp-chip-on" : ""}`}
              onClick={() => setChartWindow(option.code)}
            >
              {option.label}
            </button>
          ))}
        </span>
        <span className="pp-muted">
          {(((index % count) + count) % count) + 1} de {count}
        </span>
        <button
          type="button"
          className="pp-btn pp-btn-sm"
          onClick={() => step(1)}
          disabled={count < 2}
          aria-label="próximo símbolo"
        >
          ▶
        </button>
      </div>
      <div className="pp-carousel-body">
        <div className="pp-carousel-chart">
          {error ? (
            <p className="pp-error">{error}</p>
          ) : loading && bars.length === 0 ? (
            <p className="pp-muted">a carregar velas de {current}…</p>
          ) : bars.length === 0 ? (
            <p className="pp-muted">
              Sem velas {candle} para {current} — o histórico intraday vem do
              Gateway; confirma que está ligado.
            </p>
          ) : (
            <CandleChart
              bars={bars}
              forming={null}
              indicators={[]}
              windowSeconds={WINDOW_SECONDS[chartWindow]}
              height={260}
            />
          )}
        </div>
        <aside className="pp-carousel-side">
          <div className="pp-side-price">
            <span className="rt-k">Preço</span>
            <span className="pp-side-price-v">{price !== null ? fmtPrice(price) : "—"}</span>
            {trend !== null && (
              <span className={trend >= 0 ? "rt-up" : "rt-down"}>
                {trend >= 0 ? "+" : ""}
                {trend.toFixed(2)}% <span className="pp-muted">{trendLabel}</span>
              </span>
            )}
          </div>
          <div className="pp-side-row">
            <span className="rt-k">Máx / mín ({trendLabel})</span>
            <span>
              {windowHigh !== null ? fmtPrice(windowHigh) : "—"}
              {" / "}
              {windowLow !== null ? fmtPrice(windowLow) : "—"}
            </span>
          </div>
          <div className="pp-side-divider" />
          {position ? (
            <>
              <div className="pp-side-row">
                <span className="rt-k">Posição</span>
                <span>
                  <b>{position.quantity.toLocaleString()}</b> @{" "}
                  {fmtPrice(position.avg_entry_price)}
                </span>
              </div>
              <div className="pp-side-row">
                <span className="rt-k">Stop / TP</span>
                <span>
                  {position.stop_price !== null ? fmtPrice(position.stop_price) : "—"}
                  {" / "}
                  {position.take_profit_price !== null
                    ? fmtPrice(position.take_profit_price)
                    : "—"}
                </span>
              </div>
              <div className="pp-side-row">
                <span className="rt-k">PnL n/ realizado</span>
                <PnlCell value={position.unrealized_pnl} />
              </div>
            </>
          ) : (
            <span className="pp-muted">Sem posição aberta neste símbolo.</span>
          )}
          <div className="pp-side-divider" />
          {(() => {
            const monitor = current !== null ? signals[current] : undefined;
            if (!monitor) {
              return (
                <div className="pp-side-row">
                  <span className="rt-k">Sinais</span>
                  <span className="pp-muted">
                    liga o engine para veres a análise ao vivo
                  </span>
                </div>
              );
            }
            return (
              <div className="pp-side-row">
                <span className="rt-k">
                  Sinais · analisado às {fmtTime(monitor.checked_at)}
                </span>
                <ul className="pp-signal-list">
                  {monitor.signals.map((entry) => {
                    const label =
                      SIGNAL_OUTCOME_LABEL[entry.outcome] ??
                      SIGNAL_OUTCOME_LABEL.pending;
                    return (
                      <li key={entry.strategy} className="pp-signal-row">
                        <span className="pp-signal-name">{entry.strategy}</span>
                        <span className={label.tone}>
                          {entry.direction && entry.strength !== undefined
                            ? `${entry.direction} ${entry.strength.toFixed(2)} · ${label.text}`
                            : label.text}
                        </span>
                      </li>
                    );
                  })}
                </ul>
                <span className="pp-field-hint">
                  {monitor.no_quote
                    ? "à espera de cotação (mercado fechado ou feed em baixo) — retenta a cada ciclo"
                    : `barra de ${fmtWhen(monitor.bar_time)} — novo veredicto quando fechar a próxima barra`}
                </span>
              </div>
            );
          })()}
        </aside>
      </div>
    </section>
  );
}

// -- settings ------------------------------------------------------------------

function num(value: unknown, fallback: number): number {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function parseSymbols(text: string): string[] {
  return text
    .split(/[\s,;]+/)
    .map((symbol) => symbol.trim().toUpperCase())
    .filter(Boolean);
}

type SettingsPanelProps = {
  portfolio: PaperPortfolio;
  equity: number | null;
  busy: boolean;
  engineRunning: boolean;
  instruments: string[];
  strategies: string[];
  onSave: (settings: Record<string, unknown>) => void;
  onReset: (initialCash: number) => void;
};

function SettingsPanel({
  portfolio,
  equity,
  busy,
  engineRunning,
  instruments,
  strategies,
  onSave,
  onReset,
}: SettingsPanelProps) {
  const rs = portfolio.risk_settings;
  const [form, setForm] = useState(() => ({
    positionSizePct: String(num(rs.position_size_pct, 10)),
    maxPositionPct: String(num(rs.max_position_pct, 10)),
    maxExposurePct: String(num(rs.max_total_exposure_pct, 50)),
    dailyLossPct: String(num(rs.daily_loss_limit_pct, 3)),
    stopLossPct: String(num(rs.default_stop_loss_pct, 2)),
    takeProfitPct: String(num(rs.default_take_profit_pct, 4)),
    symbols: Array.isArray(rs.symbols) ? (rs.symbols as string[]).join(", ") : "",
    strategies: Array.isArray(rs.strategies) ? (rs.strategies as string[]) : [],
    timeframe: typeof rs.timeframe === "string" ? rs.timeframe : "1d",
    rthOnly: rs.rth_only !== false,
  }));

  const selectedSymbols = parseSymbols(form.symbols);
  const toggleSymbol = (symbol: string) =>
    setForm((current) => {
      const list = parseSymbols(current.symbols);
      const next = list.includes(symbol)
        ? list.filter((item) => item !== symbol)
        : [...list, symbol];
      return { ...current, symbols: next.join(", ") };
    });
  const toggleStrategy = (strategy: string) =>
    setForm((current) => ({
      ...current,
      strategies: current.strategies.includes(strategy)
        ? current.strategies.filter((item) => item !== strategy)
        : [...current.strategies, strategy],
    }));
  const [resetCash, setResetCash] = useState("100000");
  const [confirmReset, setConfirmReset] = useState(false);

  const field = (key: keyof typeof form) => ({
    className: "pp-input pp-input-sm",
    type: "number" as const,
    value: form[key] as string,
    onChange: (event: { target: { value: string } }) =>
      setForm((current) => ({ ...current, [key]: event.target.value })),
  });

  const perTradeAmount =
    equity !== null ? (equity * num(form.positionSizePct, 0)) / 100 : null;

  const save = () =>
    onSave({
      position_size_pct: num(form.positionSizePct, num(rs.position_size_pct, 10)),
      max_position_pct: num(form.maxPositionPct, num(rs.max_position_pct, 10)),
      max_total_exposure_pct: num(form.maxExposurePct, num(rs.max_total_exposure_pct, 50)),
      daily_loss_limit_pct: num(form.dailyLossPct, num(rs.daily_loss_limit_pct, 3)),
      default_stop_loss_pct: num(form.stopLossPct, num(rs.default_stop_loss_pct, 2)),
      default_take_profit_pct: num(form.takeProfitPct, num(rs.default_take_profit_pct, 4)),
      symbols: selectedSymbols,
      strategies: form.strategies,
      timeframe: form.timeframe,
      rth_only: form.rthOnly,
    });

  return (
    <section className="rt-card pp-panel pp-panel-wide">
      <div className="rt-card-h">
        <span className="rt-card-t">Definições de trading</span>
        <span className="pp-muted">as alterações aplicam-se ao próximo ciclo do engine</span>
      </div>
      <div className="pp-settings-grid">
        <label className="pp-field">
          <span className="pp-field-label">Investimento por trade (% do equity)</span>
          <input {...field("positionSizePct")} min={1} max={100} step={1} />
          <span className="pp-field-hint">
            {perTradeAmount !== null ? `≈ ${fmtMoney(perTradeAmount)} por ordem` : "—"}
          </span>
        </label>
        <label className="pp-field">
          <span className="pp-field-label">Máx. por posição (%)</span>
          <input {...field("maxPositionPct")} min={1} max={100} step={1} />
        </label>
        <label className="pp-field">
          <span className="pp-field-label">Exposição total máx. (%)</span>
          <input {...field("maxExposurePct")} min={1} max={100} step={5} />
        </label>
        <label className="pp-field">
          <span className="pp-field-label">Perda diária → kill switch (%)</span>
          <input {...field("dailyLossPct")} min={0.5} max={100} step={0.5} />
        </label>
        <label className="pp-field">
          <span className="pp-field-label">Stop-loss por defeito (%)</span>
          <input {...field("stopLossPct")} min={0.5} max={50} step={0.5} />
        </label>
        <label className="pp-field">
          <span className="pp-field-label">Take-profit por defeito (%)</span>
          <input {...field("takeProfitPct")} min={0.5} max={100} step={0.5} />
        </label>
        <label className="pp-field">
          <span className="pp-field-label">Timeframe das estratégias</span>
          <select
            className="pp-input pp-input-sm"
            value={form.timeframe}
            onChange={(event) =>
              setForm((current) => ({ ...current, timeframe: event.target.value }))
            }
          >
            <option value="1d">Diário (1d)</option>
            <option value="1w">Semanal (1w)</option>
          </select>
        </label>
        <label className="pp-field pp-field-check">
          <input
            type="checkbox"
            checked={form.rthOnly}
            onChange={(event) =>
              setForm((current) => ({ ...current, rthOnly: event.target.checked }))
            }
          />
          <span>Operar apenas com o mercado aberto (RTH)</span>
        </label>
        <div className="pp-field pp-field-wide">
          <span className="pp-field-label">Símbolos a seguir</span>
          {instruments.length > 0 && (
            <div className="pp-chips">
              {instruments.map((symbol) => (
                <button
                  key={symbol}
                  type="button"
                  className={`pp-chip ${selectedSymbols.includes(symbol) ? "pp-chip-on" : ""}`}
                  onClick={() => toggleSymbol(symbol)}
                >
                  {symbol}
                </button>
              ))}
            </div>
          )}
          <input
            className="pp-input"
            type="text"
            placeholder="AAPL, MSFT, NVDA, SPY (vazio = lista por defeito)"
            value={form.symbols}
            onChange={(event) =>
              setForm((current) => ({ ...current, symbols: event.target.value }))
            }
          />
          <span className="pp-field-hint">
            por defeito o engine segue: posições/ordens abertas + símbolos com
            histórico positivo + seguidos na aba Mercado. O que escolheres aqui
            soma-se a esses; as mudanças aplicam-se no ciclo seguinte.
          </span>
        </div>
        <div className="pp-field pp-field-wide">
          <span className="pp-field-label">Estratégias ativas</span>
          {strategies.length > 0 ? (
            <div className="pp-chips">
              {strategies.map((strategy) => (
                <button
                  key={strategy}
                  type="button"
                  className={`pp-chip ${
                    form.strategies.length === 0 || form.strategies.includes(strategy)
                      ? "pp-chip-on"
                      : ""
                  }`}
                  onClick={() => toggleStrategy(strategy)}
                >
                  {strategy}
                </button>
              ))}
            </div>
          ) : (
            <span className="pp-muted">a carregar estratégias…</span>
          )}
          <span className="pp-field-hint">
            {form.strategies.length === 0
              ? "nenhuma selecionada = todas ativas"
              : `${form.strategies.length} selecionada(s)`}
          </span>
        </div>
      </div>
      <div className="pp-settings-actions">
        <button type="button" className="pp-btn pp-btn-approve" disabled={busy} onClick={save}>
          Guardar definições
        </button>
      </div>

      <div className="pp-reset-row">
        <span className="pp-field-label">Recomeçar do zero</span>
        <input
          className="pp-input pp-input-sm"
          type="number"
          min={1000}
          step={1000}
          value={resetCash}
          onChange={(event) => setResetCash(event.target.value)}
        />
        {!confirmReset ? (
          <button
            type="button"
            className="pp-btn"
            disabled={busy}
            onClick={() => setConfirmReset(true)}
          >
            Recomeçar portfolio…
          </button>
        ) : (
          <>
            <button
              type="button"
              className="pp-btn pp-btn-danger"
              disabled={busy}
              onClick={() => {
                setConfirmReset(false);
                onReset(Math.max(1000, Number(resetCash) || 100_000));
              }}
            >
              Confirmar: apagar posições e ordens
            </button>
            <button
              type="button"
              className="pp-btn"
              disabled={busy}
              onClick={() => setConfirmReset(false)}
            >
              Cancelar
            </button>
          </>
        )}
        <span className="pp-field-hint">
          apaga ordens, posições e trades; o histórico de eventos mantém-se (mín. $1.000)
        </span>
      </div>
    </section>
  );
}

// -- live PnL cell with flash on change ---------------------------------------------

function PnlCell({ value }: { value: number | null }) {
  const previousRef = useRef<number | null>(null);
  const flashRef = useRef<{ dir: "up" | "down"; key: number } | null>(null);
  const previous = previousRef.current;
  if (value !== null && previous !== null && value !== previous) {
    flashRef.current = { dir: value > previous ? "up" : "down", key: Date.now() };
  }
  previousRef.current = value;
  const flash = flashRef.current;
  return (
    <span
      key={flash?.key ?? 0}
      className={`${pnlClass(value)} ${flash ? `rt-flash-${flash.dir}` : ""}`.trim()}
    >
      {fmtSigned(value)}
    </span>
  );
}

// -- page ------------------------------------------------------------------------

export function PaperPage({ apiBaseUrl, authToken }: PaperPageProps) {
  const [portfolio, setPortfolio] = useState<PaperPortfolio | null>(null);
  const [portfolioMissing, setPortfolioMissing] = useState(false);
  const [initialCash, setInitialCash] = useState("100000");
  const [pending, setPending] = useState<PaperOrder[]>([]);
  const [waiting, setWaiting] = useState<PaperOrder[]>([]); // approved, fill pendente
  const [trades, setTrades] = useState<PaperTradeWire[]>([]);
  const [instruments, setInstruments] = useState<string[]>([]);
  const [strategies, setStrategies] = useState<string[]>([]);
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
      const [proposed, approved] = await Promise.all([
        getPaperOrders(apiBaseUrl, authToken, "proposed"),
        getPaperOrders(apiBaseUrl, authToken, "approved"),
      ]);
      setPending(proposed);
      setWaiting(approved);
    } catch (err) {
      fail(err);
    }
  }, [apiBaseUrl, authToken, fail]);

  const refreshTrades = useCallback(async () => {
    try {
      setTrades(await getPaperTrades(apiBaseUrl, authToken, 100));
    } catch (err) {
      fail(err);
    }
  }, [apiBaseUrl, authToken, fail]);

  // Initial load: portfolio, then seed the cockpit from REST.
  useEffect(() => {
    void loadPortfolio();
  }, [loadPortfolio]);

  const seedCockpit = useCallback(async () => {
    const [events, engineStatus, pnl, positions, equity] = await Promise.all([
      getPaperEvents(apiBaseUrl, authToken, 50),
      getEngineStatus(apiBaseUrl, authToken),
      getPaperPnl(apiBaseUrl, authToken),
      getPaperPositions(apiBaseUrl, authToken),
      getPaperEquity(apiBaseUrl, authToken),
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
        opened_at: position.opened_at,
        strategy: position.strategy,
        rationale: position.rationale,
        stop_price: position.stop_price,
        take_profit_price: position.take_profit_price,
      })),
      signals: engineStatus.last_signals ?? undefined,
    });
    dispatch({
      kind: "seed_equity",
      points: equity.map((point) => ({ at: point.at, equity: point.equity })),
    });
    await Promise.all([refreshPending(), refreshTrades()]);
  }, [apiBaseUrl, authToken, dispatch, refreshPending, refreshTrades]);

  useEffect(() => {
    if (!hasPortfolio) return;
    seedCockpit().catch(fail);
  }, [hasPortfolio, seedCockpit, fail]);

  // Catalogs for the settings pickers, fetched once per session.
  useEffect(() => {
    if (!hasPortfolio) return;
    fetchInstruments(apiBaseUrl, authToken)
      .then((items) => setInstruments(items.map((item) => item.symbol)))
      .catch(() => setInstruments([]));
    getStrategies(apiBaseUrl, authToken)
      .then(setStrategies)
      .catch(() => setStrategies([]));
  }, [hasPortfolio, apiBaseUrl, authToken]);

  // Refetch panels when order-lifecycle events stream in.
  const lastHandledEvent = useRef<number | null>(null);
  useEffect(() => {
    const newest = state.events[0];
    if (!newest || newest.id === lastHandledEvent.current) return;
    lastHandledEvent.current = newest.id;
    if (affectsPendingOrders(newest.event_type)) void refreshPending();
    if (newest.event_type === "order_filled") void refreshTrades();
  }, [state.events, refreshPending, refreshTrades]);

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

  const saveSettings = useCallback(
    (settings: Record<string, unknown>) =>
      void act(async () => {
        const updated = await updatePaperRiskSettings(apiBaseUrl, authToken, settings);
        setPortfolio(updated);
      }),
    [act, apiBaseUrl, authToken],
  );

  const resetPortfolio = useCallback(
    (initialCash: number) =>
      void act(async () => {
        const fresh = await resetPaperPortfolio(apiBaseUrl, authToken, initialCash);
        setPortfolio(fresh);
        dispatch({ kind: "reset" });
        await seedCockpit();
      }),
    [act, apiBaseUrl, authToken, dispatch, seedCockpit],
  );

  const totalUnrealized = useMemo(
    () =>
      state.positions.reduce(
        (sum, position) => sum + (position.unrealized_pnl ?? 0),
        0,
      ),
    [state.positions],
  );

  const riskGauges = useMemo(
    () =>
      computeRiskGauges({
        positions: state.positions,
        equity: state.pnl?.equity ?? portfolio?.equity ?? null,
        dayPnl: state.pnl?.day_pnl ?? null,
        riskSettings: portfolio?.risk_settings ?? null,
      }),
    [state.positions, state.pnl, portfolio],
  );

  if (portfolioMissing) {
    return (
      <div className="rt-page pp-page">
        <div className="rt-card pp-setup-card">
          <div className="rt-card-h">
            <span className="rt-card-t">Paper Trading</span>
          </div>
          <p>
            Ainda não tens um portfolio virtual. Define o cash inicial (mínimo $1.000)
            e cria um — nenhuma ordem real é enviada em circunstância alguma.
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
                    Math.max(1000, Number(initialCash) || 100_000),
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

      <MarketCarousel
        apiBaseUrl={apiBaseUrl}
        authToken={authToken}
        symbols={status?.tracked_symbols ?? []}
        positions={state.positions}
        signals={state.signals}
      />

      <section className="rt-card pp-panel pp-panel-wide">
        <div className="rt-card-h">
          <span className="rt-card-t">Equity intraday</span>
          <span className="pp-muted">
            {state.equitySeries.length < 2
              ? "a curva acumula-se com o engine ligado e sobrevive a reloads"
              : `${state.equitySeries.length} amostras`}
          </span>
        </div>
        <div className="pp-equity-row">
          <EquityChart
            points={state.equitySeries}
            baseline={state.pnl ? state.pnl.equity - state.pnl.day_pnl : null}
          />
          <div className="pp-stats pp-stats-column">
            <div className="pp-stat">
              <span className="rt-k">Equity</span>
              <span className="rt-v pp-stat-v">{fmtMoney(state.pnl?.equity)}</span>
            </div>
            <div className="pp-stat">
              <span className="rt-k">PnL do dia</span>
              <span className="rt-v pp-stat-v">
                <PnlCell value={state.pnl?.day_pnl ?? null} />
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
        </div>
      </section>

      <div className="pp-grid">
        <section className="rt-card pp-panel">
          <div className="rt-card-h">
            <span className="rt-card-t">Ordens pendentes</span>
            <span className="rt-badge">{pending.length}</span>
          </div>
          {pending.length === 0 ? (
            <>
              <p className="pp-muted">
                {status?.running
                  ? "Sem propostas por decidir. O engine propõe quando houver sinal."
                  : "Engine parado — liga-o para receber propostas de ordens."}
              </p>
              {status?.running && evaluationText(status) && (
                <p className="pp-eval">{evaluationText(status)}</p>
              )}
            </>
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
          {waiting.length > 0 && (
            <div className="pp-waiting">
              <span className="pp-field-label">Aprovadas, à espera de fill</span>
              {waiting.map((order) => (
                <div key={order.id} className="pp-waiting-row">
                  <span>
                    <b className={order.side === "BUY" ? "rt-up" : "rt-down"}>{order.side}</b>{" "}
                    {order.quantity.toLocaleString()} {order.symbol}
                  </span>
                  <span className="pp-muted">desde {fmtTime(order.decided_at ?? order.proposed_at)}</span>
                  <button
                    type="button"
                    className="pp-btn pp-btn-sm"
                    disabled={busy}
                    onClick={() =>
                      void act(() => cancelPaperOrder(apiBaseUrl, authToken, order.id))
                    }
                  >
                    Cancelar
                  </button>
                </div>
              ))}
            </div>
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
            <>
              <table className="pp-table">
                <thead>
                  <tr>
                    <th>Símbolo</th>
                    <th>Qtd</th>
                    <th>P. médio</th>
                    <th>Último</th>
                    <th>PnL n/ realizado</th>
                    <th>Stop / TP</th>
                    <th>Aberta</th>
                    <th>Origem</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {state.positions.map((position) => (
                    <tr key={position.symbol}>
                      <td>{position.symbol}</td>
                      <td>{position.quantity.toLocaleString()}</td>
                      <td>{fmtPrice(position.avg_entry_price)}</td>
                      <td>
                        {position.last_price !== null ? fmtPrice(position.last_price) : "—"}
                      </td>
                      <td>
                        <PnlCell value={position.unrealized_pnl} />
                      </td>
                      <td className="pp-muted" title={exitDistances(position)}>
                        {position.stop_price !== null ? fmtPrice(position.stop_price) : "—"}
                        {" / "}
                        {position.take_profit_price !== null
                          ? fmtPrice(position.take_profit_price)
                          : "—"}
                      </td>
                      <td className="pp-muted">{fmtWhen(position.opened_at)}</td>
                      <td className="pp-muted" title={position.rationale ?? undefined}>
                        {position.strategy ?? "—"}
                      </td>
                      <td>
                        <button
                          type="button"
                          className="pp-btn pp-btn-reject pp-btn-sm"
                          disabled={busy}
                          onClick={() =>
                            void act(() =>
                              closePaperPosition(apiBaseUrl, authToken, position.symbol),
                            )
                          }
                        >
                          Vender
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <td colSpan={4}>Total</td>
                    <td>
                      <PnlCell value={totalUnrealized} />
                    </td>
                    <td colSpan={4} />
                  </tr>
                </tfoot>
              </table>
              {pnlBars(state.positions).length > 0 && (
                <div className="pp-pnl-bars">
                  {pnlBars(state.positions).map((bar) => (
                    <div key={bar.symbol} className="pp-pnl-bar-row">
                      <span className="pp-pnl-bar-symbol">{bar.symbol}</span>
                      <div className="pp-pnl-bar-track">
                        <div className="pp-pnl-bar-half pp-pnl-bar-neg">
                          {!bar.positive && (
                            <i style={{ width: `${bar.widthPct}%` }} />
                          )}
                        </div>
                        <div className="pp-pnl-bar-half pp-pnl-bar-pos">
                          {bar.positive && <i style={{ width: `${bar.widthPct}%` }} />}
                        </div>
                      </div>
                      <span className={`pp-pnl-bar-value ${pnlClass(bar.value)}`}>
                        {fmtSigned(bar.value)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </section>

        <section className="rt-card pp-panel">
          <div className="rt-card-h">
            <span className="rt-card-t">Utilização de risco</span>
          </div>
          {riskGauges.length === 0 ? (
            <p className="pp-muted">Sem dados de equity ainda.</p>
          ) : (
            <div className="pp-gauges">
              {riskGauges.map((gauge) => (
                <div key={gauge.key} className="pp-gauge">
                  <div className="pp-gauge-head">
                    <span>{gauge.label}</span>
                    <span className="pp-muted">{gauge.detail}</span>
                  </div>
                  <div className="pp-gauge-track">
                    <i
                      className={`pp-gauge-fill pp-gauge-${gauge.tone}`}
                      style={{ width: `${gauge.ratio * 100}%` }}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
          {status && status.max_consecutive_losses > 0 && (
            <p
              className={
                status.consecutive_losses >= status.max_consecutive_losses - 1 &&
                status.consecutive_losses > 0
                  ? "pp-losses pp-losses-warn"
                  : "pp-losses"
              }
            >
              Perdas consecutivas hoje: {status.consecutive_losses} de{" "}
              {status.max_consecutive_losses}
              {status.cooldown_until
                ? ` — em cooldown até ${fmtTime(status.cooldown_until)}`
                : " até entrar em cooldown"}
              .
            </p>
          )}
        </section>
      </div>

      <section className="rt-card pp-panel pp-panel-wide">
        <div className="rt-card-h">
          <span className="rt-card-t">Histórico de trades</span>
          <span className="pp-muted">{trades.length} fills</span>
        </div>
        {trades.length === 0 ? (
          <p className="pp-muted">Sem trades ainda — os fills aparecem aqui.</p>
        ) : (
          <div className="pp-table-scroll">
            <table className="pp-table">
              <thead>
                <tr>
                  <th>Quando</th>
                  <th>Lado</th>
                  <th>Qtd</th>
                  <th>Símbolo</th>
                  <th>Preço</th>
                  <th>Fee</th>
                  <th>PnL realizado</th>
                  <th>Base</th>
                  <th>Idade cotação</th>
                </tr>
              </thead>
              <tbody>
                {trades.map((trade) => (
                  <tr key={trade.id}>
                    <td className="pp-muted">{fmtWhen(trade.executed_at)}</td>
                    <td className={trade.side === "BUY" ? "rt-up" : "rt-down"}>
                      {trade.side}
                    </td>
                    <td>{trade.quantity.toLocaleString()}</td>
                    <td>{trade.symbol}</td>
                    <td>{fmtPrice(trade.price)}</td>
                    <td className="pp-muted">{fmtMoney(trade.fee_paid)}</td>
                    <td className={pnlClass(trade.realized_pnl)}>
                      {trade.realized_pnl !== null ? fmtSigned(trade.realized_pnl) : "—"}
                    </td>
                    <td className="pp-muted">
                      {trade.fill_basis === "bid_ask" ? "bid/ask" : "last+slippage"}
                    </td>
                    <td className="pp-muted">
                      {trade.quote_age_seconds !== null
                        ? `${trade.quote_age_seconds.toFixed(1)}s`
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {portfolio && (
        <SettingsPanel
          key={`${portfolio.id}-${portfolio.initial_cash}`}
          portfolio={portfolio}
          equity={state.pnl?.equity ?? portfolio.equity}
          busy={busy}
          engineRunning={status?.running ?? false}
          instruments={instruments}
          strategies={strategies}
          onSave={saveSettings}
          onReset={resetPortfolio}
        />
      )}
    </div>
  );
}
