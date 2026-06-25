import type { UTCTimestamp } from "lightweight-charts";

import type { Quote } from "../realtime/api";
import type { IndicatorBar } from "../realtime/indicators";

export type ApiBar = {
  timestamp: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
};

export function isoSec(iso: string): number {
  const hasTz = /[zZ]$|[+-]\d\d:?\d\d$/.test(iso);
  return Math.floor(Date.parse(hasTz ? iso : `${iso}Z`) / 1000);
}

export function isoToChartTime(iso: string): UTCTimestamp {
  return isoSec(iso) as UTCTimestamp;
}

export function apiBarsToQuotes(symbol: string, bars: ApiBar[]): Quote[] {
  return bars.map((bar) => ({
    ...bar,
    symbol,
    is_final: true,
  }));
}

export function quotesToIndicatorBars(quotes: Quote[]): IndicatorBar[] {
  const mapped = quotes
    .map((bar) => ({
      time: isoSec(bar.timestamp),
      open: Number(bar.open),
      high: Number(bar.high),
      low: Number(bar.low),
      close: Number(bar.close),
      volume: Number(bar.volume),
    }))
    .filter((bar) => Number.isFinite(bar.close))
    .sort((left, right) => left.time - right.time);

  const out: IndicatorBar[] = [];
  for (const bar of mapped) {
    const last = out[out.length - 1];
    if (last && last.time === bar.time) {
      out[out.length - 1] = bar;
    } else {
      out.push(bar);
    }
  }
  return out;
}
