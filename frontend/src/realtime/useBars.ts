import { useEffect, useState } from "react";

import { type Bar, type Quote, ApiError, fetchBars, fetchHistory } from "./api";

// Treat a persisted (DB) bar as a closed quote for the chart.
function asQuotes(symbol: string, bars: Bar[]): Quote[] {
  return bars.map((b) => ({ ...b, symbol, is_final: true }));
}

type UseBarsResult = {
  bars: Quote[];
  loading: boolean;
  error: string | null;
};

// Loads chart history for a symbol/candle/window from /market-data/bars (DB).
// When the DB has no rows (e.g. a just-picked symbol), falls back to
// /realtime/history (provider-backed). Live forming bars come from the WS tick
// layer when snapshots are final-only.
export function useBars(
  baseUrl: string,
  token: string,
  symbol: string,
  timeframe: string,
  window: string,
  limit: number,
  refreshMs = 20000,
): UseBarsResult {
  const [bars, setBars] = useState<Quote[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token || !symbol) {
      setBars([]);
      return;
    }

    let cancelled = false;

    const load = async (initial: boolean) => {
      if (!initial && typeof document !== "undefined" && document.hidden) {
        return;
      }
      if (initial) {
        setLoading(true);
        setError(null);
      }
      try {
        const persisted = await fetchBars(baseUrl, token, symbol, timeframe, limit);
        let data = asQuotes(symbol, persisted);
        if (data.length === 0) {
          try {
            data = await fetchHistory(baseUrl, token, symbol, timeframe, window, limit);
          } catch {
            // Provider unavailable — keep empty; chart shows the hint.
          }
        }
        if (!cancelled) {
          setBars(data);
          setError(null);
        }
      } catch (err: unknown) {
        if (!cancelled && initial) {
          setBars([]);
          setError(err instanceof ApiError ? err.message : "Erro ao carregar velas.");
        }
      } finally {
        if (!cancelled && initial) {
          setLoading(false);
        }
      }
    };

    void load(true);
    const timer = globalThis.setInterval(() => void load(false), refreshMs);

    return () => {
      cancelled = true;
      globalThis.clearInterval(timer);
    };
  }, [baseUrl, token, symbol, timeframe, window, limit, refreshMs]);

  return { bars, loading, error };
}
