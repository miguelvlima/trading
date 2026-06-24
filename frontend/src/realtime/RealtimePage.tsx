import { useEffect, useMemo, useState } from "react";

import { type Instrument, fetchInstruments } from "./api";
import { CandleChart } from "./CandleChart";
import { RealtimeErrorBoundary } from "./ErrorBoundary";
import { FeedStatusBadge } from "./FeedStatusBadge";
import { useBars } from "./useBars";
import { useFeedHealth } from "./useFeedHealth";
import { useLiveQuote } from "./useLiveQuote";
import { useSymbolSearch } from "./useSymbolSearch";
import "./realtime.css";

type RealtimePageProps = {
  apiBaseUrl: string;
  authToken: string;
};

const DEFAULT_SYMBOL = (import.meta.env.VITE_REALTIME_DEFAULT_SYMBOL as string | undefined) ?? "AAPL";
const DEFAULT_TIMEFRAME =
  (import.meta.env.VITE_REALTIME_DEFAULT_TIMEFRAME as string | undefined) ?? "5m";
const BARS_LIMIT = 300;
const TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"] as const;

function formatSecondsAgo(lastUpdatedMs: number | null, nowMs: number): string {
  if (lastUpdatedMs === null) {
    return "—";
  }
  const seconds = Math.max(0, Math.round((nowMs - lastUpdatedMs) / 1000));
  return `há ${seconds}s`;
}

