import { describe, expect, it } from "vitest";

import { computeRiskGauges, pnlBars, toEquitySeries } from "./monitor";
import type { LivePosition } from "./streamReducer";

function makePosition(overrides: Partial<LivePosition> = {}): LivePosition {
  return {
    symbol: "AAPL",
    quantity: 100,
    avg_entry_price: 100,
    last_price: 100,
    unrealized_pnl: 0,
    ...overrides,
  };
}

describe("computeRiskGauges", () => {
  const settings = {
    max_total_exposure_pct: 50,
    max_position_pct: 10,
    daily_loss_limit_pct: 3,
  };

  it("returns nothing without equity", () => {
    expect(
      computeRiskGauges({ positions: [], equity: 0, dayPnl: 0, riskSettings: settings }),
    ).toEqual([]);
  });

  it("measures exposure and largest position against their caps", () => {
    const positions = [
      makePosition({ symbol: "AAPL", quantity: 100, last_price: 100 }), // 10k
      makePosition({ symbol: "MSFT", quantity: 20, last_price: 250 }), // 5k
    ];
    const gauges = computeRiskGauges({
      positions,
      equity: 100_000,
      dayPnl: 0,
      riskSettings: settings,
    });
    const exposure = gauges.find((gauge) => gauge.key === "exposure")!;
    const position = gauges.find((gauge) => gauge.key === "position")!;
    expect(exposure.usedPct).toBe(15);
    expect(exposure.ratio).toBeCloseTo(0.3);
    expect(exposure.tone).toBe("ok");
    expect(position.usedPct).toBe(10);
    expect(position.ratio).toBe(1);
    expect(position.tone).toBe("danger");
  });

  it("uses avg_entry_price when last_price is missing", () => {
    const gauges = computeRiskGauges({
      positions: [makePosition({ last_price: null, avg_entry_price: 200, quantity: 10 })],
      equity: 10_000,
      dayPnl: 0,
      riskSettings: settings,
    });
    expect(gauges.find((gauge) => gauge.key === "exposure")!.usedPct).toBe(20);
  });

  it("daily loss gauge fills toward the kill switch only on losses", () => {
    const losing = computeRiskGauges({
      positions: [],
      equity: 98_500,
      dayPnl: -1_500,
      riskSettings: settings,
    }).find((gauge) => gauge.key === "daily_loss")!;
    expect(losing.usedPct).toBeCloseTo(1.5);
    expect(losing.ratio).toBeCloseTo(0.5);
    expect(losing.tone).toBe("ok");

    const gaining = computeRiskGauges({
      positions: [],
      equity: 101_000,
      dayPnl: 1_000,
      riskSettings: settings,
    }).find((gauge) => gauge.key === "daily_loss")!;
    expect(gaining.usedPct).toBe(0);
    expect(gaining.ratio).toBe(0);
  });

  it("warns above 70% of a cap", () => {
    const gauges = computeRiskGauges({
      positions: [makePosition({ quantity: 400, last_price: 100 })], // 40k = 80% of 50%-cap
      equity: 100_000,
      dayPnl: 0,
      riskSettings: settings,
    });
    expect(gauges.find((gauge) => gauge.key === "exposure")!.tone).toBe("warn");
  });
});

describe("pnlBars", () => {
  it("normalises widths to the largest absolute PnL, sorted best-first", () => {
    const bars = pnlBars([
      makePosition({ symbol: "AAPL", unrealized_pnl: 50 }),
      makePosition({ symbol: "MSFT", unrealized_pnl: -200 }),
      makePosition({ symbol: "NVDA", unrealized_pnl: 100 }),
    ]);
    expect(bars.map((bar) => bar.symbol)).toEqual(["NVDA", "AAPL", "MSFT"]);
    expect(bars[2].widthPct).toBe(100);
    expect(bars[1].widthPct).toBe(25);
    expect(bars[2].positive).toBe(false);
  });

  it("skips positions without a live PnL", () => {
    expect(pnlBars([makePosition({ unrealized_pnl: null })])).toEqual([]);
  });
});

describe("toEquitySeries", () => {
  it("deduplicates by second (last wins) and sorts ascending", () => {
    const series = toEquitySeries([
      { at: "2026-07-08T15:00:01.200Z", equity: 100 },
      { at: "2026-07-08T15:00:00.000Z", equity: 99 },
      { at: "2026-07-08T15:00:01.900Z", equity: 101 },
    ]);
    expect(series).toEqual([
      { time: Date.parse("2026-07-08T15:00:00.000Z") / 1000, value: 99 },
      { time: Math.floor(Date.parse("2026-07-08T15:00:01.900Z") / 1000), value: 101 },
    ]);
  });

  it("drops unparsable timestamps", () => {
    expect(toEquitySeries([{ at: "not-a-date", equity: 1 }])).toEqual([]);
  });
});
