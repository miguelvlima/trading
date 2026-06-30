import { useEffect, useState } from "react";

import { type FeedHealth, ApiError, fetchHealth } from "./api";

type UseFeedHealthResult = {
  health: FeedHealth | null;
  loading: boolean;
  error: string | null;
};

// Polls /realtime/health on a slow interval (default 15s) so the status badge
// reflects feed staleness without adding meaningful load.
export function useFeedHealth(
  baseUrl: string,
  token: string,
  symbol: string,
  timeframe: string,
  intervalMs = 15000,
): UseFeedHealthResult {
  const [health, setHealth] = useState<FeedHealth | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      setHealth(null);
      return;
    }

    let cancelled = false;
    setLoading(true);

    const poll = async () => {
      if (typeof document !== "undefined" && document.hidden) {
        return;
      }
      try {
        const next = await fetchHealth(baseUrl, token, symbol, timeframe);
        if (!cancelled) {
          setHealth(next);
          setError(null);
        }
      } catch (err: unknown) {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Erro ao obter estado do feed.");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    void poll();
    const timer = window.setInterval(() => void poll(), intervalMs);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [baseUrl, token, symbol, timeframe, intervalMs]);

  return { health, loading, error };
}
