// Typed client for the real-time feed endpoints. Reuses the same auth as the
// rest of the app: the caller passes the JWT it already holds (App.tsx reads it
// from localStorage key "trading_auth_token") and the API base URL.

export type Bar = {
  timestamp: string; // ISO 8601, timezone-aware UTC (e.g. "2026-06-22T04:00:00Z")
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
};

export type Quote = Bar & {
  symbol: string;
  is_final: boolean;
};

export type FeedStatus = "running" | "stale" | "error" | "empty";

export type FeedHealth = {
  provider: string;
  status: FeedStatus;
  last_update: string | null;
  lag_seconds: number | null;
  tracked_symbols: string[];
  recent_errors: string[];
};

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function getJson<T>(baseUrl: string, token: string, path: string): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
  } catch {
    throw new ApiError(0, "Não foi possível contactar o servidor.");
  }

  if (response.status === 401) {
    throw new ApiError(401, "Sessão expirada. Faça login novamente.");
  }
  if (!response.ok) {
    throw new ApiError(response.status, `Pedido falhou (HTTP ${response.status}).`);
  }
  return (await response.json()) as T;
}

export function fetchBars(
  baseUrl: string,
  token: string,
  symbol: string,
  timeframe: string,
  limit: number,
): Promise<Bar[]> {
  const query = new URLSearchParams({
    symbol,
    timeframe,
    limit: String(limit),
  });
  return getJson<Bar[]>(baseUrl, token, `/market-data/bars?${query.toString()}`);
}

export function fetchQuote(baseUrl: string, token: string, symbol: string): Promise<Quote> {
  const query = new URLSearchParams({ symbol });
  return getJson<Quote>(baseUrl, token, `/realtime/quote?${query.toString()}`);
}

export function fetchHealth(
  baseUrl: string,
  token: string,
  symbol?: string,
  timeframe?: string,
): Promise<FeedHealth> {
  const query = new URLSearchParams();
  if (symbol) {
    query.set("symbol", symbol);
  }
  if (timeframe) {
    query.set("timeframe", timeframe);
  }
  const suffix = query.toString() ? `?${query.toString()}` : "";
  return getJson<FeedHealth>(baseUrl, token, `/realtime/health${suffix}`);
}
