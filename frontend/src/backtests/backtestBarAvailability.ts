import type { RecommendationTargets } from "./recommendationApply";

export const BACKTEST_MIN_BARS = 200;

export type RecommendationAvailabilityContext = {
  minBars: number;
  barCountsByTimeframe: Record<string, number>;
};

export async function fetchBarCountsByTimeframe(
  apiBaseUrl: string,
  authToken: string,
  symbol: string,
  timeframes: string[] = ["1d", "1w"],
): Promise<Record<string, number>> {
  const entries = await Promise.all(
    timeframes.map(async (timeframe) => {
      const query = new URLSearchParams({
        symbol,
        timeframe,
        min_bars: String(BACKTEST_MIN_BARS),
      });
      const response = await fetch(`${apiBaseUrl}/market-data/bars/availability?${query.toString()}`, {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      if (!response.ok) {
        return [timeframe, 0] as const;
      }
      const payload = (await response.json()) as { available_bars?: number };
      return [timeframe, payload.available_bars ?? 0] as const;
    }),
  );
  return Object.fromEntries(entries);
}

export function isTimeframeViable(
  timeframe: string,
  context: RecommendationAvailabilityContext,
): boolean {
  return (context.barCountsByTimeframe[timeframe] ?? 0) >= context.minBars;
}

export function validateRecommendationTargets(
  targets: RecommendationTargets,
  context: RecommendationAvailabilityContext,
): string | null {
  if (targets.timeframe && !isTimeframeViable(targets.timeframe, context)) {
    const available = context.barCountsByTimeframe[targets.timeframe] ?? 0;
    return (
      `Só há ${available} velas em ${targets.timeframe}; o backtest precisa de pelo menos ${context.minBars}. ` +
      "Carrega dados demo (com semanal) antes de mudar o timeframe."
    );
  }
  return null;
}
