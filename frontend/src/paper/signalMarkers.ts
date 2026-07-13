// Chart markers for the engine's signal history: every signal the engine saw
// on a symbol — weak/skipped ones included — plotted on the carousel candles.
//
// The engine evaluates on ITS timeframe (e.g. daily closed bars) while the
// carousel may show 5m candles, so each signal is snapped to the nearest
// loaded candle; signals outside the loaded range are dropped instead of
// being pinned misleadingly to the chart's edge.

import type { SeriesMarker, UTCTimestamp } from "lightweight-charts";

import type { PaperSignalWire } from "./api";

export function isoSec(iso: string): number {
  const hasTz = /[zZ]$|[+-]\d\d:?\d\d$/.test(iso);
  return Math.floor(Date.parse(hasTz ? iso : `${iso}Z`) / 1000);
}

const OUTCOME_COLOR: Record<string, { buy: string; sell: string }> = {
  proposed: { buy: "#22c55e", sell: "#ef4444" },
  vetoed: { buy: "#f59e0b", sell: "#f59e0b" },
  // Skipped/weak: dimmed so the chart shows "the engine saw this but stood down".
  skipped: { buy: "#5b708f", sell: "#5b708f" },
};

function markerColor(signal: PaperSignalWire): string {
  const palette = OUTCOME_COLOR[signal.outcome] ?? OUTCOME_COLOR.skipped;
  return signal.direction === "SELL" ? palette.sell : palette.buy;
}

/** Short strategy tag for the marker text ("bollinger_breakout" -> "bollinger"). */
function strategyTag(strategy: string): string {
  return strategy.split("_")[0].slice(0, 10);
}

/**
 * Map the signal history of one symbol onto the loaded candles.
 *
 * `barTimesSec` must be the ascending times (in seconds) of the candles on the
 * chart. Signals snap to the nearest candle at or before their bar time; the
 * result is sorted by time as lightweight-charts requires.
 */
export function signalMarkers(
  signals: PaperSignalWire[],
  symbol: string,
  barTimesSec: number[],
): SeriesMarker<UTCTimestamp>[] {
  if (barTimesSec.length === 0) return [];
  const first = barTimesSec[0];
  const last = barTimesSec[barTimesSec.length - 1];

  const markers: SeriesMarker<UTCTimestamp>[] = [];
  for (const signal of signals) {
    if (signal.symbol !== symbol) continue;
    const anchorIso = signal.bar_time ?? signal.at;
    const sec = isoSec(anchorIso);
    if (!Number.isFinite(sec) || sec < first || sec > last) continue;
    // Nearest candle at or before the signal time (bars are ascending).
    let lo = 0;
    let hi = barTimesSec.length - 1;
    while (lo < hi) {
      const mid = Math.ceil((lo + hi) / 2);
      if (barTimesSec[mid] <= sec) lo = mid;
      else hi = mid - 1;
    }
    const snapped = barTimesSec[lo] as UTCTimestamp;
    const isSell = signal.direction === "SELL";
    const strength = signal.strength !== null ? signal.strength.toFixed(2) : "?";
    markers.push({
      time: snapped,
      position: isSell ? "aboveBar" : "belowBar",
      shape: isSell ? "arrowDown" : "arrowUp",
      color: markerColor(signal),
      text: `${strategyTag(signal.strategy)} ${strength}`,
    });
  }
  return markers.sort((a, b) => Number(a.time) - Number(b.time));
}
