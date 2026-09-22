import { describe, expect, it } from "vitest";

import {
  fmtClock,
  MARKETS,
  marketStatus,
  sessionsLabelLocal,
  sessionsLabelMarket,
  type Market,
} from "./marketHours";

const byId = (id: string): Market => {
  const market = MARKETS.find((m) => m.id === id);
  if (!market) throw new Error(`unknown market ${id}`);
  return market;
};

const nyse = byId("nyse");
const tokyo = byId("tse");
const lisbon = byId("lis");

describe("marketStatus", () => {
  // 2026-07-14 is a Tuesday; 15:00Z = 11:00 in New York (EDT, UTC-4).
  it("NYSE open mid-session", () => {
    expect(marketStatus(nyse, new Date("2026-07-14T15:00:00Z"))).toBe("open");
  });

  it("NYSE closed before the bell (09:00 NY)", () => {
    expect(marketStatus(nyse, new Date("2026-07-14T13:00:00Z"))).toBe("closed");
  });

  it("NYSE closed right at 16:00 NY", () => {
    expect(marketStatus(nyse, new Date("2026-07-14T20:00:00Z"))).toBe("closed");
  });

  it("NYSE closed on Saturday even at a mid-session hour", () => {
    expect(marketStatus(nyse, new Date("2026-07-18T15:00:00Z"))).toBe("closed");
  });

  it("NYSE respects winter time (EST): 14:00Z in January is pre-open", () => {
    // 2026-01-14 is a Wednesday; 14:00Z = 09:00 EST.
    expect(marketStatus(nyse, new Date("2026-01-14T14:00:00Z"))).toBe("closed");
    expect(marketStatus(nyse, new Date("2026-01-14T15:00:00Z"))).toBe("open");
  });

  it("Tokyo lunch break between the two sessions", () => {
    // 03:00Z = 12:00 in Tokyo (UTC+9), inside the 11:30–12:30 break.
    expect(marketStatus(tokyo, new Date("2026-07-14T03:00:00Z"))).toBe("lunch");
    expect(marketStatus(tokyo, new Date("2026-07-14T01:00:00Z"))).toBe("open");
    expect(marketStatus(tokyo, new Date("2026-07-14T04:00:00Z"))).toBe("open");
  });

  it("weekday in the market's own timezone decides the weekend", () => {
    // Friday 23:00Z is already Saturday 09:00 in Sydney — closed there.
    const sydney = byId("asx");
    expect(marketStatus(sydney, new Date("2026-07-17T23:30:00Z"))).toBe("closed");
  });
});

describe("session labels", () => {
  it("market-local label keeps the exchange's own hours", () => {
    expect(sessionsLabelMarket(nyse)).toBe("09:30–16:00");
    expect(sessionsLabelMarket(tokyo)).toBe("09:00–11:30 · 12:30–15:30");
  });

  it("translates NYSE hours to another timezone, DST-aware", () => {
    // July: EDT (UTC-4) -> 13:30Z, viewed in UTC.
    expect(sessionsLabelLocal(nyse, new Date("2026-07-14T12:00:00Z"), "UTC")).toBe(
      "13:30–20:00",
    );
    // January: EST (UTC-5) -> 14:30Z.
    expect(sessionsLabelLocal(nyse, new Date("2026-01-14T12:00:00Z"), "UTC")).toBe(
      "14:30–21:00",
    );
  });

  it("translates NYSE hours to Lisbon time", () => {
    // July: Lisbon is WEST (UTC+1) -> 09:30 EDT = 14:30 in Lisbon.
    expect(
      sessionsLabelLocal(nyse, new Date("2026-07-14T12:00:00Z"), "Europe/Lisbon"),
    ).toBe("14:30–21:00");
  });

  it("Lisbon session is identity when viewed from Lisbon", () => {
    expect(
      sessionsLabelLocal(lisbon, new Date("2026-07-14T12:00:00Z"), "Europe/Lisbon"),
    ).toBe("08:00–16:30");
  });
});

describe("fmtClock", () => {
  it("renders the wall clock of the requested timezone", () => {
    const at = new Date("2026-07-14T15:04:05Z");
    expect(fmtClock(at, "UTC")).toBe("15:04:05");
    expect(fmtClock(at, "America/New_York")).toBe("11:04:05");
  });
});
