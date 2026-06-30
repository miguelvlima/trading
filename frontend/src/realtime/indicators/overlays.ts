// Price overlays: drawn on the main price scale (same pane as the candles).

import type { BandResult, IndicatorBar, LinePoint } from "./types";

export function sma(bars: IndicatorBar[], period: number): LinePoint[] {
  if (period <= 0) return [];
  const out: LinePoint[] = [];
  let sum = 0;
  for (let i = 0; i < bars.length; i++) {
    sum += bars[i].close;
    if (i >= period) sum -= bars[i - period].close;
    if (i >= period - 1) out.push({ time: bars[i].time, value: sum / period });
  }
  return out;
}

export function ema(bars: IndicatorBar[], period: number): LinePoint[] {
  if (period <= 0 || bars.length < period) return [];
  const out: LinePoint[] = [];
  const k = 2 / (period + 1);
  // Seed with the SMA of the first `period` closes, then roll forward.
  let prev = 0;
  for (let i = 0; i < period; i++) prev += bars[i].close;
  prev /= period;
  out.push({ time: bars[period - 1].time, value: prev });
  for (let i = period; i < bars.length; i++) {
    prev = bars[i].close * k + prev * (1 - k);
    out.push({ time: bars[i].time, value: prev });
  }
  return out;
}

export function wma(bars: IndicatorBar[], period: number): LinePoint[] {
  if (period <= 0) return [];
  const denom = (period * (period + 1)) / 2;
  const out: LinePoint[] = [];
  for (let i = period - 1; i < bars.length; i++) {
    let weighted = 0;
    for (let j = 0; j < period; j++) {
      weighted += bars[i - period + 1 + j].close * (j + 1);
    }
    out.push({ time: bars[i].time, value: weighted / denom });
  }
  return out;
}

// Cumulative VWAP over the loaded series (no intraday session reset — matches
// the prototype, which accumulates across the visible window).
export function vwap(bars: IndicatorBar[]): LinePoint[] {
  const out: LinePoint[] = [];
  let cumPv = 0;
  let cumVol = 0;
  for (const bar of bars) {
    const typical = (bar.high + bar.low + bar.close) / 3;
    cumPv += typical * bar.volume;
    cumVol += bar.volume;
    if (cumVol > 0) out.push({ time: bar.time, value: cumPv / cumVol });
  }
  return out;
}

export function bollinger(
  bars: IndicatorBar[],
  period = 20,
  mult = 2,
): BandResult {
  const upper: LinePoint[] = [];
  const middle: LinePoint[] = [];
  const lower: LinePoint[] = [];
  for (let i = period - 1; i < bars.length; i++) {
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += bars[j].close;
    const mean = sum / period;
    let variance = 0;
    for (let j = i - period + 1; j <= i; j++) {
      variance += (bars[j].close - mean) ** 2;
    }
    const sd = Math.sqrt(variance / period);
    const time = bars[i].time;
    middle.push({ time, value: mean });
    upper.push({ time, value: mean + mult * sd });
    lower.push({ time, value: mean - mult * sd });
  }
  return { upper, middle, lower };
}
