import { useEffect, useState } from "react";

import { type Quote, ApiError, fetchQuote } from "./api";

type UseLiveQuoteResult = {
  quote: Quote | null;
  error: string | null;
};

// Polls /realtime/quote on an interval. It is "polite": a single interval is
// ever active (cleaned up on unmount / dependency change) and polling pauses
// while the browser tab is hidden, so we never hammer the rate-limited backend.
export function useLiveQuote(
  baseUrl: string,
  token: string,
  symbol: string,
  intervalMs = 5000,
): UseLiveQuoteResult {
  const [quote, setQuote] = useState<Quote | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token || !symbol) {
      setQuote(null);
      return;
    }

    let cancelled = false;
    setQuote(null);
    setError(null);

    const poll = async () => {
      if (typeof document !== "undefined" && document.hidden) {
        return; // tab not visible — skip this tick
      }
      try {
        const next = await fetchQuote(baseUrl, token, symbol);
        if (!cancelled) {
          setQuote(next);
          setError(null);
        }
      } catch (err: unknown) {
        if (!cancelled) {
          setError(err instanceof ApiError ? err.message : "Erro ao obter cotação.");
        }
      }
    };

    void poll();
    const timer = window.setInterval(() => void poll(), intervalMs);

    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [baseUrl, token, symbol, intervalMs]);

  return { quote, error };
}
