import type { FormingBar } from "../realtime/CandleChart";
import type { Quote } from "../realtime/api";

export type LiveBarInput = {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type LiveEvaluatePayload = {
  symbol: string;
  timeframe: string;
  strategies: string[];
  min_strength: number;
  persist: boolean;
  limit: number;
  start?: string;
  end?: string;
  context_bars?: LiveBarInput[];
  forming_bar?: LiveBarInput & { is_forming: boolean };
};

export function quoteToLiveBarInput(quote: Quote): LiveBarInput {
  return {
    timestamp: quote.timestamp,
    open: Number(quote.open),
    high: Number(quote.high),
    low: Number(quote.low),
    close: Number(quote.close),
    volume: Number(quote.volume),
  };
}

export function formingBarToLiveInput(forming: FormingBar): LiveBarInput & { is_forming: boolean } {
  return {
    timestamp: new Date(forming.time * 1000).toISOString(),
    open: forming.open,
    high: forming.high,
    low: forming.low,
    close: forming.close,
    volume: forming.volume,
    is_forming: true,
  };
}

export function filterQuotesByDateRange(
  quotes: Quote[],
  startDate: string,
  endDate: string,
): Quote[] {
  const startMs = Date.parse(`${startDate}T00:00:00Z`);
  const endMs = Date.parse(`${endDate}T23:59:59Z`);
  return quotes.filter((quote) => {
    const ts = Date.parse(/[zZ]$|[+-]\d\d:?\d\d$/.test(quote.timestamp) ? quote.timestamp : `${quote.timestamp}Z`);
    return ts >= startMs && ts <= endMs;
  });
}

export function buildLiveEvaluatePayload(args: {
  symbol: string;
  timeframe: string;
  strategies: string[];
  minStrength: number;
  periodMode: "window" | "date";
  barLimit: number;
  startDate: string;
  endDate: string;
  contextQuotes: Quote[];
  formingBar: FormingBar | null;
}): LiveEvaluatePayload {
  const scopedQuotes =
    args.periodMode === "date"
      ? filterQuotesByDateRange(args.contextQuotes, args.startDate, args.endDate)
      : args.contextQuotes;

  const payload: LiveEvaluatePayload = {
    symbol: args.symbol,
    timeframe: args.timeframe,
    strategies: args.strategies,
    min_strength: args.minStrength,
    persist: true,
    limit: args.periodMode === "window" ? args.barLimit : 5000,
  };

  if (args.periodMode === "date") {
    payload.start = `${args.startDate}T00:00:00Z`;
    payload.end = `${args.endDate}T23:59:59Z`;
  }

  if (scopedQuotes.length > 0) {
    payload.context_bars = scopedQuotes.map(quoteToLiveBarInput);
  }

  if (args.formingBar) {
    payload.forming_bar = formingBarToLiveInput(args.formingBar);
  }

  return payload;
}
