import type { FormingBar } from "../realtime/CandleChart";
import type { Quote } from "../realtime/api";
import type { LiveTick } from "../realtime/useTickStream";

import { isoSec } from "./chartBars";
import { isMarketDataStale } from "./dataFreshness";
import { type CandleCode, CANDLE_SECONDS } from "./windowCandle";

/** Máximo desvio tick↔última barra da BD aceite antes de tratar a barra como obsoleta. */
export const MAX_TICK_GAP_PCT = 20;

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

/**
 * Estado tick-a-tick da vela em formação. `LiveTick.volume` é o volume
 * ACUMULADO da sessão (em ações — ver `useTickStream.ts` / `types.py`), por
 * isso o volume da vela é sempre o delta `cumVolume - volumeBase`, nunca o
 * acumulado directamente.
 */
export type TickAccumulator = {
  symbol: string;
  candle: CandleCode;
  openSec: number;
  open: number;
  high: number;
  low: number;
  close: number;
  /** Volume acumulado da sessão no instante em que a vela abriu (null até haver leitura). */
  volumeBase: number | null;
  /** Última leitura do volume acumulado da sessão. */
  cumVolume: number | null;
};

/** Fold one live tick into the per-bar accumulator, rolling over on a new bar. */
export function accumulateTick(
  prev: TickAccumulator | null,
  symbol: string,
  candle: CandleCode,
  openSec: number,
  tick: LiveTick,
): TickAccumulator | null {
  if (tick.last == null || !Number.isFinite(tick.last)) {
    return prev;
  }
  const price = tick.last;
  const cum = tick.volume != null && Number.isFinite(tick.volume) ? tick.volume : null;

  const sameBar =
    prev !== null && prev.symbol === symbol && prev.candle === candle && prev.openSec === openSec;
  if (sameBar) {
    return {
      ...prev,
      high: Math.max(prev.high, price),
      low: Math.min(prev.low, price),
      close: price,
      volumeBase: prev.volumeBase ?? cum,
      cumVolume: cum ?? prev.cumVolume,
    };
  }

  // Rollover: a baseline da nova vela é a última leitura acumulada da vela
  // anterior, para que o delta comece exactamente na fronteira do período.
  const carriedBase = prev !== null && prev.symbol === symbol ? prev.cumVolume : null;
  return {
    symbol,
    candle,
    openSec,
    open: price,
    high: price,
    low: price,
    close: price,
    volumeBase: carriedBase ?? cum,
    cumVolume: cum,
  };
}

/** Per-bar volume derived from the accumulator's cumulative readings. */
export function accumulatedVolume(acc: TickAccumulator | null): number {
  if (!acc || acc.cumVolume === null || acc.volumeBase === null) {
    return 0;
  }
  // Contador acumulado desceu => nova sessão; a baseline antiga já não se aplica.
  if (acc.cumVolume < acc.volumeBase) {
    return acc.cumVolume;
  }
  return acc.cumVolume - acc.volumeBase;
}

/** True when the live price is implausibly far from the DB bar's close (> MAX_TICK_GAP_PCT). */
export function isTickGapSuspicious(lastClose: number, tickLast: number): boolean {
  if (!Number.isFinite(lastClose) || lastClose <= 0 || !Number.isFinite(tickLast)) {
    return false;
  }
  return (Math.abs(tickLast - lastClose) / lastClose) * 100 > MAX_TICK_GAP_PCT;
}

const gapWarned = new Set<string>();

function warnGapOnce(symbol: string, barTimestamp: string, lastClose: number, tickLast: number): void {
  const key = `${symbol}:${barTimestamp}`;
  if (gapWarned.has(key)) {
    return;
  }
  gapWarned.add(key);
  console.warn(
    `[formingBar] gap de preço >${MAX_TICK_GAP_PCT}% entre a última barra da BD e o tick live ` +
      `(${symbol}: close ${lastClose} vs tick ${tickLast}) — a tratar a barra da BD como obsoleta.`,
  );
}

/**
 * Build a forming bar from DB/history snapshot + live tick when `is_final` is true.
 *
 * Se a última barra da BD estiver obsoleta (mais velha do que o limiar de
 * `dataFreshness.ts` para o timeframe) ou o preço live divergir >MAX_TICK_GAP_PCT
 * do close persistido, a vela em formação NUNCA usa valores da BD: abre no
 * primeiro tick recebido e high/low/close/volume vêm só do acumulador de ticks.
 */
export function synthesizeFormingBar(
  lastBar: Quote,
  candle: CandleCode,
  tick: LiveTick,
  nowMs: number,
  acc: TickAccumulator | null = null,
): FormingBar | null {
  if (tick.last == null || !Number.isFinite(tick.last)) {
    return null;
  }

  const price = tick.last;
  const lastOpenSec = isoSec(lastBar.timestamp);
  const lastClose = Number(lastBar.close);

  const gapSuspicious = isTickGapSuspicious(lastClose, price);
  if (gapSuspicious) {
    warnGapOnce(lastBar.symbol, lastBar.timestamp, lastClose, price);
  }

  if (gapSuspicious || isMarketDataStale(lastOpenSec * 1000, candle, nowMs)) {
    const openSec = currentCandleOpenSec(candle, nowMs);
    const barAcc = acc && acc.openSec === openSec ? acc : null;
    return {
      time: openSec,
      open: barAcc ? barAcc.open : price,
      high: barAcc ? barAcc.high : price,
      low: barAcc ? barAcc.low : price,
      close: price,
      volume: accumulatedVolume(barAcc),
    };
  }

  if (!isCandlePeriodClosed(lastOpenSec, candle, nowMs)) {
    const barAcc = acc && acc.openSec === lastOpenSec ? acc : null;
    return {
      time: lastOpenSec,
      open: Number(lastBar.open),
      high: Math.max(Number(lastBar.high), barAcc ? barAcc.high : price),
      low: Math.min(Number(lastBar.low), barAcc ? barAcc.low : price),
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

  const barAcc = acc && acc.openSec === openSec ? acc : null;
  return {
    time: openSec,
    open: lastClose,
    high: Math.max(lastClose, barAcc ? barAcc.high : price),
    low: Math.min(lastClose, barAcc ? barAcc.low : price),
    close: price,
    // Delta do acumulado da sessão — nunca o volume acumulado do dia inteiro.
    volume: accumulatedVolume(barAcc),
  };
}

export type ResolvedFormingBar = {
  forming: FormingBar | null;
  isLiveForming: boolean;
  /** Estado a devolver na próxima chamada (o caller guarda-o num ref). */
  acc: TickAccumulator | null;
};

/** Provider forming bar (is_final=false) or tick-synthesized bar when only DB snapshots exist. */
export function resolveFormingBar(
  lastBar: Quote | null,
  candle: CandleCode,
  tick: LiveTick | null,
  nowMs: number,
  prevAcc: TickAccumulator | null = null,
): ResolvedFormingBar {
  if (!lastBar || !tick || tick.last == null) {
    return { forming: null, isLiveForming: false, acc: prevAcc };
  }
  if (tick.symbol !== lastBar.symbol) {
    // Troca de símbolo a meio: nunca misturar o tick de um símbolo com a barra de outro.
    return { forming: null, isLiveForming: false, acc: prevAcc };
  }

  const acc = accumulateTick(prevAcc, tick.symbol, candle, currentCandleOpenSec(candle, nowMs), tick);

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
      acc,
    };
  }

  const forming = synthesizeFormingBar(lastBar, candle, tick, nowMs, acc);
  return { forming, isLiveForming: forming !== null, acc };
}
