// Shared window <-> candle model for Mercado, Sinais, Simulação and Realtime.
//
// *window* = visible time span on the chart; *candle* = bar resolution.
// Bar fetch limit is derived — never exposed as a primary user control.

export type WindowCode = "1h" | "4h" | "1d" | "1w" | "1mo" | "1y" | "all";
export type CandleCode = "1m" | "5m" | "15m" | "30m" | "1h" | "4h" | "1d" | "1w";
export type PeriodMode = "window" | "date";

export type WindowOption = { code: WindowCode; label: string };

export const WINDOWS: readonly WindowOption[] = [
  { code: "1h", label: "1H" },
  { code: "4h", label: "4H" },
  { code: "1d", label: "1D" },
  { code: "1w", label: "1S" },
  { code: "1mo", label: "1M" },
  { code: "1y", label: "1A" },
  { code: "all", label: "All" },
];

export const CANDLES: readonly CandleCode[] = [
  "1m",
  "5m",
  "15m",
  "30m",
  "1h",
  "4h",
  "1d",
  "1w",
];

export const SUGGESTED_CANDLE: Record<WindowCode, CandleCode> = {
  "1h": "1m",
  "4h": "5m",
  "1d": "5m",
  "1w": "1h",
  "1mo": "1d",
  "1y": "1d",
  all: "1w",
};

export const IBKR_DURATION: Record<WindowCode, string> = {
  "1h": "3600 S",
  "4h": "14400 S",
  "1d": "1 D",
  "1w": "1 W",
  "1mo": "1 M",
  "1y": "1 Y",
  all: "30 Y",
};

export const WINDOW_SECONDS: Record<WindowCode, number | null> = {
  "1h": 3600,
  "4h": 14400,
  "1d": 86400,
  "1w": 604800,
  "1mo": 2592000,
  "1y": 31536000,
  all: null,
};

export const CANDLE_SECONDS: Record<CandleCode, number> = {
  "1m": 60,
  "5m": 300,
  "15m": 900,
  "30m": 1800,
  "1h": 3600,
  "4h": 14400,
  "1d": 86400,
  "1w": 604800,
};

export function fetchLimitFor(window: WindowCode, candle: CandleCode): number {
  const span = WINDOW_SECONDS[window];
  if (span === null) {
    return 5000;
  }
  const bars = Math.ceil((span / CANDLE_SECONDS[candle]) * 1.1) + 5;
  return Math.min(5000, Math.max(40, bars));
}

export function suggestedCandle(window: WindowCode): CandleCode {
  return SUGGESTED_CANDLE[window];
}

export function isSuggestedCandle(window: WindowCode, candle: CandleCode): boolean {
  return SUGGESTED_CANDLE[window] === candle;
}
