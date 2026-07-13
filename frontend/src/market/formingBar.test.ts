import { afterEach, describe, expect, it, vi } from "vitest";

import type { Quote } from "../realtime/api";
import type { LiveTick } from "../realtime/useTickStream";

import {
  type TickAccumulator,
  accumulateTick,
  accumulatedVolume,
  isTickGapSuspicious,
  MAX_TICK_GAP_PCT,
  resolveFormingBar,
} from "./formingBar";

// 2026-07-09T15:02:30Z — a meio da vela 5m que abre às 15:00:00.
const NOW_MS = Date.UTC(2026, 6, 9, 15, 2, 30);
const BAR_15H00_SEC = Math.floor(Date.UTC(2026, 6, 9, 15, 0, 0) / 1000);

function makeQuote(overrides: Partial<Quote> = {}): Quote {
  return {
    symbol: "AMD",
    timestamp: "2026-07-09T14:55:00Z", // vela 5m imediatamente anterior (fresca)
    open: "207.10",
    high: "208.60",
    low: "206.90",
    close: "208.44",
    volume: "12000",
    is_final: true,
    ...overrides,
  };
}

function makeTick(overrides: Partial<LiveTick> = {}): LiveTick {
  return {
    symbol: "AMD",
    timestamp: "2026-07-09T15:02:29Z",
    last: 208.9,
    bid: 208.85,
    ask: 208.95,
    bidSize: 3,
    askSize: 5,
    lastSize: 1,
    volume: 1_500_000,
    dayHigh: 209.4,
    dayLow: 205.1,
    ...overrides,
  };
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("resolveFormingBar — barra da BD obsoleta", () => {
  it("abre no primeiro tick quando a última barra tem dias, sem usar o close da BD", () => {
    // Última barra 5m com 3 semanas — muito além do limiar de 6h do dataFreshness.
    const staleBar = makeQuote({ timestamp: "2026-06-18T19:55:00Z", close: "536.90" });
    vi.spyOn(console, "warn").mockImplementation(() => undefined);

    const { forming, isLiveForming } = resolveFormingBar(
      staleBar,
      "5m",
      makeTick({ last: 208.9 }),
      NOW_MS,
      null,
    );

    expect(isLiveForming).toBe(true);
    expect(forming).not.toBeNull();
    expect(forming!.time).toBe(BAR_15H00_SEC);
    // Nunca o preço obsoleto da BD: OHLC só de ticks.
    expect(forming!.open).toBe(208.9);
    expect(forming!.high).toBe(208.9);
    expect(forming!.low).toBe(208.9);
    expect(forming!.close).toBe(208.9);
    // Sem baseline de acumulado ainda => volume 0, nunca o acumulado do dia.
    expect(forming!.volume).toBe(0);
  });

  it("acumula high/low/close de ticks sucessivos na vela obsoleta", () => {
    const staleBar = makeQuote({ timestamp: "2026-06-18T19:55:00Z" });
    let acc: TickAccumulator | null = null;

    let result = resolveFormingBar(staleBar, "5m", makeTick({ last: 208.9 }), NOW_MS, acc);
    acc = result.acc;
    result = resolveFormingBar(staleBar, "5m", makeTick({ last: 210.2 }), NOW_MS + 1000, acc);
    acc = result.acc;
    result = resolveFormingBar(staleBar, "5m", makeTick({ last: 207.5 }), NOW_MS + 2000, acc);

    expect(result.forming).not.toBeNull();
    expect(result.forming!.open).toBe(208.9);
    expect(result.forming!.high).toBe(210.2);
    expect(result.forming!.low).toBe(207.5);
    expect(result.forming!.close).toBe(207.5);
  });
});

describe("resolveFormingBar — volume acumulado → delta", () => {
  it("usa o delta do acumulado da sessão como volume da vela, não o acumulado", () => {
    const freshBar = makeQuote(); // fecha às 15:00, período fechado → nova vela sintetizada
    let acc: TickAccumulator | null = null;

    let result = resolveFormingBar(
      freshBar,
      "5m",
      makeTick({ last: 208.9, volume: 1_500_000 }),
      NOW_MS,
      acc,
    );
    acc = result.acc;
    result = resolveFormingBar(
      freshBar,
      "5m",
      makeTick({ last: 209.1, volume: 1_512_500 }),
      NOW_MS + 5000,
      acc,
    );

    expect(result.forming).not.toBeNull();
    // 1_512_500 - 1_500_000, nunca os 1.5M acumulados do dia.
    expect(result.forming!.volume).toBe(12_500);
    expect(result.forming!.open).toBe(Number(freshBar.close));
    expect(result.forming!.close).toBe(209.1);
  });

  it("faz rollover da baseline quando a vela muda de período", () => {
    const tickA = makeTick({ volume: 1_000_000, last: 208.0 });
    const tickB = makeTick({ volume: 1_050_000, last: 208.5 });

    const barA = accumulateTick(null, "AMD", "5m", BAR_15H00_SEC, tickA);
    // Nova vela 5m: a baseline passa a ser o último acumulado da vela anterior.
    const barB = accumulateTick(barA, "AMD", "5m", BAR_15H00_SEC + 300, tickB);

    expect(barB).not.toBeNull();
    expect(barB!.volumeBase).toBe(1_000_000);
    expect(accumulatedVolume(barB)).toBe(50_000);
  });

  it("trata reset do acumulado (nova sessão) sem volume negativo", () => {
    const acc: TickAccumulator = {
      symbol: "AMD",
      candle: "5m",
      openSec: BAR_15H00_SEC,
      open: 208,
      high: 208,
      low: 208,
      close: 208,
      volumeBase: 1_500_000,
      cumVolume: 4_200, // contador recomeçou (nova sessão)
    };
    expect(accumulatedVolume(acc)).toBe(4_200);
  });
});

describe("resolveFormingBar — guard de gap de preço", () => {
  it("descarta a barra da BD e avisa quando |tick - close| excede o limiar", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    // Barra fresca mas com close incompatível com o tick (>20% de desvio).
    const freshBar = makeQuote({ close: "536.90", high: "537.00" });

    const { forming } = resolveFormingBar(freshBar, "5m", makeTick({ last: 208.9 }), NOW_MS, null);

    expect(forming).not.toBeNull();
    // A vela abre no tick, não estica desde o close incompatível.
    expect(forming!.open).toBe(208.9);
    expect(forming!.high).toBe(208.9);
    expect(warn).toHaveBeenCalledTimes(1);
    expect(warn.mock.calls[0][0]).toContain(`${MAX_TICK_GAP_PCT}%`);
  });

  it("não dispara para variações normais", () => {
    expect(isTickGapSuspicious(208.44, 208.9)).toBe(false);
    expect(isTickGapSuspicious(208.44, 536.9)).toBe(true);
    expect(isTickGapSuspicious(0, 100)).toBe(false); // close inválido nunca dispara
  });
});

describe("resolveFormingBar — comportamento fresco preservado", () => {
  it("continua a barra da BD quando o período ainda não fechou", () => {
    // Barra 5m das 15:00 ainda em curso às 15:02:30.
    const openBar = makeQuote({ timestamp: "2026-07-09T15:00:00Z" });
    const { forming } = resolveFormingBar(openBar, "5m", makeTick({ last: 209.0 }), NOW_MS, null);

    expect(forming).not.toBeNull();
    expect(forming!.time).toBe(BAR_15H00_SEC);
    expect(forming!.open).toBe(Number(openBar.open));
    expect(forming!.high).toBe(209.0);
    expect(forming!.volume).toBe(Number(openBar.volume));
  });

  it("ignora ticks de outro símbolo", () => {
    const { forming } = resolveFormingBar(
      makeQuote(),
      "5m",
      makeTick({ symbol: "NVDA" }),
      NOW_MS,
      null,
    );
    expect(forming).toBeNull();
  });
});
