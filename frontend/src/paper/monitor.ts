// Pure data shaping for the cockpit's graphical monitors (unit-tested).

import type { LivePosition } from "./streamReducer";

export type GaugeTone = "ok" | "warn" | "danger";

export type RiskGauge = {
  key: "exposure" | "position" | "daily_loss";
  label: string;
  usedPct: number; // e.g. 34.2 (% of equity)
  capPct: number; // configured limit
  ratio: number; // used/cap clamped to [0, 1] for the bar width
  tone: GaugeTone;
  detail: string;
};

function toneFor(ratio: number): GaugeTone {
  if (ratio >= 1) return "danger";
  if (ratio >= 0.7) return "warn";
  return "ok";
}

function numberSetting(
  settings: Record<string, unknown> | null | undefined,
  key: string,
  fallback: number,
): number {
  const value = settings?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function positionNotional(position: LivePosition): number {
  const price = position.last_price ?? position.avg_entry_price;
  return Math.abs(position.quantity * price);
}

export function computeRiskGauges(args: {
  positions: LivePosition[];
  equity: number | null | undefined;
  dayPnl: number | null | undefined;
  riskSettings: Record<string, unknown> | null | undefined;
}): RiskGauge[] {
  const { positions, riskSettings } = args;
  const equity = args.equity ?? 0;
  const dayPnl = args.dayPnl ?? 0;
  if (equity <= 0) return [];

  const exposureCap = numberSetting(riskSettings, "max_total_exposure_pct", 50);
  const positionCap = numberSetting(riskSettings, "max_position_pct", 10);
  const lossCap = numberSetting(riskSettings, "daily_loss_limit_pct", 3);

  const totalNotional = positions.reduce((sum, p) => sum + positionNotional(p), 0);
  const exposurePct = (totalNotional / equity) * 100;

  const largest = positions.reduce(
    (best, p) => Math.max(best, positionNotional(p)),
    0,
  );
  const largestPct = (largest / equity) * 100;

  // Daily loss gauge fills toward the kill switch; gains leave it at zero.
  const dayStartEquity = equity - dayPnl;
  const lossPct =
    dayPnl < 0 && dayStartEquity > 0 ? (Math.abs(dayPnl) / dayStartEquity) * 100 : 0;

  const make = (
    key: RiskGauge["key"],
    label: string,
    usedPct: number,
    capPct: number,
    detail: string,
  ): RiskGauge => {
    const ratio = capPct > 0 ? Math.min(1, Math.max(0, usedPct / capPct)) : 0;
    return {
      key,
      label,
      usedPct: Math.round(usedPct * 10) / 10,
      capPct,
      ratio,
      tone: toneFor(ratio),
      detail,
    };
  };

  return [
    make(
      "exposure",
      "Exposição total",
      exposurePct,
      exposureCap,
      `${exposurePct.toFixed(1)}% de ${exposureCap.toFixed(0)}%`,
    ),
    make(
      "position",
      "Maior posição",
      largestPct,
      positionCap,
      `${largestPct.toFixed(1)}% de ${positionCap.toFixed(0)}%`,
    ),
    make(
      "daily_loss",
      "Perda diária → kill switch",
      lossPct,
      lossCap,
      `${lossPct.toFixed(2)}% de ${lossCap.toFixed(1)}%`,
    ),
  ];
}

export type PnlBar = {
  symbol: string;
  value: number;
  widthPct: number; // 0..100, share of the largest |value|
  positive: boolean;
};

export function pnlBars(positions: LivePosition[]): PnlBar[] {
  const rows = positions
    .filter((p) => p.unrealized_pnl !== null)
    .map((p) => ({ symbol: p.symbol, value: p.unrealized_pnl as number }));
  const maxAbs = rows.reduce((best, row) => Math.max(best, Math.abs(row.value)), 0);
  return rows
    .sort((a, b) => b.value - a.value)
    .map((row) => ({
      symbol: row.symbol,
      value: row.value,
      widthPct: maxAbs > 0 ? Math.max(4, (Math.abs(row.value) / maxAbs) * 100) : 0,
      positive: row.value >= 0,
    }));
}

export type EquityPoint = { time: number; value: number };

// lightweight-charts requires strictly ascending, unique times (seconds).
export function toEquitySeries(
  points: Array<{ at: string; equity: number }>,
): EquityPoint[] {
  const bySecond = new Map<number, number>();
  for (const point of points) {
    const seconds = Math.floor(Date.parse(point.at) / 1000);
    if (Number.isFinite(seconds)) bySecond.set(seconds, point.equity); // last wins
  }
  return [...bySecond.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([time, value]) => ({ time, value }));
}
