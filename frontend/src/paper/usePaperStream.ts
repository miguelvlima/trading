import { useEffect, useReducer, useRef, useState } from "react";

import type { PaperStreamMessage } from "./api";
import { paperWsUrl } from "./api";
import {
  initialStreamState,
  reduceStream,
  type PaperStreamAction,
  type PaperStreamState,
} from "./streamReducer";

export type PaperStreamStatus = "connecting" | "open" | "closed";

export type UsePaperStreamResult = {
  state: PaperStreamState;
  dispatch: (action: PaperStreamAction) => void;
  status: PaperStreamStatus;
  error: string | null;
};

const RECONNECT_DELAY_MS = 2000; // same fixed retry as useTickStream

export function usePaperStream(
  baseUrl: string,
  token: string,
  enabled = true,
): UsePaperStreamResult {
  const [state, dispatch] = useReducer(reduceStream, initialStreamState);
  const [status, setStatus] = useState<PaperStreamStatus>("closed");
  const [error, setError] = useState<string | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<number | null>(null);
  const closedRef = useRef(false);

  useEffect(() => {
    if (!enabled || !token) {
      setStatus("closed");
      return undefined;
    }
    closedRef.current = false;

    const connect = () => {
      if (closedRef.current) return;
      setStatus("connecting");
      const socket = new WebSocket(paperWsUrl(baseUrl, token));
      socketRef.current = socket;

      socket.onopen = () => {
        setStatus("open");
        setError(null);
      };
      socket.onmessage = (raw) => {
        let message: PaperStreamMessage;
        try {
          message = JSON.parse(raw.data as string) as PaperStreamMessage;
        } catch {
          return;
        }
        if (message.type === "error") {
          setError(message.message);
          return;
        }
        dispatch({ kind: "message", message });
      };
      socket.onclose = () => {
        socketRef.current = null;
        setStatus("closed");
        if (!closedRef.current) {
          timerRef.current = window.setTimeout(connect, RECONNECT_DELAY_MS);
        }
      };
      socket.onerror = () => {
        socket.close();
      };
    };

    connect();

    return () => {
      closedRef.current = true;
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, [baseUrl, token, enabled]);

  return { state, dispatch, status, error };
}
