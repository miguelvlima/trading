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

// Loads the chart history for a symbol/candle/window from /realtime/history
// (provider-backed, window-aware, paginated + throttled on the server).
// Re-fetches on selection change AND on an interval (default 20s) so newly
// closed bars show up without a manual reload. The periodic refresh is silent
// (no loading flicker) and pauses while the tab is hidden.
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
        // Chart history comes from the DB first (the worker persists closed
        // bars): reliable, no live-Gateway dependency, no client-id contention.
        // Live updates arrive separately over the WebSocket (forming bar).
        const persisted = await fetchBars(baseUrl, token, symbol, timeframe, limit);
        let data = asQuotes(symbol, persisted);
        // Fallback for symbols the worker is not persisting (e.g. a just-picked
        // instrument like GOOGL): pull history straight from the provider so the
        // chart is never blank. /realtime/history is provider-backed + throttled.
        if (data.length === 0) {
          data = await fetchHistory(baseUrl, token, symbol, timeframe, window, limit);
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
