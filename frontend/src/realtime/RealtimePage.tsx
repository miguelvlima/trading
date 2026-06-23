import { useEffect, useState } from "react";

import { CandleChart } from "./CandleChart";
import { FeedStatusBadge } from "./FeedStatusBadge";
import { useBars } from "./useBars";
import { useFeedHealth } from "./useFeedHealth";
import { useLiveQuote } from "./useLiveQuote";
import "./realtime.css";

type RealtimePageProps = {
  apiBaseUrl: string;
  authToken: string;
};

const DEFAULT_SYMBOL = (import.meta.env.VITE_REALTIME_DEFAULT_SYMBOL as string | undefined) ?? "AAPL";
const DEFAULT_TIMEFRAME =
  (import.meta.env.VITE_REALTIME_DEFAULT_TIMEFRAME as string | undefined) ?? "1d";
const BARS_LIMIT = 300;
const TIMEFRAMES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"] as const;

function formatSecondsAgo(lastUpdatedMs: number | null, nowMs: number): string {
  if (lastUpdatedMs === null) {
    return "—";
  }
  const seconds = Math.max(0, Math.round((nowMs - lastUpdatedMs) / 1000));
  return `há ${seconds}s`;
}

export function RealtimePage({ apiBaseUrl, authToken }: RealtimePageProps) {
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

  const sessionExpired = [barsError, quoteError, healthError].some((message) =>
    message?.toLowerCase().includes("sessão expirada"),
  );

  const applySymbol = () => {
    const next = symbolInput.trim().toUpperCase();
    if (next) {
      setSymbol(next);
    }
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
          <label htmlFor="realtime-symbol">Símbolo</label>
          <div className="realtime-symbol-input">
            <input
              id="realtime-symbol"
              value={symbolInput}
              onChange={(event) => setSymbolInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  applySymbol();
                }
              }}
              placeholder="AAPL"
              list="realtime-symbol-options"
            />
            <button type="button" className="tab-button" onClick={applySymbol}>
              Ver
            </button>
          </div>
          {health && health.tracked_symbols.length > 0 && (
            <datalist id="realtime-symbol-options">
              {health.tracked_symbols.map((tracked) => (
                <option key={tracked} value={tracked} />
              ))}
            </datalist>
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
          <span className="realtime-live-label">Último preço</span>
          <span className="realtime-live-value">
            {quote ? Number(quote.close).toLocaleString("en-US", { minimumFractionDigits: 2 }) : "—"}
          </span>
          {quote && !quote.is_final && (
            <span className="realtime-live-tag" title="Barra do período ainda em formação">
              em formação
            </span>
          )}
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
