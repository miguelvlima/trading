// Shared types for the technical-indicator modules. All indicators are pure
// functions of an ordered bar series (oldest first) — no React, no charting —
// so they are trivially testable and reusable across overlays and oscillators.

export type IndicatorBar = {
  time: number; // epoch seconds (UTC), strictly ascending
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type LinePoint = {
  time: number;
  value: number;
};

export type BandResult = {
  upper: LinePoint[];
  middle: LinePoint[];
  lower: LinePoint[];
};

export type MacdResult = {
  macd: LinePoint[];
  signal: LinePoint[];
  histogram: LinePoint[];
};

export type StochasticResult = {
  k: LinePoint[];
  d: LinePoint[];
};
