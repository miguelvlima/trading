import type { SeriesMarker, UTCTimestamp } from "lightweight-charts";

import { isoToChartTime } from "./chartBars";

export type SignalForChart = {
  id: number;
  symbol: string;
  strategy: string;
  direction: string;
  strength: number;
  rationale: string;
  timestamp: string;
  source?: string;
};

export const STRATEGY_MARKER_COLORS: Record<string, string> = {
  rsi_mean_reversion: "#a78bfa",
  macd_crossover: "#60a5fa",
  sma_ema_crossover: "#fbbf24",
  bollinger_breakout: "#34d399",
};

const STRATEGY_ABBREV: Record<string, string> = {
  rsi_mean_reversion: "RSI",
  macd_crossover: "MACD",
  sma_ema_crossover: "SMA",
  bollinger_breakout: "BB",
};

function strategyAbbrev(strategy: string): string {
  return STRATEGY_ABBREV[strategy] ?? strategy.slice(0, 4).toUpperCase();
}

function markerPosition(
  isBuy: boolean,
  index: number,
  highlighted: boolean,
): "aboveBar" | "belowBar" | "inBar" {
  if (highlighted) {
    return isBuy ? "aboveBar" : "belowBar";
  }
  if (index === 0) {
    return isBuy ? "aboveBar" : "belowBar";
  }
  if (index === 1) {
    return "inBar";
  }
  return isBuy ? "aboveBar" : "belowBar";
}

export function buildSignalMarkers(
  signals: SignalForChart[],
  highlightedId?: number | null,
): SeriesMarker<UTCTimestamp>[] {
  const grouped = new Map<number, SignalForChart[]>();
  for (const signal of signals) {
    const time = Number(isoToChartTime(signal.timestamp));
    const bucket = grouped.get(time) ?? [];
    bucket.push(signal);
    grouped.set(time, bucket);
  }

  const markers: SeriesMarker<UTCTimestamp>[] = [];
  for (const [time, bucket] of grouped) {
    bucket
      .slice()
      .sort((left, right) => right.strength - left.strength)
      .forEach((signal, index) => {
        const isBuy = signal.direction === "BUY";
        const highlighted = highlightedId != null && signal.id === highlightedId;
        const baseColor =
          STRATEGY_MARKER_COLORS[signal.strategy] ?? (isBuy ? "#22c55e" : "#f87171");
        const color = highlighted ? (isBuy ? "#4ade80" : "#fb7185") : baseColor;
        const abbrev = strategyAbbrev(signal.strategy);
        markers.push({
          time: time as UTCTimestamp,
          position: markerPosition(isBuy, index, highlighted),
          color,
          shape: isBuy ? "arrowUp" : "arrowDown",
          text: highlighted
            ? isBuy
              ? `▲ BUY ${abbrev}`
              : `▼ SELL ${abbrev}`
            : `${abbrev} ${isBuy ? "B" : "S"}`,
        });
      });
  }

  return markers.sort((left, right) => Number(left.time) - Number(right.time));
}

export function findSignalsAtChartTime(
  signals: SignalForChart[],
  timeSec: number,
): SignalForChart[] {
  return signals.filter((signal) => Number(isoToChartTime(signal.timestamp)) === timeSec);
}
