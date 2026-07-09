import { useMemo, useRef } from "react";

import type { Quote } from "../realtime/api";
import type { LiveTick } from "../realtime/useTickStream";

import { type ResolvedFormingBar, type TickAccumulator, resolveFormingBar } from "./formingBar";
import type { CandleCode } from "./windowCandle";

/**
 * Vela em formação com estado tick-a-tick: guarda o acumulador entre renders
 * para que high/low/close venham dos ticks e o volume seja o delta do
 * acumulado da sessão (ver `resolveFormingBar`).
 */
export function useFormingBar(
  lastBar: Quote | null,
  candle: CandleCode,
  tick: LiveTick | null,
  nowMs: number,
): ResolvedFormingBar {
  const accRef = useRef<TickAccumulator | null>(null);
  return useMemo(() => {
    // accumulateTick é idempotente para o mesmo tick, por isso a escrita no ref
    // dentro do memo é segura mesmo com double-render em StrictMode.
    const resolved = resolveFormingBar(lastBar, candle, tick, nowMs, accRef.current);
    accRef.current = resolved.acc;
    return resolved;
  }, [lastBar, candle, tick, nowMs]);
}
