import { useEffect, useRef, useState } from "react";

import { type StreamMessage, realtimeWsUrl } from "./api";

const toNum = (value: string | null): number | null =>
  value === null ? null : Number(value);

export type LiveTick = {
  symbol: string;
  timestamp: string;
  last: number | null;
  bid: number | null;
  ask: number | null;
  bidSize: number | null;
  askSize: number | null;
  lastSize: number | null;
  volume: number | null;
  dayHigh: number | null;
  dayLow: number | null;
};

export type LiveIndex = {
  symbol: string;
  name: string;
  last: number | null;
  changePct: number | null;
};

export type StreamStatus = "connecting" | "open" | "closed";

export type UseTickStreamResult = {
  tick: LiveTick | null;
  indices: Record<string, LiveIndex>;
  status: StreamStatus;
  lastMessageMs: number | null;
  activeLines: number | null;
  error: string | null;
};

// Single WebSocket to /realtime/ws: streams the active symbol's ticks plus all
// index quotes. Switching symbol sends a "subscribe" over the open socket (no
// reconnect); the connection auto-reconnects with a small delay if it drops.
export function useTickStream(
  baseUrl: string,
  token: string,
  symbol: string,
  enabled = true,
): UseTickStreamResult {
  const [tick, setTick] = useState<LiveTick | null>(null);
  const [indices, setIndices] = useState<Record<string, LiveIndex>>({});
  const [status, setStatus] = useState<StreamStatus>("connecting");
  const [lastMessageMs, setLastMessageMs] = useState<number | null>(null);
  const [activeLines, setActiveLines] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const symbolRef = useRef<string>(symbol);
  const closedRef = useRef<boolean>(false);
  const reconnectRef = useRef<number | undefined>(undefined);

  // Re-subscribe over the existing socket when the symbol changes.
  useEffect(() => {
    symbolRef.current = symbol;
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN && symbol) {
      setTick(null); // drop the previous symbol's snapshot immediately
      ws.send(JSON.stringify({ action: "subscribe", symbol }));
    }
  }, [symbol]);

  useEffect(() => {
    if (!enabled) {
      closedRef.current = true;
      if (reconnectRef.current) {
        globalThis.clearTimeout(reconnectRef.current);
      }
      wsRef.current?.close();
      wsRef.current = null;
      setTick(null);
      setStatus("closed");
      setError(null);
      return;
    }
    if (!token || !baseUrl) {
      return;
    }
    closedRef.current = false;

    const handle = (msg: StreamMessage) => {
      switch (msg.type) {
        case "tick":
          if (msg.symbol === symbolRef.current) {
            setTick({
              symbol: msg.symbol,
              timestamp: msg.timestamp,
              last: toNum(msg.last),
              bid: toNum(msg.bid),
              ask: toNum(msg.ask),
              bidSize: toNum(msg.bid_size),
              askSize: toNum(msg.ask_size),
              lastSize: toNum(msg.last_size),
              volume: toNum(msg.volume),
              dayHigh: toNum(msg.day_high),
              dayLow: toNum(msg.day_low),
            });
          }
          break;
        case "index":
          setIndices((prev) => ({
            ...prev,
            [msg.symbol]: {
              symbol: msg.symbol,
              name: msg.name,
              last: toNum(msg.last),
              changePct: toNum(msg.change_pct),
            },
          }));
          break;
        case "subscribed":
          setActiveLines(msg.active_lines);
          break;
        case "error":
          setError(msg.message);
          break;
        default:
          break;
      }
    };

    const connect = () => {
      setStatus("connecting");
      const ws = new WebSocket(realtimeWsUrl(baseUrl, token));
      wsRef.current = ws;

      ws.onopen = () => {
        setStatus("open");
        setError(null);
        if (symbolRef.current) {
          ws.send(JSON.stringify({ action: "subscribe", symbol: symbolRef.current }));
        }
      };
      ws.onmessage = (event) => {
        setLastMessageMs(Date.now());
        let msg: StreamMessage;
        try {
          msg = JSON.parse(event.data) as StreamMessage;
        } catch {
          return;
        }
        handle(msg);
      };
      ws.onerror = () => {
        setError("Erro na ligação em tempo real.");
      };
      ws.onclose = () => {
        setStatus("closed");
        if (!closedRef.current) {
          reconnectRef.current = globalThis.setTimeout(connect, 2000);
        }
      };
    };

    connect();

    return () => {
      closedRef.current = true;
      if (reconnectRef.current) {
        globalThis.clearTimeout(reconnectRef.current);
      }
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [baseUrl, token, enabled]);

  return { tick, indices, status, lastMessageMs, activeLines, error };
}
