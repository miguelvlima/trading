import type { SeriesMarker, UTCTimestamp } from "lightweight-charts";

import { isoToChartTime } from "./chartBars";

export type BacktestTradeForChart = {
  direction: string;
  entry_timestamp: string;
  exit_timestamp: string;
  net_pnl: number;
};

export function buildBacktestTradeMarkers(
  trades: BacktestTradeForChart[],
): SeriesMarker<UTCTimestamp>[] {
  const markers: SeriesMarker<UTCTimestamp>[] = [];
  for (const trade of trades) {
    const isLong = trade.direction === "LONG";
    markers.push({
      time: isoToChartTime(trade.entry_timestamp),
      position: isLong ? "belowBar" : "aboveBar",
      color: isLong ? "#22c55e" : "#f87171",
      shape: isLong ? "arrowUp" : "arrowDown",
      text: isLong ? "Entrada L" : "Entrada S",
    });
    markers.push({
      time: isoToChartTime(trade.exit_timestamp),
      position: isLong ? "aboveBar" : "belowBar",
      color: trade.net_pnl >= 0 ? "#22c55e" : "#ef4444",
      shape: isLong ? "arrowDown" : "arrowUp",
      text: trade.net_pnl >= 0 ? "Saída +" : "Saída −",
    });
  }
  return markers.sort((left, right) => Number(left.time) - Number(right.time));
}
