// Typed client for the /paper REST API + WS message shapes.
// Follows the realtime/api.ts pattern: every call takes (baseUrl, token, ...).

export type EngineStatusWire = {
  running: boolean;
  kill_switch_active: boolean;
  kill_switch_reason: string | null;
  feed_status: "fresh" | "stale" | "unavailable";
  feed_reason: "engine_stopped" | "no_provider" | "market_closed" | "no_ticks" | null;
  feed_age_seconds: number | null;
  data_liveness: string;
  market_session: "rth" | "closed";
  tracked_symbols: string[];
  pending_orders: number;
  cooldown_until: string | null;
  consecutive_losses: number;
  max_consecutive_losses: number;
  last_evaluation: EvaluationSummary | null;
  poll_seconds: number | null;
  last_signals: Record<string, SymbolSignals> | null;
};

// Live signal monitor per symbol: the engine's latest verdict per strategy on
// the current bar, plus WHEN it last checked (advances every poll).
export type SignalMonitorEntry = {
  strategy: string;
  outcome: "proposed" | "vetoed" | "skipped" | "none" | "error" | "pending";
  direction?: "BUY" | "SELL";
  strength?: number;
};

export type SymbolSignals = {
  checked_at: string;
  bar_time: string | null;
  no_quote?: boolean;
  signals: SignalMonitorEntry[];
};

// What the engine's last strategy sweep did (explains cockpit "silence").
export type EvaluationSummary = {
  at: string;
  symbols_total: number;
  strategies: number;
  timeframe: string;
  no_quote: number;
  no_bars: number;
  evaluated: number;
  signals: number;
  proposals: number;
};

export type PaperEquityPoint = {
  at: string;
  equity: number;
  cash: number;
};

export type PaperPortfolio = {
  id: number;
  initial_cash: number;
  cash: number;
  equity: number;
  risk_settings: Record<string, unknown>;
  engine_running: boolean;
  kill_switch_active: boolean;
  kill_switch_reason: string | null;
  created_at: string;
  updated_at: string;
};

export type PaperOrder = {
  id: number;
  symbol: string;
  side: "BUY" | "SELL";
  quantity: number;
  order_type: string;
  status: string;
  stop_loss_pct: number | null;
  take_profit_pct: number | null;
  signal_snapshot: Record<string, unknown>;
  risk_snapshot: Record<string, unknown>;
  data_liveness: string;
  reject_reason: string | null;
  proposed_at: string;
  decided_at: string | null;
  filled_at: string | null;
};

export type PaperPositionWire = {
  symbol: string;
  quantity: number;
  avg_entry_price: number;
  realized_pnl: number;
  last_price: number | null;
  unrealized_pnl: number | null;
  opened_at: string | null;
  strategy: string | null;
  rationale: string | null;
  stop_price: number | null;
  take_profit_price: number | null;
  updated_at: string;
};

export type PaperPnl = {
  equity: number;
  cash: number;
  unrealized_pnl: number;
  realized_pnl_today: number;
  fees_today: number;
  day_pnl: number;
  trades_today: number;
};

export type PaperTradeWire = {
  id: number;
  order_id: number;
  symbol: string;
  side: "BUY" | "SELL";
  quantity: number;
  price: number;
  fee_paid: number;
  fill_basis: string;
  quote_age_seconds: number | null;
  data_liveness: string;
  realized_pnl: number | null;
  executed_at: string;
};

// One signal the engine saw — weak ones included — with the outcome stamped
// by the backend (see /paper/signals).
export type PaperSignalWire = {
  id: number;
  at: string;
  symbol: string;
  strategy: string;
  direction: "BUY" | "SELL" | "?";
  strength: number | null;
  min_strength: number | null;
  rationale: string | null;
  bar_time: string | null;
  outcome: "proposed" | "vetoed" | "skipped" | "pending" | "unknown";
  reason: string | null;
  order_id: number | null;
};

export type PaperEventWire = {
  id: number;
  event_type: string;
  severity: "info" | "warn" | "error";
  symbol: string | null;
  message: string;
  payload: Record<string, unknown>;
  created_at: string;
};

// Server -> client WS messages.
export type PaperStreamMessage =
  | ({ type: "engine_event" } & PaperEventWire)
  | {
      type: "engine_state";
      status: EngineStatusWire;
      pnl: PaperPnl;
      positions: Array<{
        symbol: string;
        quantity: number;
        avg_entry_price: number;
        last_price: number;
        unrealized_pnl: number;
        opened_at: string | null;
        strategy: string | null;
        rationale: string | null;
        stop_price: number | null;
        take_profit_price: number | null;
      }>;
      signals?: Record<string, SymbolSignals>;
      at: string;
    }
  | { type: "pong" }
  | { type: "error"; code: string; message: string };

