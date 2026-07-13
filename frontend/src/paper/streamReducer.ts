// Pure state logic for the paper cockpit stream (unit-tested, no React).

import type {
  EngineStatusWire,
  PaperEventWire,
  PaperPnl,
  PaperStreamMessage,
  SymbolSignals,
} from "./api";

export const MAX_EVENTS = 200;
// Server persists ~1 point/min while the engine runs; 3000 covers days of RTH.
export const MAX_EQUITY_POINTS = 3000;

export type LivePosition = {
  symbol: string;
  quantity: number;
  avg_entry_price: number;
  last_price: number | null;
  unrealized_pnl: number | null;
  opened_at: string | null;
  strategy: string | null;
  rationale: string | null;
  stop_price: number | null;
  take_profit_price: number | null;
};

export type PaperStreamState = {
  events: PaperEventWire[]; // newest first
  status: EngineStatusWire | null;
  pnl: PaperPnl | null;
  positions: LivePosition[];
  signals: Record<string, SymbolSignals>;
  equitySeries: Array<{ at: string; equity: number }>;
  lastEventId: number | null;
};

export type PaperStreamAction =
  | { kind: "message"; message: PaperStreamMessage }
  | { kind: "seed_events"; events: PaperEventWire[] }
  | {
      kind: "seed_state";
      status?: EngineStatusWire;
      pnl?: PaperPnl;
      positions?: LivePosition[];
      signals?: Record<string, SymbolSignals>;
    }
  | { kind: "seed_equity"; points: Array<{ at: string; equity: number }> }
  | { kind: "reset" };

export const initialStreamState: PaperStreamState = {
  events: [],
  status: null,
  pnl: null,
  positions: [],
  signals: {},
  equitySeries: [],
  lastEventId: null,
};

function mergeEvents(
  current: PaperEventWire[],
  incoming: PaperEventWire[],
): PaperEventWire[] {
  const seen = new Set(current.map((event) => event.id));
  const fresh = incoming.filter((event) => !seen.has(event.id));
  return [...fresh, ...current]
    .sort((a, b) => b.id - a.id)
    .slice(0, MAX_EVENTS);
}

export function reduceStream(
  state: PaperStreamState,
  action: PaperStreamAction,
): PaperStreamState {
  switch (action.kind) {
    case "reset":
      return initialStreamState;

    case "seed_events": {
      const events = mergeEvents(state.events, action.events);
      return { ...state, events, lastEventId: events[0]?.id ?? state.lastEventId };
    }

    case "seed_state":
      return {
        ...state,
        status: action.status ?? state.status,
        pnl: action.pnl ?? state.pnl,
        positions: action.positions ?? state.positions,
        signals: action.signals ?? state.signals,
      };

    case "seed_equity": {
      // Server history is authoritative; live points accumulated before the
      // seed arrived are folded in after it (dedup by timestamp happens at
      // render time in toEquitySeries).
      const equitySeries = [...action.points, ...state.equitySeries].slice(
        -MAX_EQUITY_POINTS,
      );
      return { ...state, equitySeries };
    }

    case "message": {
      const message = action.message;
      if (message.type === "engine_event") {
        const { type: _type, ...event } = message;
        const events = mergeEvents(state.events, [event]);
        return { ...state, events, lastEventId: events[0]?.id ?? null };
      }
      if (message.type === "engine_state") {
        const equitySeries = [
          ...state.equitySeries,
          { at: message.at, equity: message.pnl.equity },
        ].slice(-MAX_EQUITY_POINTS);
        return {
          ...state,
          status: message.status,
          pnl: message.pnl,
          positions: message.positions,
          signals: message.signals ?? state.signals,
          equitySeries,
        };
      }
      return state; // pong / error handled by the hook
    }

    default:
      return state;
  }
}

// Events that change the pending-orders panel; the page refetches on these.
const ORDER_EVENT_TYPES = new Set([
  "order_proposed",
  "order_approved",
  "order_rejected",
  "order_cancelled",
  "order_expired",
  "order_filled",
  "risk_veto",
]);

export function affectsPendingOrders(eventType: string): boolean {
  return ORDER_EVENT_TYPES.has(eventType);
}

// Cockpit colour class per event type (paper.css).
export function eventTone(event: PaperEventWire): "up" | "down" | "warn" | "neutral" {
  if (event.severity === "error") return "down";
  switch (event.event_type) {
    case "order_filled":
    case "take_profit_hit":
    case "feed_recovered":
    case "kill_switch_off":
      return "up";
    case "risk_veto":
    case "stop_loss_hit":
    case "kill_switch_on":
      return "down";
    case "fill_deferred":
    case "feed_stale":
    case "cooldown_started":
    case "order_expired":
      return "warn";
    default:
      return "neutral";
  }
}
