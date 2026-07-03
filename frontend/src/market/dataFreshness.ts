const MS_PER_MINUTE = 60_000;
const MS_PER_HOUR = 60 * MS_PER_MINUTE;
const MS_PER_DAY = 24 * MS_PER_HOUR;

const STALE_THRESHOLD_MS_BY_TIMEFRAME: Record<string, number> = {
  "1m": 2 * MS_PER_HOUR,
  "5m": 6 * MS_PER_HOUR,
  "15m": 12 * MS_PER_HOUR,
  "30m": 24 * MS_PER_HOUR,
  "1h": 2 * MS_PER_DAY,
  "4h": 3 * MS_PER_DAY,
  "1d": 3 * MS_PER_DAY,
  "1w": 14 * MS_PER_DAY,
};

const DEFAULT_STALE_THRESHOLD_MS = 3 * MS_PER_DAY;

export function getStaleBarThresholdMs(timeframe: string): number {
  return STALE_THRESHOLD_MS_BY_TIMEFRAME[timeframe] ?? DEFAULT_STALE_THRESHOLD_MS;
}

export function isMarketDataStale(
  lastBarMs: number | null,
  timeframe: string,
  nowMs: number = Date.now(),
): boolean {
  if (lastBarMs === null) {
    return false;
  }
  return nowMs - lastBarMs > getStaleBarThresholdMs(timeframe);
}

export function formatStaleBarMessage(timeframe: string, lastBarMs: number): string {
  const ageHours = Math.max(1, Math.round((Date.now() - lastBarMs) / MS_PER_HOUR));
  if (ageHours >= 48) {
    const ageDays = Math.max(1, Math.round(ageHours / 24));
    return `Última barra na BD tem ${ageDays} dia(s) — sinais live podem estar desactualizados para ${timeframe}. Actualiza dados demo ou liga o feed IBKR.`;
  }
  return `Última barra na BD tem ${ageHours} h — sinais live podem estar desactualizados para ${timeframe}. Actualiza dados demo ou liga o feed IBKR.`;
}
