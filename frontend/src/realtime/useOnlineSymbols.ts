import { useCallback, useEffect, useState } from "react";

import { type OnlineSymbol, fetchAvailable } from "./api";

export type UseOnlineSymbolsResult = {
  online: OnlineSymbol[];
  loading: boolean;
  /** Re-fetch the available list (curated majors + live IBKR scanner + indices). */
  refresh: () => void;
};

// The "available now" universe shown in the symbol search on focus: curated
// majors, the live IBKR market scanner (most active), and the index strip,
// served by GET /realtime/available. Fetched on mount and on demand via
// `refresh` — the scanner can be empty on the first try if the Gateway is still
// connecting, so the picker exposes a manual retry.
export function useOnlineSymbols(baseUrl: string, token: string): UseOnlineSymbolsResult {
  const [online, setOnline] = useState<OnlineSymbol[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [nonce, setNonce] = useState<number>(0);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (!token) {
      setOnline([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    fetchAvailable(baseUrl, token)
      .then((rows) => {
        if (!cancelled) setOnline(rows);
      })
      .catch(() => {
        // Best-effort: keep whatever we had so a failed refresh never blanks the
        // list. The user can retry; the empty-state hint covers the cold start.
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [baseUrl, token, nonce]);

  return { online, loading, refresh };
}
