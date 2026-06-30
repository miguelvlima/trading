import { useCallback, useEffect, useState } from "react";

import { type HotDirection, type HotMover, type HotSort, fetchHotMovers } from "./api";

type UseHotMoversResult = {
  items: HotMover[];
  loading: boolean;
  /** True when the last refresh failed: we keep showing the previous data. */
  stale: boolean;
  asOf: string | null;
  refresh: () => void;
};

// Polls /market-scanner/hot-movers (default 5s). Pauses while the browser tab is
// hidden, aborts in-flight requests on change/unmount, and on error keeps the
// last good data while flagging `stale` (mirrors the FeedStatusBadge approach).
export function useHotMovers(
  baseUrl: string,
  token: string,
  sort: HotSort,
  direction: HotDirection,
  { limit = 10, minPrice = 0.3, intervalMs = 5000 }: { limit?: number; minPrice?: number; intervalMs?: number } = {},
): UseHotMoversResult {
  const [items, setItems] = useState<HotMover[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [stale, setStale] = useState<boolean>(false);
  const [asOf, setAsOf] = useState<string | null>(null);
  const [nonce, setNonce] = useState<number>(0);

  const refresh = useCallback(() => setNonce((n) => n + 1), []);

  useEffect(() => {
    if (!token) {
      setItems([]);
      return;
    }
    let cancelled = false;
    let controller: AbortController | null = null;

    const load = async (initial: boolean) => {
      if (!initial && typeof document !== "undefined" && document.visibilityState === "hidden") {
        return; // polling pauses while the tab is not visible
      }
      controller?.abort();
      controller = new AbortController();
      if (initial) setLoading(true);
      try {
        const data = await fetchHotMovers(baseUrl, token, { limit, sort, direction, minPrice }, controller.signal);
        if (cancelled) return;
        setItems(data.items);
        setAsOf(data.as_of);
        setStale(false);
      } catch (error) {
        if (cancelled || (error as Error).name === "AbortError") return;
        setStale(true); // keep last data, just flag it
      } finally {
        if (!cancelled && initial) setLoading(false);
      }
    };

    void load(true);
    const timer = window.setInterval(() => void load(false), intervalMs);
    const onVisible = () => {
      if (document.visibilityState === "visible") void load(false);
    };
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      cancelled = true;
      controller?.abort();
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [baseUrl, token, sort, direction, limit, minPrice, intervalMs, nonce]);

  return { items, loading, stale, asOf, refresh };
}