function formatPrice(value: number): string {
  return value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function RealtimePage(props: RealtimePageProps) {
  return (
    <RealtimeErrorBoundary>
      <RealtimePageContent {...props} />
    </RealtimeErrorBoundary>
  );
}

function RealtimePageContent({ apiBaseUrl, authToken }: RealtimePageProps) {
  const [symbolInput, setSymbolInput] = useState<string>(DEFAULT_SYMBOL);
  const [symbol, setSymbol] = useState<string>(DEFAULT_SYMBOL);
  const [timeframe, setTimeframe] = useState<string>(DEFAULT_TIMEFRAME);

  const { bars, loading, error: barsError } = useBars(
    apiBaseUrl,
    authToken,
    symbol,
    timeframe,
    BARS_LIMIT,
  );
  const { quote, error: quoteError, lastUpdatedMs } = useLiveQuote(
    apiBaseUrl,
    authToken,
    symbol,
  );
  const { health, loading: healthLoading, error: healthError } = useFeedHealth(
    apiBaseUrl,
    authToken,
    symbol,
    timeframe,
  );

  // 1s tick so the "atualizado há Xs" label counts up between polls.
  const [nowMs, setNowMs] = useState<number>(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  // Symbols already persisted by the feed (these have candles in the DB).
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  useEffect(() => {
    if (!authToken) {
      return;
    }
    let cancelled = false;
    fetchInstruments(apiBaseUrl, authToken)
      .then((rows) => {
        if (!cancelled) {
          setInstruments(rows);
        }
      })
      .catch(() => {
        /* non-fatal: quick-picks just stay empty */
      });
    return () => {
      cancelled = true;
    };
  }, [apiBaseUrl, authToken, symbol]);

  // Quick-pick chips: union of persisted instruments and the configured feed.
  const quickPicks = useMemo(() => {
    const set = new Set<string>(instruments.map((row) => row.symbol));
    for (const tracked of health?.tracked_symbols ?? []) {
      set.add(tracked);
    }
    return Array.from(set).sort();
  }, [instruments, health]);

  const [showResults, setShowResults] = useState<boolean>(false);
  const { results: searchResults, loading: searchLoading } = useSymbolSearch(
    apiBaseUrl,
    authToken,
    symbolInput,
  );

  const sessionExpired = [barsError, quoteError, healthError].some((message) =>
    message?.toLowerCase().includes("sessão expirada"),
  );

  // Live price + change since the session open (derived from the quote alone).
  const livePrice = quote ? Number(quote.close) : null;
  const dayOpen = quote ? Number(quote.open) : null;
  const change = livePrice !== null && dayOpen !== null ? livePrice - dayOpen : null;
  const changePct = change !== null && dayOpen ? (change / dayOpen) * 100 : null;
  const changeDir = change === null || change === 0 ? "flat" : change > 0 ? "up" : "down";

  const selectSymbol = (next: string) => {
    const cleaned = next.trim().toUpperCase();
    if (!cleaned) {
      return;
    }
    setSymbol(cleaned);
    setSymbolInput(cleaned);
    setShowResults(false);
  };

  if (!authToken) {
    return (
      <div className="realtime-page">
        <p className="hint">Inicie sessão para ver o feed em tempo real.</p>
      </div>
    );
  }

  return (
    <div className="realtime-page">
      <div className="realtime-toolbar">
        <div className="realtime-field">
          <label htmlFor="realtime-symbol">Símbolo (pesquisa IBKR)</label>
          <div className="realtime-symbol-search">
            <div className="realtime-symbol-input">
              <input
                id="realtime-symbol"
                value={symbolInput}
                onChange={(event) => {
                  setSymbolInput(event.target.value);
                  setShowResults(true);
                }}
                onFocus={() => setShowResults(true)}
                onBlur={() => window.setTimeout(() => setShowResults(false), 150)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    selectSymbol(symbolInput);
                  }
                }}
                placeholder="Pesquisar (ex.: AAPL, TSLA, SPY)…"
                autoComplete="off"
              />
              <button type="button" className="tab-button" onClick={() => selectSymbol(symbolInput)}>
                Ver
              </button>
            </div>

            {showResults && (searchLoading || searchResults.length > 0) && (
              <ul className="realtime-search-results">
                {searchLoading && <li className="realtime-search-loading">A pesquisar…</li>}
                {searchResults.map((match, index) => (
                  <li key={`${match.symbol}-${match.exchange}-${index}`}>
                    <button
                      type="button"
                      className="realtime-search-item"
                      onMouseDown={(event) => {
                        // onMouseDown fires before input blur so the click lands.
                        event.preventDefault();
                        selectSymbol(match.symbol);
                      }}
                    >
                      <span className="realtime-search-symbol">{match.symbol}</span>
                      <span className="realtime-search-desc">
                        {[match.sec_type, match.exchange, match.currency]
                          .filter(Boolean)
                          .join(" · ")}
                        {match.name ? ` — ${match.name}` : ""}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {quickPicks.length > 0 && (
            <div className="realtime-quick-picks">
              <span className="realtime-quick-label">Seguidos:</span>
              {quickPicks.map((pick) => (
                <button
                  key={pick}
                  type="button"
                  className={
                    pick === symbol
                      ? "realtime-chip realtime-chip-active"
                      : "realtime-chip"
                  }
                  onClick={() => selectSymbol(pick)}
                >
                  {pick}
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="realtime-field">
          <label htmlFor="realtime-timeframe">Intervalo</label>
          <select
            id="realtime-timeframe"
            value={timeframe}
            onChange={(event) => setTimeframe(event.target.value)}
          >
            {TIMEFRAMES.map((tf) => (
              <option key={tf} value={tf}>
                {tf}
              </option>
            ))}
          </select>
        </div>

        <div className="realtime-live-price">
          <span className="realtime-live-label">Último preço · {symbol}</span>
          <div className="realtime-live-row">
            <span className="realtime-live-value">
              {livePrice !== null ? formatPrice(livePrice) : "—"}
            </span>
            {change !== null && changePct !== null && (
              <span
                className={`realtime-live-change realtime-live-change-${changeDir}`}
                title="Variação desde a abertura da sessão"
              >
                {change >= 0 ? "▲" : "▼"} {change >= 0 ? "+" : ""}
                {formatPrice(change)} ({changePct >= 0 ? "+" : ""}
                {changePct.toFixed(2)}%)
              </span>
            )}
          </div>
          <span className="realtime-live-meta">
            {quote && !quote.is_final && (
              <span className="realtime-live-tag" title="Barra do período ainda em formação">
                em formação
              </span>
            )}
            {quote && (
              <span>
                máx {formatPrice(Number(quote.high))} · mín {formatPrice(Number(quote.low))}
              </span>
            )}
          </span>
          <span className="realtime-live-updated">
            atualizado {formatSecondsAgo(lastUpdatedMs, nowMs)}
          </span>
        </div>
      </div>

      <FeedStatusBadge health={health} loading={healthLoading} />

      {sessionExpired && (
        <p className="error">Sessão expirada. Faça login novamente para continuar.</p>
      )}

      {!sessionExpired && barsError && <p className="error">{barsError}</p>}

      {!barsError && (health?.status === "stale" || health?.status === "error") && (
        <p className="hint">
          O feed está {health.status === "stale" ? "atrasado" : "em erro"} — as velas podem não
          estar atualizadas. Verifique se o worker / IB Gateway está a correr.
        </p>
      )}

      {loading && <p className="hint">A carregar velas…</p>}

      {!loading && !barsError && bars.length === 0 && (
        <p className="hint">
          Sem velas para {symbol} ({timeframe}) ainda. Assim que o feed persistir barras fechadas,
          aparecem aqui.
        </p>
      )}

      {bars.length > 0 && <CandleChart bars={bars} liveQuote={quote} />}
    </div>
  );
}
