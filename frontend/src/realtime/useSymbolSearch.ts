import { useEffect, useState } from "react";

import { type SymbolMatch, ApiError, searchSymbols } from "./api";

type UseSymbolSearchResult = {
  results: SymbolMatch[];
  loading: boolean;
  error: string | null;
};

// Debounced IBKR contract search. Only queries once the user pauses typing and
// has entered at least `minChars`, to avoid hammering the rate-limited provider.
export function useSymbolSearch(
  baseUrl: string,
  token: string,
  query: string,
  { minChars = 2, debounceMs = 350 }: { minChars?: number; debounceMs?: number } = {},
): UseSymbolSearchResult {
  const [results, setResults] = useState<SymbolMatch[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const trimmed = query.trim();
    if (!token || trimmed.length < minChars) {
      setResults([]);
      setLoading(false);
      setError(null);
      return;
    }

    let cancelled = false;
    setLoading(true);

    const timer = window.setTimeout(() => {
      searchSymbols(baseUrl, token, trimmed)
        .then((matches) => {
          if (!cancelled) {
            setResults(matches);
            setError(null);
          }
        })
        .catch((err: unknown) => {
          if (!cancelled) {
            setResults([]);
            setError(err instanceof ApiError ? err.message : "Erro na pesquisa de símbolos.");
          }
        })
        .finally(() => {
          if (!cancelled) {
            setLoading(false);
          }
        });
    }, debounceMs);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [baseUrl, token, query, minChars, debounceMs]);

  return { results, loading, error };
}
