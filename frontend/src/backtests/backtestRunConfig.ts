import type { CandleCode, PeriodMode, WindowCode } from "../market/windowCandle";
import { fetchLimitFor, WINDOWS } from "../market/windowCandle";

export type BacktestFormSnapshot = {
  strategies: string[];
  initialCapital: number;
  feeBps: number;
  feeModel: "fixed_bps" | "ibkr_us_tiered";
  slippageBps: number;
  slippageModel: "fixed" | "atr_volume";
  strategyMinStrengthPct: Record<string, number>;
  consensusStrengthPct: number;
  periodMode: PeriodMode;
  chartWindow: WindowCode | null;
  barLimit: number;
  startDate: string | null;
  endDate: string | null;
  positionSizePct: number;
  positionSizingModel: "fixed_pct" | "atr_risk";
  riskPerTradePct: number;
  entryConfirmationBars: number;
  executionTiming: "signal_close" | "next_open";
  exitMode: "opposite_signal" | "tp_sl_or_opposite" | "tp_sl_only";
  stopLossPct: number;
  takeProfitPct: number;
  maxBarsInTrade: number;
  walkforwardSplitPct: number;
  walkforwardMode: "holdout" | "rolling";
  walkforwardFolds: number;
  benchmarkEnabled: boolean;
};

export type BacktestPresetLike = {
  id: string;
  name: string;
  strategies: string[];
  initialCapital: number;
  feeBps: number;
  slippageBps: number;
  strategyMinStrengthPct: Record<string, number>;
  consensusStrengthPct: number;
  positionSizePct: number;
  entryConfirmationBars: number;
  exitMode: BacktestFormSnapshot["exitMode"];
  walkforwardSplitPct: number;
  benchmarkEnabled: boolean;
  feeModel?: BacktestFormSnapshot["feeModel"];
  slippageModel?: BacktestFormSnapshot["slippageModel"];
  periodMode?: PeriodMode;
  chartWindow?: WindowCode | null;
  barLimit?: number;
  startDate?: string | null;
  endDate?: string | null;
  positionSizingModel?: BacktestFormSnapshot["positionSizingModel"];
  riskPerTradePct?: number;
  executionTiming?: BacktestFormSnapshot["executionTiming"];
  stopLossPct?: number | null;
  takeProfitPct?: number | null;
  maxBarsInTrade?: number | null;
  walkforwardMode?: BacktestFormSnapshot["walkforwardMode"];
  walkforwardFolds?: number;
  /** @deprecated legacy single threshold */
  minStrengthPct?: number;
  /** @deprecated legacy preset field */
  entryTiming?: "signal_close" | "next_open";
  /** @deprecated legacy field — use barLimit */
  limit?: number;
};

export type BacktestRunLike = {
  symbol: string;
  timeframe: string;
  strategy_names: string[];
  start_at: string | null;
  end_at: string | null;
  initial_capital: number;
  fee_bps: number;
  slippage_bps: number;
  min_signal_strength: number;
  bars_processed: number;
  result_summary: Record<string, unknown>;
};

export type ParsedRunConfig = {
  strategies: string[];
  initialCapital: number;
  feeBps: number;
  feeModel: "fixed_bps" | "ibkr_us_tiered";
  slippageBps: number;
  slippageModel: "fixed" | "atr_volume";
  strategyMinStrengthPct: Record<string, number>;
  consensusStrengthPct: number;
  minSignalStrengthPct: number;
  periodMode: PeriodMode;
  chartWindow: WindowCode | null;
  barLimit: number;
  startDate: string | null;
  endDate: string | null;
  positionSizePct: number;
  positionSizingModel: "fixed_pct" | "atr_risk";
  riskPerTradePct: number;
  entryConfirmationBars: number;
  executionTiming: "signal_close" | "next_open";
  exitMode: "opposite_signal" | "tp_sl_or_opposite" | "tp_sl_only";
  stopLossPct: number;
  takeProfitPct: number;
  maxBarsInTrade: number;
  walkforwardSplitPct: number;
  walkforwardMode: "holdout" | "rolling";
  walkforwardFolds: number;
  benchmarkEnabled: boolean;
};

const WINDOW_CODES: WindowCode[] = ["1h", "4h", "1d", "1w", "1mo", "1y", "all"];
const DEFAULT_STRENGTH_PCT = 10;

function asNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function asOptionalNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asBoolean(value: unknown, fallback: boolean): boolean {
  return typeof value === "boolean" ? value : fallback;
}

