import type { FormingBar } from "../realtime/CandleChart";
import type { Quote } from "../realtime/api";
import type { LiveTick } from "../realtime/useTickStream";

import { isoSec } from "./chartBars";
import { type CandleCode, CANDLE_SECONDS } from "./windowCandle";

/** True when the bar that opened at `barOpenSec` has fully closed by `nowMs`. */
export function isCandlePeriodClosed(barOpenSec: number, candle: CandleCode, nowMs: number): boolean {
  const periodSec = CANDLE_SECONDS[candle];
  return (barOpenSec + periodSec) * 1000 <= nowMs;
}

function currentCandleOpenSec(candle: CandleCode, nowMs: number): number {
  const nowSec = Math.floor(nowMs / 1000);
  const periodSec = CANDLE_SECONDS[candle];

  if (candle === "1d") {
    const d = new Date(nowMs);
    return Math.floor(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate()) / 1000);
  }
  if (candle === "1w") {
    const d = new Date(nowMs);
    const daysFromMonday = (d.getUTCDay() + 6) % 7;
    return Math.floor(
      Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() - daysFromMonday) / 1000,
    );
  }
  return Math.floor(nowSec / periodSec) * periodSec;
}

/** Build a forming bar from DB/history snapshot + live tick when `is_final` is true. */
export function synthesizeFormingBar(
  lastBar: Quote,
  candle: CandleCode,
  tick: LiveTick,
  nowMs: number,
): FormingBar | null {
  if (tick.last == null || !Number.isFinite(tick.last)) {
    return null;
  }

  const price = tick.last;
  const lastOpenSec = isoSec(lastBar.timestamp);

  if (!isCandlePeriodClosed(lastOpenSec, candle, nowMs)) {
    return {
      time: lastOpenSec,
      open: Number(lastBar.open),
      high: Math.max(Number(lastBar.high), price),
      low: Math.min(Number(lastBar.low), price),
      close: price,
      volume: Number(lastBar.volume),
    };
  }

  const openSec = currentCandleOpenSec(candle, nowMs);
  if (openSec <= lastOpenSec) {
    return {
      time: lastOpenSec,
      open: Number(lastBar.open),
      high: Math.max(Number(lastBar.high), price),
      low: Math.min(Number(lastBar.low), price),
      close: price,
      volume: Number(lastBar.volume),
    };
  }

  const prevClose = Number(lastBar.close);
  return {
    time: openSec,
    open: prevClose,
    high: Math.max(prevClose, price),
    low: Math.min(prevClose, price),
    close: price,
    volume: tick.volume ?? 0,
  };
}

export type ResolvedFormingBar = {
  forming: FormingBar | null;
  isLiveForming: boolean;
};

/** Provider forming bar (is_final=false) or tick-synthesized bar when only DB snapshots exist. */
export function resolveFormingBar(
  lastBar: Quote | null,
  candle: CandleCode,
  tick: LiveTick | null,
  nowMs: number,
): ResolvedFormingBar {
  if (!lastBar || !tick || tick.last == null) {
    return { forming: null, isLiveForming: false };
  }

  if (lastBar.is_final === false) {
    return {
      forming: {
        time: isoSec(lastBar.timestamp),
        open: Number(lastBar.open),
        high: Math.max(Number(lastBar.high), tick.last),
        low: Math.min(Number(lastBar.low), tick.last),
        close: tick.last,
        volume: Number(lastBar.volume),
      },
      isLiveForming: true,
    };
  }

  const forming = synthesizeFormingBar(lastBar, candle, tick, nowMs);
  return { forming, isLiveForming: forming !== null };
}
