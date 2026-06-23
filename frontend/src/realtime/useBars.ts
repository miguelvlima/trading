import { useEffect, useState } from "react";

import { type Bar, ApiError, fetchBars } from "./api";

type UseBarsResult = {
  bars: Bar[];
  loading: boolean;
  error: string | null;
};

// Loads the historical candles for a symbol/timeframe from /market-data/bars,
// re-fetching whenever the selection changes.
export function useBars(
  baseUrl: string,
  token: string,
  symbol: string,
  timeframe: string,
  limit: number,
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
    setLoading(true);
    setError(null);

    fetchBars(baseUrl, token, symbol, timeframe, limit)
      .then((data) => {
        if (!cancelled) {
          setBars(data);
        }
      })
      .catch((err: unknown) => {
        if (cancelled) {
          return;
        }
        setBars([]);
        setError(err instanceof ApiError ? err.message : "Erro ao carregar velas.");
      })
      .finally(() => {
        if (!cancelled) {
          setLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [baseUrl, token, symbol, timeframe, limit]);

  return { bars, loading, error };
}