function toInputDate(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function parseCandleCode(timeframe: string): CandleCode {
  const allowed: CandleCode[] = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"];
  return allowed.includes(timeframe as CandleCode) ? (timeframe as CandleCode) : "1d";
}

function parseWindowCode(value: unknown): WindowCode | null {
  if (typeof value !== "string") {
    return null;
  }
  return WINDOW_CODES.includes(value as WindowCode) ? (value as WindowCode) : null;
}

function parsePeriodMode(value: unknown): PeriodMode | null {
  if (value === "window" || value === "date" || value === "bars") {
    return value;
  }
  return null;
}

export function inferChartWindowFromLimit(candle: CandleCode, limit: number): WindowCode {
  let best: WindowCode = "all";
  let bestDelta = Number.POSITIVE_INFINITY;
  for (const option of WINDOWS) {
    const derived = fetchLimitFor(option.code, candle);
    const delta = Math.abs(derived - limit);
    if (delta < bestDelta) {
      bestDelta = delta;
      best = option.code;
    }
  }
  return best;
}

function resolveChartWindow(
  periodMode: PeriodMode,
  storedWindow: WindowCode | null,
  candle: CandleCode,
  barLimit: number,
): WindowCode | null {
  if (periodMode !== "window") {
    return null;
  }
  return storedWindow ?? inferChartWindowFromLimit(candle, barLimit);
}

function getStoredConfig(run: BacktestRunLike): Record<string, unknown> {
  const stored =
    typeof run.result_summary.config === "object" && run.result_summary.config !== null
      ? (run.result_summary.config as Record<string, unknown>)
      : {};
  return stored;
}

export function parseRunConfig(run: BacktestRunLike): ParsedRunConfig {
  const config = getStoredConfig(run);
  const strategies = Array.isArray(config.strategies)
    ? (config.strategies as string[]).filter((item) => item.trim().length > 0)
    : [...run.strategy_names];

  const fallbackStrengthPct = Math.round(
    asNumber(config.min_signal_strength, run.min_signal_strength) * 100,
  );
  const consensusStrengthPct = Math.round(
    asNumber(config.min_consensus_strength, fallbackStrengthPct / 100) * 100,
  );

  const strategyMinStrengthPct: Record<string, number> = {};
  const rawStrengths = config.strategy_min_strengths;
  if (rawStrengths && typeof rawStrengths === "object") {
    for (const strategy of strategies) {
      const value = (rawStrengths as Record<string, unknown>)[strategy];
      strategyMinStrengthPct[strategy] =
        typeof value === "number" ? Math.round(value * 100) : fallbackStrengthPct;
    }
  } else {
    for (const strategy of strategies) {
      strategyMinStrengthPct[strategy] = fallbackStrengthPct;
    }
  }

  const barLimit = Math.round(
    asNumber(config.limit, run.bars_processed > 0 ? run.bars_processed : 2000),
  );

  const storedPeriodMode = parsePeriodMode(config.period_mode);
  const hasDates = Boolean(run.start_at && run.end_at);
  let periodMode: PeriodMode;
  if (storedPeriodMode) {
    periodMode = storedPeriodMode;
  } else if (hasDates) {
    periodMode = "date";
  } else {
    periodMode = "bars";
  }

  const chartWindow = resolveChartWindow(
    periodMode,
    parseWindowCode(config.chart_window),
    parseCandleCode(run.timeframe),
    Math.max(200, Math.min(10000, barLimit)),
  );

  const stopLoss = asOptionalNumber(config.stop_loss_pct);
  const takeProfit = asOptionalNumber(config.take_profit_pct);
  const maxBars = asOptionalNumber(config.max_bars_in_trade);

  const executionTimingRaw = config.execution_timing ?? config.entry_timing;
  const executionTiming =
    executionTimingRaw === "signal_close" || executionTimingRaw === "next_open"
      ? executionTimingRaw
      : "next_open";

  const exitModeRaw = config.exit_mode;
  const exitMode =
    exitModeRaw === "opposite_signal" ||
    exitModeRaw === "tp_sl_or_opposite" ||
    exitModeRaw === "tp_sl_only"
      ? exitModeRaw
      : "tp_sl_or_opposite";

  const feeModelRaw = config.fee_model;
  const slippageModelRaw = config.slippage_model;
  const positionSizingRaw = config.position_sizing_model;
  const walkforwardModeRaw = config.walkforward_mode;

  return {
    strategies,
    initialCapital: asNumber(config.initial_capital, run.initial_capital),
    feeBps: asNumber(config.fee_bps, run.fee_bps),
    feeModel: feeModelRaw === "ibkr_us_tiered" ? "ibkr_us_tiered" : "fixed_bps",
    slippageBps: asNumber(config.slippage_bps, run.slippage_bps),
    slippageModel: slippageModelRaw === "fixed" ? "fixed" : "atr_volume",
    strategyMinStrengthPct,
    consensusStrengthPct,
    minSignalStrengthPct: fallbackStrengthPct,
    periodMode,
    chartWindow,
    barLimit: Math.max(200, Math.min(10000, barLimit)),
    startDate: run.start_at ? toInputDate(new Date(run.start_at)) : null,
    endDate: run.end_at ? toInputDate(new Date(run.end_at)) : null,
    positionSizePct: asNumber(config.position_size_pct, 100),
    positionSizingModel: positionSizingRaw === "atr_risk" ? "atr_risk" : "fixed_pct",
    riskPerTradePct: asNumber(config.risk_per_trade_pct, 1),
    entryConfirmationBars: Math.round(asNumber(config.entry_confirmation_bars, 1)),
    executionTiming,
    exitMode,
    stopLossPct: exitMode === "opposite_signal" ? 2 : (stopLoss ?? 2),
    takeProfitPct: exitMode === "opposite_signal" ? 4 : (takeProfit ?? 4),
    maxBarsInTrade: maxBars !== null ? Math.round(maxBars) : 40,
    walkforwardSplitPct: asNumber(config.walkforward_split_pct, 0),
    walkforwardMode: walkforwardModeRaw === "rolling" ? "rolling" : "holdout",
    walkforwardFolds: Math.round(asNumber(config.walkforward_folds, 3)),
    benchmarkEnabled: asBoolean(config.benchmark_enabled, true),
  };
}

export type RunConfigFormSetters = {
  setSelectedSymbol: (symbol: string) => void;
  setCandle: (candle: CandleCode) => void;
  setChartWindow: (window: WindowCode) => void;
  setManualCandle: (manual: boolean) => void;
  setPeriodMode: (mode: PeriodMode) => void;
  setStartDate: (value: string) => void;
  setEndDate: (value: string) => void;
  setBacktestLimit: (value: number) => void;
  setActiveStrategies: (strategies: string[]) => void;
  setBacktestInitialCapital: (value: number) => void;
  setBacktestFeeBps: (value: number) => void;
  setBacktestFeeModel: (value: "fixed_bps" | "ibkr_us_tiered") => void;
  setBacktestSlippageBps: (value: number) => void;
  setBacktestSlippageModel: (value: "fixed" | "atr_volume") => void;
  setBacktestStrategyMinStrengthPct: (
    value: Record<string, number> | ((previous: Record<string, number>) => Record<string, number>),
  ) => void;
  setBacktestConsensusStrengthPct: (value: number) => void;
  setBacktestPositionSizePct: (value: number) => void;
  setBacktestPositionSizingModel: (value: "fixed_pct" | "atr_risk") => void;
  setBacktestRiskPerTradePct: (value: number) => void;
  setBacktestEntryConfirmationBars: (value: number) => void;
  setBacktestExecutionTiming: (value: "signal_close" | "next_open") => void;
  setBacktestExitMode: (value: "opposite_signal" | "tp_sl_or_opposite" | "tp_sl_only") => void;
  setBacktestStopLossPct: (value: number) => void;
  setBacktestTakeProfitPct: (value: number) => void;
  setBacktestMaxBarsInTrade: (value: number) => void;
  setBacktestWalkforwardSplitPct: (value: number) => void;
  setBacktestWalkforwardMode: (value: "holdout" | "rolling") => void;
  setBacktestWalkforwardFolds: (value: number) => void;
  setBacktestBenchmarkEnabled: (value: boolean) => void;
};

export function parsedConfigToSnapshot(parsed: ParsedRunConfig): BacktestFormSnapshot {
  return {
    strategies: [...parsed.strategies],
    initialCapital: parsed.initialCapital,
    feeBps: parsed.feeBps,
    feeModel: parsed.feeModel,
    slippageBps: parsed.slippageBps,
    slippageModel: parsed.slippageModel,
    strategyMinStrengthPct: { ...parsed.strategyMinStrengthPct },
    consensusStrengthPct: parsed.consensusStrengthPct,
    periodMode: parsed.periodMode,
    chartWindow: parsed.chartWindow,
    barLimit: parsed.barLimit,
    startDate: parsed.startDate,
    endDate: parsed.endDate,
    positionSizePct: parsed.positionSizePct,
    positionSizingModel: parsed.positionSizingModel,
    riskPerTradePct: parsed.riskPerTradePct,
    entryConfirmationBars: parsed.entryConfirmationBars,
    executionTiming: parsed.executionTiming,
    exitMode: parsed.exitMode,
    stopLossPct: parsed.stopLossPct,
    takeProfitPct: parsed.takeProfitPct,
    maxBarsInTrade: parsed.maxBarsInTrade,
    walkforwardSplitPct: parsed.walkforwardSplitPct,
    walkforwardMode: parsed.walkforwardMode,
    walkforwardFolds: parsed.walkforwardFolds,
    benchmarkEnabled: parsed.benchmarkEnabled,
  };
}

export function parsePresetConfig(preset: BacktestPresetLike): BacktestFormSnapshot {
  const legacyStrength = preset.minStrengthPct ?? preset.consensusStrengthPct ?? DEFAULT_STRENGTH_PCT;
  const consensusStrengthPct = preset.consensusStrengthPct ?? legacyStrength;
  const strategyMinStrengthPct = { ...preset.strategyMinStrengthPct };
  for (const strategy of preset.strategies) {
    if (strategyMinStrengthPct[strategy] === undefined) {
      strategyMinStrengthPct[strategy] = legacyStrength;
    }
  }

  const barLimit = Math.round(
    asNumber(preset.barLimit ?? preset.limit, 2000),
  );
  const clampedLimit = Math.max(200, Math.min(10000, barLimit));
  const periodMode = parsePeriodMode(preset.periodMode) ?? "bars";
  const chartWindow =
    periodMode === "window"
      ? preset.chartWindow ?? inferChartWindowFromLimit("1d", clampedLimit)
      : null;

  const exitMode = preset.exitMode;
  const stopLoss = preset.stopLossPct;
  const takeProfit = preset.takeProfitPct;

  return {
    strategies: [...preset.strategies],
    initialCapital: preset.initialCapital,
    feeBps: preset.feeBps,
    feeModel: preset.feeModel ?? "fixed_bps",
    slippageBps: preset.slippageBps,
    slippageModel: preset.slippageModel ?? "atr_volume",
    strategyMinStrengthPct,
    consensusStrengthPct,
    periodMode,
    chartWindow,
    barLimit: clampedLimit,
    startDate: preset.startDate ?? null,
    endDate: preset.endDate ?? null,
    positionSizePct: preset.positionSizePct,
    positionSizingModel: preset.positionSizingModel ?? "fixed_pct",
    riskPerTradePct: preset.riskPerTradePct ?? 1,
    entryConfirmationBars: preset.entryConfirmationBars,
    executionTiming: preset.executionTiming ?? preset.entryTiming ?? "next_open",
    exitMode,
    stopLossPct: exitMode === "opposite_signal" ? 2 : (stopLoss ?? 2),
    takeProfitPct: exitMode === "opposite_signal" ? 4 : (takeProfit ?? 4),
    maxBarsInTrade: preset.maxBarsInTrade ?? 40,
    walkforwardSplitPct: preset.walkforwardSplitPct,
    walkforwardMode: preset.walkforwardMode ?? "holdout",
    walkforwardFolds: preset.walkforwardFolds ?? 3,
    benchmarkEnabled: preset.benchmarkEnabled,
  };
}

export function applyFormSnapshot(
  snapshot: BacktestFormSnapshot,
  setters: RunConfigFormSetters,
  options?: { symbol?: string; timeframe?: string },
): void {
  if (options?.symbol) {
    setters.setSelectedSymbol(options.symbol);
  }
  if (options?.timeframe) {
    setters.setCandle(parseCandleCode(options.timeframe));
    setters.setManualCandle(true);
  }
  setters.setActiveStrategies([...snapshot.strategies]);
  setters.setBacktestInitialCapital(snapshot.initialCapital);
  setters.setBacktestFeeBps(snapshot.feeBps);
  setters.setBacktestFeeModel(snapshot.feeModel);
  setters.setBacktestSlippageBps(snapshot.slippageBps);
  setters.setBacktestSlippageModel(snapshot.slippageModel);
  setters.setBacktestStrategyMinStrengthPct(snapshot.strategyMinStrengthPct);
  setters.setBacktestConsensusStrengthPct(snapshot.consensusStrengthPct);
  setters.setBacktestPositionSizePct(snapshot.positionSizePct);
  setters.setBacktestPositionSizingModel(snapshot.positionSizingModel);
  setters.setBacktestRiskPerTradePct(snapshot.riskPerTradePct);
  setters.setBacktestEntryConfirmationBars(snapshot.entryConfirmationBars);
  setters.setBacktestExecutionTiming(snapshot.executionTiming);
  setters.setBacktestExitMode(snapshot.exitMode);
  setters.setBacktestStopLossPct(snapshot.stopLossPct);
  setters.setBacktestTakeProfitPct(snapshot.takeProfitPct);
  setters.setBacktestMaxBarsInTrade(snapshot.maxBarsInTrade);
  setters.setBacktestWalkforwardSplitPct(snapshot.walkforwardSplitPct);
  setters.setBacktestWalkforwardMode(snapshot.walkforwardMode);
  setters.setBacktestWalkforwardFolds(snapshot.walkforwardFolds);
  setters.setBacktestBenchmarkEnabled(snapshot.benchmarkEnabled);
  setters.setBacktestLimit(snapshot.barLimit);
  setters.setPeriodMode(snapshot.periodMode);
  if (snapshot.periodMode === "date") {
    if (snapshot.startDate) {
      setters.setStartDate(snapshot.startDate);
    }
    if (snapshot.endDate) {
      setters.setEndDate(snapshot.endDate);
    }
  } else if (snapshot.periodMode === "window" && snapshot.chartWindow) {
    setters.setChartWindow(snapshot.chartWindow);
  }
}

export function applyParsedRunConfig(
  parsed: ParsedRunConfig,
  run: BacktestRunLike,
  setters: RunConfigFormSetters,
  options?: { symbolAvailable?: boolean },
): void {
  if (options?.symbolAvailable !== false) {
    setters.setSelectedSymbol(run.symbol);
  }
  setters.setCandle(parseCandleCode(run.timeframe));
  setters.setManualCandle(true);
  applyFormSnapshot(parsedConfigToSnapshot(parsed), setters);
}

export function applyBacktestPresetConfig(
  preset: BacktestPresetLike,
  setters: RunConfigFormSetters,
): BacktestFormSnapshot {
  const snapshot = parsePresetConfig(preset);
  applyFormSnapshot(snapshot, setters);
  return snapshot;
}

export function applyBacktestRunConfig(
  run: BacktestRunLike,
  setters: RunConfigFormSetters,
  options?: { symbolAvailable?: boolean },
): ParsedRunConfig {
  const parsed = parseRunConfig(run);
  applyParsedRunConfig(parsed, run, setters, options);
  return parsed;
}

const EXIT_MODE_LABELS: Record<ParsedRunConfig["exitMode"], string> = {
  opposite_signal: "só sinal oposto",
  tp_sl_or_opposite: "TP/SL + sinal oposto",
  tp_sl_only: "só TP/SL",
};

export function summarizeAppliedRunConfig(
  run: BacktestRunLike,
  parsed: ParsedRunConfig,
  strategyLabels?: Record<string, string>,
): string[] {
  const strategyText = parsed.strategies
    .map((name) => strategyLabels?.[name] ?? name)
    .join(" · ");
  const periodText =
    parsed.periodMode === "date" && parsed.startDate && parsed.endDate
      ? `Datas ${parsed.startDate} – ${parsed.endDate}`
      : parsed.periodMode === "bars"
        ? `${parsed.barLimit} velas`
        : `Janela ${parsed.chartWindow ?? "?"}`;
  const riskText =
    parsed.exitMode === "opposite_signal"
      ? EXIT_MODE_LABELS.opposite_signal
      : `SL ${parsed.stopLossPct}% / TP ${parsed.takeProfitPct}%`;
  return [
    `${run.symbol} · ${run.timeframe} · ${strategyText}`,
    periodText,
    `Capital ${parsed.initialCapital.toLocaleString("pt-PT")} · ${riskText} · confirmação ${parsed.entryConfirmationBars} vela(s)`,
  ];
}

export { parseCandleCode, DEFAULT_STRENGTH_PCT };