export class PaperApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(
  baseUrl: string,
  token: string,
  method: "GET" | "POST" | "PUT",
  path: string,
  body?: unknown,
): Promise<T> {
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const response = await fetch(`${baseUrl}${path}`, {
    method,
    headers,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const parsed = await response.json();
      if (parsed && typeof parsed.detail === "string") detail = parsed.detail;
    } catch {
      // keep the HTTP status fallback
    }
    if (response.status === 401) detail = "Sessão expirada. Faz login novamente.";
    throw new PaperApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

export const getPaperPortfolio = (baseUrl: string, token: string) =>
  request<PaperPortfolio>(baseUrl, token, "GET", "/paper/portfolio");

export const createPaperPortfolio = (baseUrl: string, token: string, initialCash: number) =>
  request<PaperPortfolio>(baseUrl, token, "POST", "/paper/portfolio", {
    initial_cash: initialCash,
  });

export const resetPaperPortfolio = (baseUrl: string, token: string, initialCash: number) =>
  request<PaperPortfolio>(baseUrl, token, "POST", "/paper/portfolio/reset", {
    initial_cash: initialCash,
  });

export const updatePaperRiskSettings = (
  baseUrl: string,
  token: string,
  settings: Record<string, unknown>,
) =>
  request<PaperPortfolio>(baseUrl, token, "PUT", "/paper/portfolio/risk-settings", {
    risk_settings: settings,
  });

export const getPaperOrders = (baseUrl: string, token: string, status?: string) =>
  request<PaperOrder[]>(
    baseUrl,
    token,
    "GET",
    `/paper/orders${status ? `?status=${encodeURIComponent(status)}` : ""}`,
  );

export const approvePaperOrder = (baseUrl: string, token: string, orderId: number) =>
  request<PaperOrder>(baseUrl, token, "POST", `/paper/orders/${orderId}/approve`);

export const rejectPaperOrder = (baseUrl: string, token: string, orderId: number) =>
  request<PaperOrder>(baseUrl, token, "POST", `/paper/orders/${orderId}/reject`);

export const getPaperPositions = (baseUrl: string, token: string) =>
  request<PaperPositionWire[]>(baseUrl, token, "GET", "/paper/positions");

export const closePaperPosition = (baseUrl: string, token: string, symbol: string) =>
  request<PaperOrder>(
    baseUrl,
    token,
    "POST",
    `/paper/positions/${encodeURIComponent(symbol)}/close`,
  );

export const getPaperPnl = (baseUrl: string, token: string) =>
  request<PaperPnl>(baseUrl, token, "GET", "/paper/pnl");

export const getPaperTrades = (baseUrl: string, token: string, limit = 100) =>
  request<PaperTradeWire[]>(baseUrl, token, "GET", `/paper/trades?limit=${limit}`);

export const getPaperEquity = (baseUrl: string, token: string, limit = 2000) =>
  request<PaperEquityPoint[]>(baseUrl, token, "GET", `/paper/equity?limit=${limit}`);

export const cancelPaperOrder = (baseUrl: string, token: string, orderId: number) =>
  request<PaperOrder>(baseUrl, token, "POST", `/paper/orders/${orderId}/cancel`);

export const getStrategies = (baseUrl: string, token: string) =>
  request<string[]>(baseUrl, token, "GET", "/signals/strategies");

export const getPaperSignals = (baseUrl: string, token: string, limit = 200) =>
  request<PaperSignalWire[]>(baseUrl, token, "GET", `/paper/signals?limit=${limit}`);

export const getPaperEvents = (baseUrl: string, token: string, limit = 50) =>
  request<PaperEventWire[]>(baseUrl, token, "GET", `/paper/events?limit=${limit}`);

export const getEngineStatus = (baseUrl: string, token: string) =>
  request<EngineStatusWire>(baseUrl, token, "GET", "/paper/engine/status");

export const startEngine = (baseUrl: string, token: string) =>
  request<EngineStatusWire>(baseUrl, token, "POST", "/paper/engine/start");

export const stopEngine = (baseUrl: string, token: string) =>
  request<EngineStatusWire>(baseUrl, token, "POST", "/paper/engine/stop");

export const resetKillSwitch = (baseUrl: string, token: string) =>
  request<EngineStatusWire>(baseUrl, token, "POST", "/paper/engine/kill-switch/reset");

export function paperWsUrl(baseUrl: string, token: string): string {
  const origin =
    baseUrl && baseUrl.length > 0
      ? baseUrl
      : typeof window !== "undefined"
        ? window.location.origin
        : "http://127.0.0.1:8100";
  const wsOrigin = origin.replace(/^http/, "ws");
  return `${wsOrigin}/paper/ws?token=${encodeURIComponent(token)}`;
}
