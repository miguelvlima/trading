import { describe, expect, it } from "vitest";

import {
  applyFormSnapshot,
  inferChartWindowFromLimit,
  parsePresetConfig,
  parseRunConfig,
  summarizeAppliedRunConfig,
  type BacktestRunLike,
  type RunConfigFormSetters,
} from "./backtestRunConfig";
import { fetchLimitFor } from "../market/windowCandle";

function makeRun(overrides: Partial<BacktestRunLike> & Pick<BacktestRunLike, "result_summary">): BacktestRunLike {
  return {
    symbol: "AMZN",
    timeframe: "1d",
    strategy_names: ["rsi_mean_reversion"],
    start_at: null,
    end_at: null,
    initial_capital: 10_000,
    fee_bps: 5,
    slippage_bps: 2,
    min_signal_strength: 0.1,
    bars_processed: 407,
    ...overrides,
  };
}

describe("parseRunConfig", () => {
  it("infers bars mode for legacy runs without period_mode", () => {
    const parsed = parseRunConfig(
      makeRun({
        bars_processed: 407,
        result_summary: {
          config: {
            strategies: ["rsi_mean_reversion"],
            limit: 407,
            initial_capital: 10_000,
            fee_bps: 5,
            slippage_bps: 2,
            min_signal_strength: 0.1,
            entry_confirmation_bars: 1,
            execution_timing: "next_open",
            exit_mode: "tp_sl_or_opposite",
            stop_loss_pct: 2,
            take_profit_pct: 4,
          },
        },
      }),
    );

    expect(parsed.periodMode).toBe("bars");
    expect(parsed.barLimit).toBe(407);
    expect(parsed.strategies).toEqual(["rsi_mean_reversion"]);
  });

  it("restores date mode when run has start/end", () => {
    const parsed = parseRunConfig(
      makeRun({
        start_at: "2024-01-01T00:00:00Z",
        end_at: "2024-12-31T23:59:59Z",
        result_summary: {
          config: {
            limit: 500,
            period_mode: "date",
          },
        },
      }),
    );

    expect(parsed.periodMode).toBe("date");
    expect(parsed.startDate).toBe("2024-01-01");
    expect(parsed.endDate).toBe("2024-12-31");
  });

  it("restores window mode with chart_window", () => {
    const parsed = parseRunConfig(
      makeRun({
        result_summary: {
          config: {
            limit: fetchLimitFor("1y", "1d"),
            period_mode: "window",
            chart_window: "1y",
          },
        },
      }),
    );

    expect(parsed.periodMode).toBe("window");
    expect(parsed.chartWindow).toBe("1y");
  });

  it("infers chart window when period_mode is window but chart_window missing", () => {
    const limit = fetchLimitFor("1y", "1d");
    const parsed = parseRunConfig(
      makeRun({
        timeframe: "1d",
        result_summary: {
          config: {
            limit,
            period_mode: "window",
          },
        },
      }),
    );

    expect(parsed.periodMode).toBe("window");
    expect(parsed.chartWindow).toBe("1y");
  });

  it("uses defaults for opposite_signal exit without SL/TP in config", () => {
    const parsed = parseRunConfig(
      makeRun({
        result_summary: {
          config: {
            limit: 500,
            exit_mode: "opposite_signal",
            stop_loss_pct: null,
            take_profit_pct: null,
          },
        },
      }),
    );

    expect(parsed.exitMode).toBe("opposite_signal");
    expect(parsed.stopLossPct).toBe(2);
    expect(parsed.takeProfitPct).toBe(4);
  });
});

describe("parsePresetConfig", () => {
  it("defaults legacy presets to bars mode with stored limit", () => {
    const snapshot = parsePresetConfig({
      id: "1",
      name: "legacy",
      strategies: ["macd_crossover"],
      initialCapital: 10_000,
      feeBps: 5,
      feeModel: "fixed_bps",
      slippageBps: 2,
      slippageModel: "atr_volume",
      strategyMinStrengthPct: { macd_crossover: 15 },
      consensusStrengthPct: 15,
      limit: 407,
      positionSizePct: 100,
      positionSizingModel: "fixed_pct",
      riskPerTradePct: 1,
      entryConfirmationBars: 1,
      executionTiming: "next_open",
      exitMode: "tp_sl_or_opposite",
      stopLossPct: 2,
      takeProfitPct: 4,
      maxBarsInTrade: 40,
      walkforwardSplitPct: 0,
      walkforwardMode: "holdout",
      walkforwardFolds: 3,
      benchmarkEnabled: true,
    });

    expect(snapshot.periodMode).toBe("bars");
    expect(snapshot.barLimit).toBe(407);
  });

  it("restores window presets with chart window", () => {
    const snapshot = parsePresetConfig({
      id: "2",
      name: "window",
      strategies: ["rsi_mean_reversion"],
      initialCapital: 10_000,
      feeBps: 5,
      feeModel: "fixed_bps",
      slippageBps: 2,
      slippageModel: "atr_volume",
      strategyMinStrengthPct: { rsi_mean_reversion: 10 },
      consensusStrengthPct: 10,
      periodMode: "window",
      chartWindow: "1mo",
      barLimit: fetchLimitFor("1mo", "1d"),
      limit: fetchLimitFor("1mo", "1d"),
      positionSizePct: 100,
      positionSizingModel: "fixed_pct",
      riskPerTradePct: 1,
      entryConfirmationBars: 1,
      executionTiming: "next_open",
      exitMode: "tp_sl_or_opposite",
      stopLossPct: 2,
      takeProfitPct: 4,
      maxBarsInTrade: 40,
      walkforwardSplitPct: 0,
      walkforwardMode: "holdout",
      walkforwardFolds: 3,
      benchmarkEnabled: true,
    });

    expect(snapshot.periodMode).toBe("window");
    expect(snapshot.chartWindow).toBe("1mo");
  });
});

