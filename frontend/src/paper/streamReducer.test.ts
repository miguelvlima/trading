import { describe, expect, it } from "vitest";

import type { EngineStatusWire, PaperEventWire, PaperPnl } from "./api";
import {
  affectsPendingOrders,
  eventTone,
  initialStreamState,
  MAX_EVENTS,
  reduceStream,
} from "./streamReducer";

function makeEvent(overrides: Partial<PaperEventWire> = {}): PaperEventWire {
  return {
    id: 1,
    event_type: "order_proposed",
    severity: "info",
    symbol: "AAPL",
    message: "Ordem proposta: BUY 12 AAPL @ mercado.",
    payload: {},
    created_at: "2026-07-08T15:00:00+00:00",
    ...overrides,
  };
}

function makeStatus(overrides: Partial<EngineStatusWire> = {}): EngineStatusWire {
  return {
    running: true,
    kill_switch_active: false,
    kill_switch_reason: null,
    feed_status: "fresh",
    feed_reason: null,
    feed_age_seconds: 2.5,
    data_liveness: "DELAYED",
    market_session: "rth",
    tracked_symbols: ["AAPL"],
    pending_orders: 0,
    cooldown_until: null,
    consecutive_losses: 0,
    max_consecutive_losses: 3,
    last_evaluation: null,
    poll_seconds: 15,
    ...overrides,
  };
}

function makePnl(overrides: Partial<PaperPnl> = {}): PaperPnl {
  return {
    equity: 100_000,
    cash: 90_000,
    unrealized_pnl: 0,
    realized_pnl_today: 0,
    fees_today: 0,
    day_pnl: 0,
    trades_today: 0,
    ...overrides,
  };
}

describe("reduceStream", () => {
  it("prepends engine events newest-first and tracks lastEventId", () => {
    let state = reduceStream(initialStreamState, {
      kind: "message",
      message: { type: "engine_event", ...makeEvent({ id: 1 }) },
    });
    state = reduceStream(state, {
      kind: "message",
      message: { type: "engine_event", ...makeEvent({ id: 2, event_type: "order_filled" }) },
    });
    expect(state.events.map((event) => event.id)).toEqual([2, 1]);
    expect(state.lastEventId).toBe(2);
  });

  it("deduplicates events already seeded from REST", () => {
    let state = reduceStream(initialStreamState, {
      kind: "seed_events",
      events: [makeEvent({ id: 5 }), makeEvent({ id: 4 })],
    });
    state = reduceStream(state, {
      kind: "message",
      message: { type: "engine_event", ...makeEvent({ id: 5 }) },
    });
    expect(state.events.map((event) => event.id)).toEqual([5, 4]);
  });

  it("caps the event list at MAX_EVENTS", () => {
    const events = Array.from({ length: MAX_EVENTS + 50 }, (_, index) =>
      makeEvent({ id: index + 1 }),
    );
    const state = reduceStream(initialStreamState, { kind: "seed_events", events });
    expect(state.events).toHaveLength(MAX_EVENTS);
    expect(state.events[0].id).toBe(MAX_EVENTS + 50); // newest kept
  });

  it("engine_state replaces status/pnl/positions and appends to the equity series", () => {
    let state = reduceStream(initialStreamState, {
      kind: "message",
      message: {
        type: "engine_state",
        status: makeStatus(),
        pnl: makePnl({ equity: 100_100 }),
        positions: [
          {
            symbol: "AAPL",
            quantity: 100,
            avg_entry_price: 100.05,
            last_price: 101.0,
            unrealized_pnl: 95,
            opened_at: "2026-07-08T15:00:00+00:00",
            strategy: "bollinger_breakout",
            rationale: "teste",
            stop_price: 98.05,
            take_profit_price: 104.05,
          },
        ],
        at: "2026-07-08T15:00:15+00:00",
      },
    });
    state = reduceStream(state, {
      kind: "message",
      message: {
        type: "engine_state",
        status: makeStatus({ feed_status: "stale" }),
        pnl: makePnl({ equity: 100_050 }),
        positions: [],
        at: "2026-07-08T15:00:30+00:00",
      },
    });
    expect(state.status?.feed_status).toBe("stale");
    expect(state.positions).toEqual([]);
    expect(state.equitySeries.map((point) => point.equity)).toEqual([100_100, 100_050]);
  });

  it("ignores pong and error messages", () => {
    const state = reduceStream(initialStreamState, {
      kind: "message",
      message: { type: "pong" },
    });
    expect(state).toEqual(initialStreamState);
  });
});

describe("affectsPendingOrders", () => {
  it("flags order lifecycle events and vetoes", () => {
    expect(affectsPendingOrders("order_proposed")).toBe(true);
    expect(affectsPendingOrders("risk_veto")).toBe(true);
    expect(affectsPendingOrders("signal_received")).toBe(false);
    expect(affectsPendingOrders("feed_stale")).toBe(false);
  });
});

describe("eventTone", () => {
  it("colours fills green, vetoes red, deferrals amber", () => {
    expect(eventTone(makeEvent({ event_type: "order_filled" }))).toBe("up");
    expect(eventTone(makeEvent({ event_type: "risk_veto" }))).toBe("down");
    expect(eventTone(makeEvent({ event_type: "fill_deferred" }))).toBe("warn");
    expect(eventTone(makeEvent({ event_type: "signal_received" }))).toBe("neutral");
  });

  it("error severity always reads as down", () => {
    expect(eventTone(makeEvent({ event_type: "engine_started", severity: "error" }))).toBe(
      "down",
    );
  });
});
