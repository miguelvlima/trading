import { useEffect, useState } from "react";

import { type Quote, ApiError, fetchHistory } from "./api";

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
        const data = await fetchHistory(baseUrl, token, symbol, timeframe, window, limit);
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