describe("inferChartWindowFromLimit", () => {
  it("picks the closest window for a 1d candle limit", () => {
    const limit = fetchLimitFor("1y", "1d");
    expect(inferChartWindowFromLimit("1d", limit)).toBe("1y");
  });
});

describe("summarizeAppliedRunConfig", () => {
  it("builds readable summary lines", () => {
    const run = makeRun({
      result_summary: { config: { limit: 407, strategies: ["rsi_mean_reversion"] } },
    });
    const parsed = parseRunConfig(run);
    const lines = summarizeAppliedRunConfig(run, parsed, { rsi_mean_reversion: "RSI" });
    expect(lines[0]).toContain("AMZN");
    expect(lines[0]).toContain("RSI");
    expect(lines[1]).toContain("407 velas");
  });
});

describe("applyFormSnapshot", () => {
  it("applies all setters including period mode and bar limit", () => {
    const calls: string[] = [];
    const setters = {
      setSelectedSymbol: (v: string) => calls.push(`symbol:${v}`),
      setCandle: () => calls.push("candle"),
      setChartWindow: (v: string) => calls.push(`window:${v}`),
      setManualCandle: () => calls.push("manual"),
      setPeriodMode: (v: string) => calls.push(`period:${v}`),
      setStartDate: () => calls.push("start"),
      setEndDate: () => calls.push("end"),
      setBacktestLimit: (v: number) => calls.push(`limit:${v}`),
      setActiveStrategies: () => calls.push("strategies"),
      setBacktestInitialCapital: () => calls.push("capital"),
      setBacktestFeeBps: () => calls.push("fee"),
      setBacktestFeeModel: () => calls.push("feeModel"),
      setBacktestSlippageBps: () => calls.push("slippage"),
      setBacktestSlippageModel: () => calls.push("slippageModel"),
      setBacktestStrategyMinStrengthPct: () => calls.push("strengths"),
      setBacktestConsensusStrengthPct: () => calls.push("consensus"),
      setBacktestPositionSizePct: () => calls.push("position"),
      setBacktestPositionSizingModel: () => calls.push("sizing"),
      setBacktestRiskPerTradePct: () => calls.push("risk"),
      setBacktestEntryConfirmationBars: () => calls.push("confirm"),
      setBacktestExecutionTiming: () => calls.push("execution"),
      setBacktestExitMode: () => calls.push("exit"),
      setBacktestStopLossPct: () => calls.push("sl"),
      setBacktestTakeProfitPct: () => calls.push("tp"),
      setBacktestMaxBarsInTrade: () => calls.push("maxBars"),
      setBacktestWalkforwardSplitPct: () => calls.push("wfSplit"),
      setBacktestWalkforwardMode: () => calls.push("wfMode"),
      setBacktestWalkforwardFolds: () => calls.push("wfFolds"),
      setBacktestBenchmarkEnabled: () => calls.push("benchmark"),
    } as unknown as RunConfigFormSetters;

    applyFormSnapshot(
      parsePresetConfig({
        id: "3",
        name: "bars",
        strategies: ["rsi_mean_reversion"],
        initialCapital: 10_000,
        feeBps: 5,
        feeModel: "fixed_bps",
        slippageBps: 2,
        slippageModel: "atr_volume",
        strategyMinStrengthPct: { rsi_mean_reversion: 10 },
        consensusStrengthPct: 10,
        periodMode: "bars",
        chartWindow: null,
        barLimit: 407,
        limit: 407,
        startDate: null,
        endDate: null,
        positionSizePct: 100,
        positionSizingModel: "fixed_pct",
        riskPerTradePct: 1,
        entryConfirmationBars: 1,
        executionTiming: "next_open",
        exitMode: "tp_sl_or_opposite",
        stopLossPct: 2,
        takeProfitPct: 4,
        maxBarsInTrade: 40,
        walkforwardSplitPct: 0,
        walkforwardMode: "holdout",
        walkforwardFolds: 3,
        benchmarkEnabled: true,
      }),
      setters,
    );

    expect(calls).toContain("period:bars");
    expect(calls).toContain("limit:407");
    expect(calls).toContain("strategies");
    expect(calls).toContain("benchmark");
  });
});
