// Public surface for the indicator layer: a registry that drives the UI toggles
// and a `computeIndicator` dispatcher that turns a bar series into chart-ready
// line series. Overlays render on the price pane; oscillators each get their own.

import { bollinger, ema, sma, vwap, wma } from "./overlays";
import { adx, atr, macd, obv, rsi, stochastic } from "./oscillators";
import type { IndicatorBar, LinePoint } from "./types";

export * from "./types";
export * from "./overlays";
export * from "./oscillators";

export type IndicatorId =
  | "SMA"
  | "EMA"
  | "WMA"
  | "VWAP"
  | "BB"
  | "RSI"
  | "MACD"
  | "ATR"
  | "STOCH"
  | "ADX"
  | "OBV";

export type IndicatorKind = "overlay" | "oscillator";

export type IndicatorParams = {
  period?: number;
  mult?: number;
  fast?: number;
  slow?: number;
  signal?: number;
  kPeriod?: number;
  dPeriod?: number;
};

export type IndicatorDescriptor = {
  id: IndicatorId;
  label: string;
  kind: IndicatorKind;
  color: string;
  defaultParams: IndicatorParams;
  defaultOn: boolean;
};

// Registry — order is the toggle order in the controls.
export const INDICATORS: readonly IndicatorDescriptor[] = [
  { id: "SMA", label: "SMA", kind: "overlay", color: "#f59e0b", defaultParams: { period: 20 }, defaultOn: true },
  { id: "VWAP", label: "VWAP", kind: "overlay", color: "#a855f7", defaultParams: {}, defaultOn: true },
  { id: "EMA", label: "EMA", kind: "overlay", color: "#38bdf8", defaultParams: { period: 50 }, defaultOn: false },
  { id: "WMA", label: "WMA", kind: "overlay", color: "#a3e635", defaultParams: { period: 20 }, defaultOn: false },
  { id: "BB", label: "Bollinger", kind: "overlay", color: "#64748b", defaultParams: { period: 20, mult: 2 }, defaultOn: false },
  { id: "RSI", label: "RSI", kind: "oscillator", color: "#22d3ee", defaultParams: { period: 14 }, defaultOn: true },
  { id: "MACD", label: "MACD", kind: "oscillator", color: "#f472b6", defaultParams: { fast: 12, slow: 26, signal: 9 }, defaultOn: false },
  { id: "ATR", label: "ATR", kind: "oscillator", color: "#fb923c", defaultParams: { period: 14 }, defaultOn: false },
  { id: "STOCH", label: "Stochastic", kind: "oscillator", color: "#34d399", defaultParams: { kPeriod: 14, dPeriod: 3 }, defaultOn: false },
  { id: "ADX", label: "ADX", kind: "oscillator", color: "#c084fc", defaultParams: { period: 14 }, defaultOn: false },
  { id: "OBV", label: "OBV", kind: "oscillator", color: "#94a3b8", defaultParams: {}, defaultOn: false },
];

export const INDICATOR_BY_ID: Record<IndicatorId, IndicatorDescriptor> = Object.fromEntries(
  INDICATORS.map((d) => [d.id, d]),
) as Record<IndicatorId, IndicatorDescriptor>;

export function indicatorLabel(descriptor: IndicatorDescriptor): string {
  const p = descriptor.defaultParams.period;
  return p ? `${descriptor.label} ${p}` : descriptor.label;
}

export type IndicatorLine = {
  key: string;
  color: string;
  points: LinePoint[];
  dashed?: boolean;
};

export type IndicatorRender = {
  id: IndicatorId;
  kind: IndicatorKind;
  lines: IndicatorLine[];
  // Fixed value range for bounded oscillators (e.g. RSI/Stochastic 0..100).
  range?: { min: number; max: number };
};

export function computeIndicator(
  descriptor: IndicatorDescriptor,
  bars: IndicatorBar[],
): IndicatorRender {
  const { id, color, defaultParams: p } = descriptor;
  const base = { id, kind: descriptor.kind } as const;

  switch (id) {
    case "SMA":
      return { ...base, lines: [{ key: "SMA", color, points: sma(bars, p.period ?? 20) }] };
    case "EMA":
      return { ...base, lines: [{ key: "EMA", color, points: ema(bars, p.period ?? 50) }] };
    case "WMA":
      return { ...base, lines: [{ key: "WMA", color, points: wma(bars, p.period ?? 20) }] };
    case "VWAP":
      return { ...base, lines: [{ key: "VWAP", color, points: vwap(bars), dashed: true }] };
    case "BB": {
      const band = bollinger(bars, p.period ?? 20, p.mult ?? 2);
      return {
        ...base,
        lines: [
          { key: "BB-upper", color, points: band.upper },
          { key: "BB-mid", color, points: band.middle, dashed: true },
          { key: "BB-lower", color, points: band.lower },
        ],
      };
    }
    case "RSI":
      return {
        ...base,
        lines: [{ key: "RSI", color, points: rsi(bars, p.period ?? 14) }],
        range: { min: 0, max: 100 },
      };
    case "MACD": {
      const m = macd(bars, p.fast ?? 12, p.slow ?? 26, p.signal ?? 9);
      return {
        ...base,
        lines: [
          { key: "MACD", color, points: m.macd },
          { key: "MACD-signal", color: "#fbbf24", points: m.signal, dashed: true },
        ],
      };
    }
    case "ATR":
      return { ...base, lines: [{ key: "ATR", color, points: atr(bars, p.period ?? 14) }] };
    case "STOCH": {
      const s = stochastic(bars, p.kPeriod ?? 14, p.dPeriod ?? 3);
      return {
        ...base,
        lines: [
          { key: "STOCH-k", color, points: s.k },
          { key: "STOCH-d", color: "#fbbf24", points: s.d, dashed: true },
        ],
        range: { min: 0, max: 100 },
      };
    }
    case "ADX":
      return { ...base, lines: [{ key: "ADX", color, points: adx(bars, p.period ?? 14) }] };
    case "OBV":
      return { ...base, lines: [{ key: "OBV", color, points: obv(bars) }] };
    default:
      return { ...base, lines: [] };
  }
}
