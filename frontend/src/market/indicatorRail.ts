import { fmtPrice } from "../realtime/format";
import {
  type IndicatorRender,
  INDICATOR_BY_ID,
  indicatorLabel,
  type IndicatorId,
} from "../realtime/indicators";

export type IndicatorRailRow = {
  id: IndicatorId;
  label: string;
  value: string;
};

function lastFinitePoint(render: IndicatorRender): number | null {
  for (const line of render.lines) {
    for (let index = line.points.length - 1; index >= 0; index -= 1) {
      const value = line.points[index]?.value;
      if (value !== undefined && Number.isFinite(value)) {
        return value;
      }
    }
  }
  return null;
}

export function indicatorRailRows(
  active: ReadonlySet<IndicatorId>,
  renders: IndicatorRender[],
  barCount: number,
): IndicatorRailRow[] {
  const byId = new Map(renders.map((render) => [render.id, render]));
  const rows: IndicatorRailRow[] = [];

  for (const id of active) {
    const descriptor = INDICATOR_BY_ID[id];
    const render = byId.get(id);
    if (!descriptor || !render) {
      continue;
    }
    const value = lastFinitePoint(render);
    const minBars = minBarsForIndicator(id);
    let display: string;
    if (value !== null) {
      display = fmtPrice(value);
    } else if (barCount < minBars) {
      display = "Poucos dados";
    } else {
      display = "-";
    }
    rows.push({ id, label: indicatorLabel(descriptor), value: display });
  }

  return rows;
}

function minBarsForIndicator(id: IndicatorId): number {
  switch (id) {
    case "RSI":
    case "ATR":
    case "STOCH":
    case "ADX":
      return 14;
    case "MACD":
      return 34;
    case "SMA":
    case "EMA":
    case "WMA":
    case "BB":
      return 20;
    default:
      return 2;
  }
}
