import { useEffect, useState } from "react";

import { type Bar, ApiError, fetchBars } from "./api";

type UseBarsResult = {
  bars: Bar[];
  loading: boolean;
  error: string | null;
};

// Loads the historical candles for a symbol/timeframe from /market-data/bars.
// Re-fetches on selection change AND on an interval (default 20s) so newly
// closed bars the worker persists show up without a manual reload. The periodic
// refresh is silent (no loading flicker) and pauses while the tab is hidden.
export function useBars(
  baseUrl: string,
  token: string,
  symbol: string,
  timeframe: string,
  limit: number,
  refreshMs = 20000,
): UseBarsResult {
  const [bars, setBars] = useState<Bar[]>([]);
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
        const data = await fetchBars(baseUrl, token, symbol, timeframe, limit);
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
    const timer = window.setInterval(() => void load(false), refreshMs);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [baseUrl, token, symbol, timeframe, limit, refreshMs]);

  return { bars, loading, error };
}
