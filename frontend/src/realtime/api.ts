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

export type SymbolMatch = {
  symbol: string;
  name: string | null;
  sec_type: string | null;
  exchange: string | null;
  currency: string | null;
};

export type Instrument = {
  id: number;
  symbol: string;
  name: string | null;
  exchange: string | null;
  currency: string;
  followed?: boolean;
};

export type IndexSpec = {
  symbol: string;
  name: string;
};

// The "available" universe shown in the symbol search before the user types:
// curated majors, the live IBKR market scanner (most active), and the index
// strip. `group` selects the section; the user can browse/pick from it while
// still searching the full IBKR universe by typing.
export type OnlineGroup = "major" | "active" | "index";

export type OnlineSymbol = {
  symbol: string;
  name: string | null;
  group: OnlineGroup;
  exchange?: string | null;
};

// --- WebSocket message shapes (server -> client) ---------------------------
// Numeric fields arrive as strings (or null when IBKR has not reported them).

export type TickMessage = {
  type: "tick";
  symbol: string;
  timestamp: string;
  last: string | null;
  bid: string | null;
  ask: string | null;
  bid_size: string | null;
  ask_size: string | null;
  last_size: string | null;
  volume: string | null;
  day_high: string | null;
  day_low: string | null;
};

export type IndexMessage = {
  type: "index";
  symbol: string;
  name: string;
  timestamp: string;
  last: string | null;
  change_pct: string | null;
};

export type StreamMessage =
  | TickMessage
  | IndexMessage
  | { type: "subscribed"; symbol: string | null; active_lines: number }
  | { type: "error"; code: string; message: string }
  | { type: "pong" };

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

export function searchSymbols(
  baseUrl: string,
  token: string,
  query: string,
): Promise<SymbolMatch[]> {
  const params = new URLSearchParams({ q: query });
  return getJson<SymbolMatch[]>(baseUrl, token, `/realtime/symbols/search?${params.toString()}`);
}

export function fetchInstruments(baseUrl: string, token: string): Promise<Instrument[]> {
  return getJson<Instrument[]>(baseUrl, token, "/market-data/instruments");
}

async function sendJson(
  baseUrl: string,
  token: string,
  method: "POST" | "DELETE",
  path: string,
  body?: unknown,
): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${baseUrl}${path}`, {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
  } catch {
    throw new ApiError(0, "Não foi possível contactar o servidor.");
  }
  if (response.status === 401) throw new ApiError(401, "Sessão expirada. Faça login novamente.");
  if (!response.ok) throw new ApiError(response.status, `Pedido falhou (HTTP ${response.status}).`);
  return response;
}

// Start following a symbol (creates the instrument if it does not exist yet).
export function followInstrument(
  baseUrl: string,
  token: string,
  symbol: string,
  name?: string | null,
): Promise<Response> {
  return sendJson(baseUrl, token, "POST", `/market-data/instruments/${encodeURIComponent(symbol)}/follow`, {
    name: name ?? null,
  });
}

// Stop following a symbol (soft flag flip; bars are preserved).
export function unfollowInstrument(
  baseUrl: string,
  token: string,
  symbol: string,
): Promise<Response> {
  return sendJson(baseUrl, token, "DELETE", `/market-data/instruments/${encodeURIComponent(symbol)}/follow`);
}

// Provider-backed history for the chart. `window` (1H..All) selects the IBKR
// duration + throttled pagination on the backend; `limit` is the fallback for
// providers without pagination.
export function fetchHistory(
  baseUrl: string,
  token: string,
  symbol: string,
  timeframe: string,
  window: string,
  limit: number,
): Promise<Quote[]> {
  const query = new URLSearchParams({
    symbol,
    timeframe,
    window,
    limit: String(limit),
  });
  return getJson<Quote[]>(baseUrl, token, `/realtime/history?${query.toString()}`);
}

export function fetchIndices(baseUrl: string, token: string): Promise<IndexSpec[]> {
  return getJson<IndexSpec[]>(baseUrl, token, "/realtime/indices");
}

// The "available now" picker list: curated majors + live IBKR scanner + indices.
export function fetchAvailable(baseUrl: string, token: string): Promise<OnlineSymbol[]> {
  return getJson<OnlineSymbol[]>(baseUrl, token, "/realtime/available");
}

// Build the ws(s):// URL for the tick stream from the http(s) API base, carrying
// the JWT in the query string (the WS handshake cannot send an auth header).
export function realtimeWsUrl(baseUrl: string, token: string): string {
  const resolvedBase =
    baseUrl ||
    (typeof globalThis !== "undefined" && "location" in globalThis
      ? globalThis.location.origin
      : "http://localhost:8000");
  let origin = resolvedBase;
  if (origin.startsWith("https")) origin = "wss" + origin.slice(5);
  else if (origin.startsWith("http")) origin = "ws" + origin.slice(4);
  return `${origin}/realtime/ws?token=${encodeURIComponent(token)}`;
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
