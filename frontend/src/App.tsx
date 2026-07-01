import { useEffect, useMemo, useRef, useState } from "react";
import { BacktestEquityChart, type EquityCurvePoint } from "./BacktestEquityChart";
import { GlobalMarketFilters } from "./market/GlobalMarketFilters";
import { HistoricalMarketView } from "./market/HistoricalMarketView";
import { MarketChartModeToggle, type ChartMode } from "./market/MarketChartModeToggle";
import {
  type CandleCode,
  type PeriodMode,
  type WindowCode,
  SUGGESTED_CANDLE,
  fetchLimitFor,
  isSuggestedCandle,
} from "./market/windowCandle";

import { HotMoversGrid } from "./market/HotMovers/HotMoversGrid";
import { resolveFormingBar } from "./market/formingBar";
import { findSignalsAtChartTime } from "./market/signalMarkers";
import { RealtimePage } from "./realtime/RealtimePage";
import { INDICATORS, type IndicatorId } from "./realtime/indicators";
import { buildLiveEvaluatePayload } from "./signals/liveEvaluatePayload";
import { BacktestRecommendationsPicker } from "./backtests/BacktestRecommendationsPicker";
import { fetchBarCountsByTimeframe } from "./backtests/backtestBarAvailability";
import { BacktestReuseBanner } from "./backtests/BacktestReuseBanner";
import { BacktestWorkspaceDateFilter } from "./backtests/BacktestWorkspaceDateFilter";
import { BacktestWorkspacePagination } from "./backtests/BacktestWorkspacePagination";
import { BacktestWorkspacePane } from "./backtests/BacktestWorkspacePane";
import { BacktestWorkspaceTabBar, type BacktestWorkspaceTab } from "./backtests/BacktestWorkspaceTabBar";
import { appendCreatedDateQuery, paginateItems, totalPagesFor } from "./backtests/backtestWorkspaceList";
import {
  applyBacktestRunConfig,
  applyBacktestPresetConfig,
  parseCandleCode,
  parsePresetConfig,
  summarizeAppliedRunConfig,
  type BacktestPresetLike,
  type RunConfigFormSetters,
} from "./backtests/backtestRunConfig";
import { BacktestRunComparePanel } from "./backtests/BacktestRunComparePanel";
import { formatBacktestRunLabel } from "./backtests/runCompare";
import {
  type AppliedRecommendationRecord,
  type BacktestFormSetters,
  type BacktestFormSnapshot,
  type BacktestRecommendation,
} from "./backtests/recommendationApply";
import { formatStaleBarMessage, isMarketDataStale } from "./market/dataFreshness";
import { useBars } from "./realtime/useBars";
import { useTickStream } from "./realtime/useTickStream";

type Instrument = {
  id: number;
  symbol: string;
  name: string | null;
  exchange: string | null;
  currency: string;
  followed?: boolean;
};

type ApiBar = {
  timestamp: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
};

type ViewTab = "market" | "signals" | "backtests";
type SignalDirectionFilter = "BOTH" | "BUY" | "SELL";
type SignalsSourceMode = "historical" | "live";
type ConfigTab = "data" | "signals" | "execution" | "alerts";

type SignalItem = {
  id: number;
  symbol: string;
  timeframe: string;
  strategy: string;
  direction: "BUY" | "SELL" | string;
  strength: number;
  rationale: string;
  timestamp: string;
  indicator_snapshot: Record<string, number | null>;
  source: string;
};

type StrategyContribution = {
  strategy: string;
  direction: "BUY" | "SELL" | "NEUTRAL";
  strength: number;
  signedScore: number;
  rationale: string;
  timestamp: string;
};

type AuthUser = {
  id: number;
  email: string;
  display_name: string | null;
  is_admin: boolean;
  created_at: string;
};

type StrategyCombination = {
  id: number;
  owner_user_id: number;
  owner_email: string;
  cloned_from_id: number | null;
  name: string;
  description: string | null;
  strategies: string[];
  is_shared: boolean;
  created_at: string;
  updated_at: string;
};

type BrokerConnection = {
  id: number;
  owner_user_id: number;
  broker_name: string;
  account_label: string;
  environment: string;
  connection_metadata: Record<string, string | number | boolean | null>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
};

type BacktestTrade = {
  id: number;
  direction: string;
  entry_timestamp: string;
  exit_timestamp: string;
  entry_price: number;
  exit_price: number;
  quantity: number;
  gross_pnl: number;
  fee_paid: number;
  net_pnl: number;
  return_pct: number;
  bars_held: number;
  entry_reason: string;
  exit_reason: string;
};

type BacktestLesson = {
  title: string;
  detail: string;
  priority: string;
  symbol: string;
  strategy_names: string[];
  run_id: number;
  created_at: string;
};

type BacktestRunInsight = {
  id: number;
  run_id: number;
  narrative_summary: string;
  timeline: Array<{
    step: number;
    phase: string;
    title: string;
    detail: string;
    severity: string;
  }>;
  failure_modes: Array<{
    code: string;
    title: string;
    detail: string;
    severity: string;
  }>;
  lessons: Array<{
    title: string;
    detail: string;
    priority: string;
  }>;
  recommendations: Array<{
    area: string;
    suggestion: string;
    rationale: string;
    param_hint?: string;
  }>;
  prior_runs_context: Record<string, unknown>;
  created_at: string;
};

type BacktestRun = {
  id: number;
  owner_user_id: number;
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
  trades_count: number;
  net_pnl: number;
  net_pnl_pct: number;
  win_rate: number;
  profit_factor: number;
  max_drawdown_pct: number;
  created_at: string;
  result_summary: Record<string, unknown>;
  insight_summary?: string | null;
  symbol_run_number?: number | null;
  trades?: BacktestTrade[];
  insight?: BacktestRunInsight | null;
};

type BacktestPreset = BacktestPresetLike & {
  /** @deprecated legacy field — mirrors barLimit for older presets */
  limit: number;
};

type AppliedReuseRun = {
  runId: number;
  label: string;
  summaryLines: string[];
};

const DEFAULT_BACKTEST_STRENGTH_PCT = 10;
const BACKTEST_MIN_BARS = 200;
const BACKTEST_TRADES_PAGE_SIZE = 20;
const SIGNALS_PAGE_SIZE = 10;
const BACKTEST_RUNS_PAGE_SIZE = 10;
const BACKTEST_RUNS_FETCH_LIMIT = 100;
const BACKTEST_LESSONS_PAGE_SIZE = 10;
const BACKTEST_LESSONS_FETCH_LIMIT = 100;
const BACKTEST_LESSONS_LIMIT = BACKTEST_LESSONS_FETCH_LIMIT;
const BACKTEST_RECOMMENDATIONS_LIMIT = 10;

const BACKTEST_LESSON_PRIORITY_RANK: Record<string, number> = {
  high: 0,
  medium: 1,
  low: 2,
};

function sortBacktestLessons(lessons: BacktestLesson[]): BacktestLesson[] {
  return [...lessons].sort((left, right) => {
    const leftRank = BACKTEST_LESSON_PRIORITY_RANK[left.priority.toLowerCase()] ?? 3;
    const rightRank = BACKTEST_LESSON_PRIORITY_RANK[right.priority.toLowerCase()] ?? 3;
    if (leftRank !== rightRank) {
      return leftRank - rightRank;
    }
    return new Date(right.created_at).getTime() - new Date(left.created_at).getTime();
  });
}

function isBacktestLessonRelevant(lesson: BacktestLesson, activeStrategies: string[]): boolean {
  if (activeStrategies.length === 0) {
    return false;
  }
  return activeStrategies.some((strategy) => lesson.strategy_names.includes(strategy));
}

const strengthLevelLabel = (pct: number): string => {
  if (pct <= 20) {
    return "Sensível";
  }
  if (pct <= 45) {
    return "Moderado";
  }
  if (pct <= 70) {
    return "Exigente";
  }
  return "Muito exigente";
};

const strengthLevelClass = (pct: number): string => {
  if (pct <= 20) {
    return "strength-level-low";
  }
  if (pct <= 45) {
    return "strength-level-mid";
  }
  if (pct <= 70) {
    return "strength-level-high";
  }
  return "strength-level-max";
};

const normalizeBacktestPreset = (item: BacktestPreset): BacktestPreset => {
  const snapshot = parsePresetConfig(item);
  return {
    ...item,
    ...snapshot,
    limit: snapshot.barLimit,
  };
};

const toUserFetchError = (error: unknown, fallback: string): string => {
  if (error instanceof TypeError && error.message === "Failed to fetch") {
    return "Backend inacessível ou com erro. Confirme que `npm run dev:all` está a correr e que a migration de backtests foi aplicada.";
  }
  if (error instanceof Error) {
    return error.message;
  }
  return fallback;
};

const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ??
  (import.meta.env.DEV ? "" : "http://localhost:8000");
const AUTH_TOKEN_STORAGE_KEY = "trading_auth_token";
const CONSENSUS_THRESHOLD_STORAGE_KEY = "trading_consensus_threshold_pct";
const SIGNALS_FETCH_LIMIT_STORAGE_KEY = "trading_signals_fetch_limit";
const SIGNALS_SOURCE_MODE_STORAGE_KEY = "trading_signals_source_mode";
const LIVE_SIGNALS_POLL_MS = 30_000;
const SIGNALS_CHART_OVERLAY_STORAGE_KEY = "trading_signals_chart_overlay";
const SIGNALS_CHART_OVERLAY_MAX = 100;
const BACKTEST_PRESETS_STORAGE_KEY = "trading_backtest_presets";
const SELECTED_SYMBOL_STORAGE_KEY = "trading_selected_symbol";

const readStoredSymbol = (): string => {
  const raw = localStorage.getItem(SELECTED_SYMBOL_STORAGE_KEY);
  return raw ? raw.trim().toUpperCase() : "";
};

const persistSelectedSymbol = (symbol: string): void => {
  const cleaned = symbol.trim().toUpperCase();
  if (cleaned) {
    localStorage.setItem(SELECTED_SYMBOL_STORAGE_KEY, cleaned);
  } else {
    localStorage.removeItem(SELECTED_SYMBOL_STORAGE_KEY);
  }
};

const resolveSymbolAfterInstrumentsLoad = (
  instruments: Instrument[],
  current: string,
): string => {
  const normalizedCurrent = current.trim().toUpperCase();
  if (normalizedCurrent) {
    return normalizedCurrent;
  }
  const stored = readStoredSymbol();
  if (stored && instruments.some((item) => item.symbol === stored)) {
    return stored;
  }
  return instruments.length > 0 ? instruments[0].symbol : "";
};

const readStoredNumber = (key: string, fallback: number, min: number, max: number): number => {
  const raw = localStorage.getItem(key);
  if (!raw) {
    return fallback;
  }
  const parsed = Number(raw);
  if (Number.isNaN(parsed)) {
    return fallback;
  }
  return Math.max(min, Math.min(max, parsed));
};

const readStoredBacktestPresets = (): BacktestPreset[] => {
  const raw = localStorage.getItem(BACKTEST_PRESETS_STORAGE_KEY);
  if (!raw) {
    return [];
  }
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) {
      return [];
    }
    return parsed
      .filter((item): item is BacktestPreset => Boolean(item && typeof item === "object"))
      .map((item) => normalizeBacktestPreset(item));
  } catch {
    return [];
  }
};

const STRATEGY_SUMMARY: Record<string, { title: string; summary: string }> = {
  rsi_mean_reversion: {
    title: "RSI Mean Reversion",
    summary: "Procura reversão quando RSI(14) entra em sobrevenda (<30) ou sobrecompra (>70).",
  },
  macd_crossover: {
    title: "MACD Crossover",
    summary: "Gera sinal quando a linha MACD cruza acima/abaixo da linha de sinal.",
  },
  sma_ema_crossover: {
    title: "SMA/EMA Crossover",
    summary: "Compara SMA(20) com EMA(50) para identificar mudança de tendência.",
  },
  bollinger_breakout: {
    title: "Bollinger Breakout",
    summary: "Deteta breakouts quando o fecho ultrapassa as bandas superior/inferior.",
  },
};

const STRATEGY_LABELS: Record<string, string> = Object.fromEntries(
  Object.entries(STRATEGY_SUMMARY).map(([key, { title }]) => [key, title]),
);

const formatPrice = (value: number): string =>
  value.toLocaleString("pt-PT", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 8,
  });

const formatDateLabel = (dateText: string): string =>
  new Date(dateText).toLocaleDateString("pt-PT");

const formatDateTimeLabel = (dateText: string): string =>
  new Date(dateText).toLocaleString("pt-PT");

const getSummaryNumber = (summary: Record<string, unknown>, key: string, fallback = 0): number => {
  const value = summary[key];
  return typeof value === "number" ? value : fallback;
};

const getSummaryCurve = (summary: Record<string, unknown>): EquityCurvePoint[] => {
  const value = summary.equity_curve;
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => {
      if (!item || typeof item !== "object") {
        return null;
      }
      const record = item as Record<string, unknown>;
      if (typeof record.timestamp !== "string" || typeof record.equity !== "number") {
        return null;
      }
      const point: EquityCurvePoint = {
        timestamp: record.timestamp,
        equity: record.equity,
      };
      if (typeof record.benchmark_equity === "number") {
        point.benchmark_equity = record.benchmark_equity;
      }
      return point;
    })
    .filter((item): item is EquityCurvePoint => item !== null);
};

type WalkforwardMetrics = {
  bars_processed: number;
  trades_count: number;
  net_pnl_pct: number;
  win_rate: number;
  profit_factor: number;
  max_drawdown_pct: number;
};

const getWalkforwardMetrics = (value: unknown): WalkforwardMetrics | null => {
  if (!value || typeof value !== "object") {
    return null;
  }
  const record = value as Record<string, unknown>;
  const readNumber = (key: string) => (typeof record[key] === "number" ? (record[key] as number) : null);
  const barsProcessed = readNumber("bars_processed");
  const tradesCount = readNumber("trades_count");
  const netPnlPct = readNumber("net_pnl_pct");
  const winRate = readNumber("win_rate");
  const profitFactor = readNumber("profit_factor");
  const maxDrawdownPct = readNumber("max_drawdown_pct");
  if (
    barsProcessed === null ||
    tradesCount === null ||
    netPnlPct === null ||
    winRate === null ||
    profitFactor === null ||
    maxDrawdownPct === null
  ) {
    return null;
  }
  return {
    bars_processed: barsProcessed,
    trades_count: tradesCount,
    net_pnl_pct: netPnlPct,
    win_rate: winRate,
    profit_factor: profitFactor,
    max_drawdown_pct: maxDrawdownPct,
  };
};

const formatPct = (value: number, digits = 2): string => `${(value * 100).toFixed(digits)}%`;

const formatExitModeLabel = (mode: string): string => {
  if (mode === "opposite_signal") {
    return "Só sinal oposto";
  }
  if (mode === "tp_sl_or_opposite") {
    return "TP/SL + sinal oposto";
  }
  if (mode === "tp_sl_only") {
    return "Só TP/SL";
  }
  return mode;
};

const formatExecutionTimingLabel = (timing: string): string => {
  if (timing === "next_open") {
    return "Abertura da vela seguinte (entrada e saída)";
  }
  if (timing === "signal_close") {
    return "Fecho da vela do sinal";
  }
  return timing;
};

const formatPositionSizingLabel = (model: string): string => {
  if (model === "atr_risk") {
    return "Risco por trade (ATR/SL)";
  }
  if (model === "fixed_pct") {
    return "% fixo do capital";
  }
  return model;
};

const formatSlippageModelLabel = (model: string): string => {
  if (model === "atr_volume") {
    return "Dinâmico (ATR + volume)";
  }
  if (model === "fixed") {
    return "Fixo";
  }
  return model;
};

const formatFeeModelLabel = (model: string): string => {
  if (model === "ibkr_us_tiered") {
    return "IBKR US tiered";
  }
  if (model === "fixed_bps") {
    return "Bps fixos";
  }
  return model;
};

const formatWalkforwardModeLabel = (mode: string): string => {
  if (mode === "rolling") {
    return "Rolling (vários blocos OOS)";
  }
  if (mode === "holdout") {
    return "Holdout único";
  }
  return mode;
};

const formatStrengthPct = (value: unknown): string =>
  typeof value === "number" ? `${Math.round(value * 100)}%` : "-";

const getRunConfigSnapshot = (run: BacktestRun): Record<string, unknown> => {
  const stored =
    typeof run.result_summary.config === "object" && run.result_summary.config !== null
      ? (run.result_summary.config as Record<string, unknown>)
      : {};
  return {
    ...stored,
    strategies: stored.strategies ?? run.strategy_names,
    fee_bps: stored.fee_bps ?? run.fee_bps,
    slippage_bps: stored.slippage_bps ?? run.slippage_bps,
    initial_capital: stored.initial_capital ?? run.initial_capital,
    min_consensus_strength: stored.min_consensus_strength ?? run.min_signal_strength,
  };
};

const toSignedScore = (direction: string, strength: number): number => {
  if (direction === "BUY") {
    return strength;
  }
  if (direction === "SELL") {
    return -strength;
  }
  return 0;
};

const toInputDate = (date: Date): string => date.toISOString().slice(0, 10);

function App() {
  const [authToken, setAuthToken] = useState<string>(() => localStorage.getItem(AUTH_TOKEN_STORAGE_KEY) ?? "");
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null);
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [showAuthPanel, setShowAuthPanel] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [authLoading, setAuthLoading] = useState(false);
  const [authChecking, setAuthChecking] = useState(false);

  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<string>(() => readStoredSymbol());
  const [candle, setCandle] = useState<CandleCode>("1d");
  const [chartWindow, setChartWindow] = useState<WindowCode>("1y");
  const [manualCandle, setManualCandle] = useState(false);
  const [periodMode, setPeriodMode] = useState<PeriodMode>("window");
  const selectedTimeframe = candle;
  const barLimit = useMemo(() => fetchLimitFor(chartWindow, candle), [chartWindow, candle]);
  const [activeTab, setActiveTab] = useState<ViewTab>("market");
  const [chartMode, setChartMode] = useState<ChartMode>("historico");
  const [showConfigPanel, setShowConfigPanel] = useState(false);
  const [activeConfigTab, setActiveConfigTab] = useState<ConfigTab>("signals");
  const [startDate, setStartDate] = useState<string>(
    toInputDate(new Date(Date.now() - 365 * 24 * 60 * 60 * 1000)),
  );
  const [endDate, setEndDate] = useState<string>(toInputDate(new Date()));
  const [bars, setBars] = useState<ApiBar[]>([]);
  const [availableStrategies, setAvailableStrategies] = useState<string[]>([]);
  const [activeStrategies, setActiveStrategies] = useState<string[]>([]);
  const [signals, setSignals] = useState<SignalItem[]>([]);
  const [consensusSignals, setConsensusSignals] = useState<SignalItem[]>([]);
  const [signalsLoading, setSignalsLoading] = useState(false);
  const [signalsGenerating, setSignalsGenerating] = useState(false);
  const [signalsError, setSignalsError] = useState<string | null>(null);
  const [signalDirectionFilter, setSignalDirectionFilter] = useState<SignalDirectionFilter>("BOTH");
  const [signalMinStrengthPct, setSignalMinStrengthPct] = useState<number>(0);
  const [consensusThresholdPct, setConsensusThresholdPct] = useState<number>(() =>
    readStoredNumber(CONSENSUS_THRESHOLD_STORAGE_KEY, 15, 0, 100),
  );
  const [signalsFetchLimit, setSignalsFetchLimit] = useState<number>(() =>
    readStoredNumber(SIGNALS_FETCH_LIMIT_STORAGE_KEY, 500, 50, 2000),
  );
  const [signalsSourceMode, setSignalsSourceMode] = useState<SignalsSourceMode>(() => {
    const stored = localStorage.getItem(SIGNALS_SOURCE_MODE_STORAGE_KEY);
    return stored === "live" ? "live" : "historical";
  });
  const [liveSignalIsForming, setLiveSignalIsForming] = useState(false);
  const [pinnedSignalsOnChart, setPinnedSignalsOnChart] = useState<SignalItem[]>([]);
  const [signalsChartOverlayEnabled, setSignalsChartOverlayEnabled] = useState<boolean>(
    () => localStorage.getItem(SIGNALS_CHART_OVERLAY_STORAGE_KEY) === "true",
  );
  const [selectedChartSignal, setSelectedChartSignal] = useState<SignalItem | null>(null);
  const [chartSignalMatches, setChartSignalMatches] = useState<SignalItem[]>([]);
  const [signalsRefreshToken, setSignalsRefreshToken] = useState(0);
  const [signalsPage, setSignalsPage] = useState(1);
  const [savedCombinations, setSavedCombinations] = useState<StrategyCombination[]>([]);
  const [newCombinationName, setNewCombinationName] = useState("");
  const [newCombinationDescription, setNewCombinationDescription] = useState("");
  const [combinationError, setCombinationError] = useState<string | null>(null);
  const [brokerConnections, setBrokerConnections] = useState<BrokerConnection[]>([]);
  const [brokerConnectionsLoading, setBrokerConnectionsLoading] = useState(false);
  const [brokerConnectionsError, setBrokerConnectionsError] = useState<string | null>(null);
  const [brokerRefreshToken, setBrokerRefreshToken] = useState(0);
  const [newBrokerName, setNewBrokerName] = useState("Binance");
  const [newBrokerLabel, setNewBrokerLabel] = useState("");
  const [newBrokerEnvironment, setNewBrokerEnvironment] = useState("paper");
  const [newBrokerMetadataJson, setNewBrokerMetadataJson] = useState("{}");
  const [brokerFormError, setBrokerFormError] = useState<string | null>(null);
  const [backtestInitialCapital, setBacktestInitialCapital] = useState<number>(10000);
  const [backtestFeeBps, setBacktestFeeBps] = useState<number>(5);
  const [backtestFeeModel, setBacktestFeeModel] = useState<"fixed_bps" | "ibkr_us_tiered">("fixed_bps");
  const [backtestSlippageBps, setBacktestSlippageBps] = useState<number>(2);
  const [backtestSlippageModel, setBacktestSlippageModel] = useState<"fixed" | "atr_volume">("atr_volume");
  const [backtestStrategyMinStrengthPct, setBacktestStrategyMinStrengthPct] = useState<
    Record<string, number>
  >({});
  const [backtestConsensusStrengthPct, setBacktestConsensusStrengthPct] = useState<number>(
    DEFAULT_BACKTEST_STRENGTH_PCT,
  );
  const [backtestLimit, setBacktestLimit] = useState<number>(2000);
  const [backtestPositionSizePct, setBacktestPositionSizePct] = useState<number>(100);
  const [backtestPositionSizingModel, setBacktestPositionSizingModel] = useState<
    "fixed_pct" | "atr_risk"
  >("fixed_pct");
  const [backtestRiskPerTradePct, setBacktestRiskPerTradePct] = useState<number>(1);
  const [backtestEntryConfirmationBars, setBacktestEntryConfirmationBars] = useState<number>(1);
  const [backtestExecutionTiming, setBacktestExecutionTiming] = useState<"signal_close" | "next_open">(
    "next_open",
  );
  const [backtestExitMode, setBacktestExitMode] = useState<
    "opposite_signal" | "tp_sl_or_opposite" | "tp_sl_only"
  >("tp_sl_or_opposite");
  const [backtestStopLossPct, setBacktestStopLossPct] = useState<number>(2);
  const [backtestTakeProfitPct, setBacktestTakeProfitPct] = useState<number>(4);
  const [backtestMaxBarsInTrade, setBacktestMaxBarsInTrade] = useState<number>(40);
  const [backtestWalkforwardSplitPct, setBacktestWalkforwardSplitPct] = useState<number>(0);
  const [backtestWalkforwardMode, setBacktestWalkforwardMode] = useState<"holdout" | "rolling">("holdout");
  const [backtestWalkforwardFolds, setBacktestWalkforwardFolds] = useState<number>(3);
  const [backtestBenchmarkEnabled, setBacktestBenchmarkEnabled] = useState(true);
  const [backtestPresets, setBacktestPresets] = useState<BacktestPreset[]>(() => readStoredBacktestPresets());
  const [backtestPresetName, setBacktestPresetName] = useState("");
  const [backtestCompareRunIds, setBacktestCompareRunIds] = useState<number[]>([]);
  const [backtestRuns, setBacktestRuns] = useState<BacktestRun[]>([]);
  const [backtestSelectedRun, setBacktestSelectedRun] = useState<BacktestRun | null>(null);
  const [backtestLoading, setBacktestLoading] = useState(false);
  const [backtestRunning, setBacktestRunning] = useState(false);
  const [backtestError, setBacktestError] = useState<string | null>(null);
  const [backtestRefreshToken, setBacktestRefreshToken] = useState(0);
  const [backtestLessons, setBacktestLessons] = useState<BacktestLesson[]>([]);
  const [backtestLessonsLoading, setBacktestLessonsLoading] = useState(false);
  const [backtestRecommendations, setBacktestRecommendations] = useState<BacktestRecommendation[]>(
    [],
  );
  const [backtestRecommendationsLoading, setBacktestRecommendationsLoading] = useState(false);
  const [appliedRecommendations, setAppliedRecommendations] = useState<AppliedRecommendationRecord[]>(
    [],
  );
  const [backtestRunsPage, setBacktestRunsPage] = useState(1);
  const [backtestLessonsPage, setBacktestLessonsPage] = useState(1);
  const [workspaceCreatedFrom, setWorkspaceCreatedFrom] = useState("");
  const [workspaceCreatedTo, setWorkspaceCreatedTo] = useState("");
  const [marketDataRefreshToken, setMarketDataRefreshToken] = useState(0);
  const [barCountsByTimeframe, setBarCountsByTimeframe] = useState<Record<string, number>>({});
  const [demoDataLoading, setDemoDataLoading] = useState(false);
  const [backtestTradesOnChartRunId, setBacktestTradesOnChartRunId] = useState<number | null>(null);
  const [backtestTradesOnChart, setBacktestTradesOnChart] = useState<BacktestTrade[]>([]);
  const [backtestTradesPage, setBacktestTradesPage] = useState(1);
  const [appliedReuseRun, setAppliedReuseRun] = useState<AppliedReuseRun | null>(null);
  const [backtestWorkspaceTab, setBacktestWorkspaceTab] = useState<BacktestWorkspaceTab>("results");
  const reuseBannerRef = useRef<HTMLElement>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeIndicators, setActiveIndicators] = useState<ReadonlySet<IndicatorId>>(
    () => new Set(INDICATORS.filter((descriptor) => descriptor.defaultOn).map((descriptor) => descriptor.id)),
  );

  const backtestRunConfigSetters = useMemo<RunConfigFormSetters>(
    () => ({
      setSelectedSymbol,
      setCandle,
      setChartWindow,
      setManualCandle,
      setPeriodMode,
      setStartDate,
      setEndDate,
      setBacktestLimit,
      setActiveStrategies,
      setBacktestInitialCapital,
      setBacktestFeeBps,
      setBacktestFeeModel,
      setBacktestSlippageBps,
      setBacktestSlippageModel,
      setBacktestStrategyMinStrengthPct,
      setBacktestConsensusStrengthPct,
      setBacktestPositionSizePct,
      setBacktestPositionSizingModel,
      setBacktestRiskPerTradePct,
      setBacktestEntryConfirmationBars,
      setBacktestExecutionTiming,
      setBacktestExitMode,
      setBacktestStopLossPct,
      setBacktestTakeProfitPct,
      setBacktestMaxBarsInTrade,
      setBacktestWalkforwardSplitPct,
      setBacktestWalkforwardMode,
      setBacktestWalkforwardFolds,
      setBacktestBenchmarkEnabled,
    }),
    [],
  );

  const isDateFilterIncomplete = periodMode === "date" && (!startDate || !endDate);
  const isDateRangeInvalid = periodMode === "date" && !isDateFilterIncomplete && startDate > endDate;
  const hasDateFilterError = isDateFilterIncomplete || isDateRangeInvalid;

  const buildMarketQueryParams = (): URLSearchParams => {
    const query = new URLSearchParams({
      symbol: selectedSymbol,
      timeframe: selectedTimeframe,
    });

    if (periodMode === "window") {
      query.set("limit", String(barLimit));
    } else if (periodMode === "bars") {
      query.set("limit", String(backtestLimit));
    } else {
      query.set("start", `${startDate}T00:00:00Z`);
      query.set("end", `${endDate}T23:59:59Z`);
    }
    return query;
  };

  const handleMarketWindow = (next: WindowCode) => {
    setChartWindow(next);
    if (!manualCandle) {
      setCandle(SUGGESTED_CANDLE[next]);
    }
  };

  const handleMarketCandle = (next: CandleCode) => {
    setCandle(next);
    setManualCandle(!isSuggestedCandle(chartWindow, next));
  };

  useEffect(() => {
    localStorage.setItem(CONSENSUS_THRESHOLD_STORAGE_KEY, String(consensusThresholdPct));
  }, [consensusThresholdPct]);

  useEffect(() => {
    localStorage.setItem(SIGNALS_FETCH_LIMIT_STORAGE_KEY, String(signalsFetchLimit));
  }, [signalsFetchLimit]);

  useEffect(() => {
    localStorage.setItem(SIGNALS_SOURCE_MODE_STORAGE_KEY, signalsSourceMode);
  }, [signalsSourceMode]);

  useEffect(() => {
    localStorage.setItem(SIGNALS_CHART_OVERLAY_STORAGE_KEY, String(signalsChartOverlayEnabled));
  }, [signalsChartOverlayEnabled]);

  const chartSignals = useMemo(() => {
    if (signalsChartOverlayEnabled) {
      return signals.slice(0, SIGNALS_CHART_OVERLAY_MAX);
    }
    return pinnedSignalsOnChart;
  }, [signalsChartOverlayEnabled, signals, pinnedSignalsOnChart]);

  useEffect(() => {
    localStorage.setItem(BACKTEST_PRESETS_STORAGE_KEY, JSON.stringify(backtestPresets));
  }, [backtestPresets]);

  const buildSignalGeneratePayload = (strategy: string): Record<string, string | number> => {
    const payload: Record<string, string | number> = {
      symbol: selectedSymbol,
      timeframe: selectedTimeframe,
      strategy,
    };
    if (periodMode === "window") {
      payload.limit = barLimit;
    } else {
      payload.start = `${startDate}T00:00:00Z`;
      payload.end = `${endDate}T23:59:59Z`;
      payload.limit = 5000;
    }
    return payload;
  };

  const isAuthenticated = Boolean(authToken && currentUser);

  const isLiveSignals = activeTab === "signals" && signalsSourceMode === "live";
  const isLiveChart = activeTab === "market" && chartMode === "aovivo";
  const useLiveStream = isAuthenticated && Boolean(selectedSymbol) && (isLiveChart || isLiveSignals);
  const liveBarsLimit =
    periodMode === "window" ? barLimit : periodMode === "bars" ? backtestLimit : 5000;

  const { tick, indices, status: streamStatus, error: streamError } = useTickStream(
    API_BASE_URL,
    isAuthenticated ? authToken : "",
    selectedSymbol,
    useLiveStream,
  );

  const { bars: liveSignalQuotes } = useBars(
    API_BASE_URL,
    authToken,
    selectedSymbol,
    selectedTimeframe,
    chartWindow,
    liveBarsLimit,
    20_000,
    isLiveSignals,
  );

  const [marketNowMs, setMarketNowMs] = useState(() => Date.now());
  useEffect(() => {
    const timer = globalThis.setInterval(() => setMarketNowMs(Date.now()), 1000);
    return () => globalThis.clearInterval(timer);
  }, []);

  const liveSignalForming = useMemo(
    () => {
      if (!isLiveSignals || liveSignalQuotes.length === 0) {
        return { forming: null, isLiveForming: false };
      }
      const lastQuote = liveSignalQuotes[liveSignalQuotes.length - 1];
      return resolveFormingBar(lastQuote, candle, tick, marketNowMs);
    },
    [isLiveSignals, liveSignalQuotes, candle, tick, marketNowMs],
  );

  const followedSymbols = useMemo(() => {
    const set = new Set<string>();
    for (const instrument of instruments) {
      if (instrument.followed !== false) set.add(instrument.symbol);
    }
    if (selectedSymbol) {
      set.add(selectedSymbol);
    }
    return Array.from(set).sort();
  }, [instruments, selectedSymbol]);

  const isFollowingSelected = useMemo(
    () => instruments.some((i) => i.symbol === selectedSymbol && i.followed !== false),
    [instruments, selectedSymbol],
  );

  const lastBarMs = useMemo(() => {
    const last = bars[bars.length - 1];
    if (!last?.timestamp) {
      return null;
    }
    const iso = /[zZ]$|[+-]\d\d:?\d\d$/.test(last.timestamp) ? last.timestamp : `${last.timestamp}Z`;
    const parsed = Date.parse(iso);
    return Number.isNaN(parsed) ? null : parsed;
  }, [bars]);

  const liveSignalsDataStale = useMemo(
    () => signalsSourceMode === "live" && isMarketDataStale(lastBarMs, candle),
    [signalsSourceMode, lastBarMs, candle],
  );

  const logout = () => {
    localStorage.removeItem(AUTH_TOKEN_STORAGE_KEY);
    setAuthToken("");
    setCurrentUser(null);
    setSavedCombinations([]);
    setBrokerConnections([]);
    setShowAuthPanel(false);
  };

  const parseApiError = (payload: unknown, fallback: string): string => {
    if (!payload || typeof payload !== "object") {
      return fallback;
    }
    const detail = (payload as { detail?: unknown }).detail;
    if (typeof detail === "string" && detail.trim().length > 0) {
      return detail;
    }
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0];
      if (first && typeof first === "object") {
        const msg = (first as { msg?: unknown }).msg;
        if (typeof msg === "string" && msg.trim().length > 0) {
          return msg;
        }
      }
      if (typeof first === "string" && first.trim().length > 0) {
        return first;
      }
    }
    return fallback;
  };

  useEffect(() => {
    persistSelectedSymbol(selectedSymbol);
  }, [selectedSymbol]);

  useEffect(() => {
    if (!isAuthenticated) {
      setInstruments([]);
      setSelectedSymbol("");
      return;
    }

    const loadInstruments = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch(`${API_BASE_URL}/market-data/instruments`, {
          headers: { Authorization: `Bearer ${authToken}` },
        });
        if (!response.ok) {
          throw new Error("Falha ao carregar instrumentos.");
        }

        const payload = (await response.json()) as Instrument[];
        setInstruments(payload);
        setSelectedSymbol((current) => resolveSymbolAfterInstrumentsLoad(payload, current));
      } catch (loadError) {
        setError(toUserFetchError(loadError, "Erro inesperado ao carregar instrumentos."));
      } finally {
        setLoading(false);
      }
    };

    loadInstruments();
  }, [isAuthenticated, authToken, marketDataRefreshToken]);

  useEffect(() => {
    if (!isAuthenticated) {
      setAvailableStrategies([]);
      setActiveStrategies([]);
      return;
    }

    const loadStrategies = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/signals/strategies`, {
          headers: { Authorization: `Bearer ${authToken}` },
        });
        if (!response.ok) {
          throw new Error("Falha ao carregar estratégias.");
        }
        const payload = (await response.json()) as string[];
        setAvailableStrategies(payload);
        setActiveStrategies((current) => {
          if (current.length > 0) {
            return current;
          }
          return payload.length > 0 ? [payload[0]] : [];
        });
      } catch {
        setAvailableStrategies([]);
        setActiveStrategies([]);
      }
    };

    loadStrategies();
  }, [isAuthenticated, authToken]);

  useEffect(() => {
    setBacktestTradesPage(1);
  }, [backtestSelectedRun?.id]);

  useEffect(() => {
    if (!authToken) {
      setCurrentUser(null);
      setSavedCombinations([]);
      setAuthChecking(false);
      return;
    }

    const loadMe = async () => {
      setAuthChecking(true);
      try {
        const response = await fetch(`${API_BASE_URL}/auth/me`, {
          headers: { Authorization: `Bearer ${authToken}` },
        });
        if (!response.ok) {
          throw new Error("Sessão inválida.");
        }
        const payload = (await response.json()) as AuthUser;
        setCurrentUser(payload);
      } catch {
        setAuthError("Sessão expirada. Volte a iniciar sessão.");
        logout();
      } finally {
        setAuthChecking(false);
      }
    };

    loadMe();
  }, [authToken]);

  useEffect(() => {
    if (!isAuthenticated) {
      return;
    }

    const loadCombinations = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/strategy-combinations`, {
          headers: { Authorization: `Bearer ${authToken}` },
        });
        if (!response.ok) {
          throw new Error("Falha ao carregar combinações.");
        }
        setSavedCombinations((await response.json()) as StrategyCombination[]);
      } catch {
        setSavedCombinations([]);
      }
    };

    loadCombinations();
  }, [authToken, isAuthenticated, signalsRefreshToken]);

  useEffect(() => {
    if (!isAuthenticated) {
      setBrokerConnections([]);
      return;
    }

    const loadBrokerConnections = async () => {
      setBrokerConnectionsLoading(true);
      setBrokerConnectionsError(null);
      try {
        const response = await fetch(`${API_BASE_URL}/broker-connections`, {
          headers: { Authorization: `Bearer ${authToken}` },
        });
        if (!response.ok) {
          throw new Error("Falha ao carregar ligações de broker.");
        }
        setBrokerConnections((await response.json()) as BrokerConnection[]);
      } catch (loadError) {
        const message =
          loadError instanceof Error ? loadError.message : "Erro inesperado ao carregar brokers.";
        setBrokerConnectionsError(message);
      } finally {
        setBrokerConnectionsLoading(false);
      }
    };

    loadBrokerConnections();
  }, [authToken, isAuthenticated, brokerRefreshToken]);

  useEffect(() => {
    if (!isAuthenticated) {
      setBacktestRuns([]);
      setBacktestSelectedRun(null);
      return;
    }

    const loadBacktests = async () => {
      setBacktestLoading(true);
      setBacktestError(null);
      try {
        const query = new URLSearchParams({ limit: String(BACKTEST_RUNS_FETCH_LIMIT) });
        if (selectedSymbol) {
          query.set("symbol", selectedSymbol);
          query.set("timeframe", selectedTimeframe);
        }
        if (!workspaceCreatedFrom || !workspaceCreatedTo || workspaceCreatedFrom <= workspaceCreatedTo) {
          appendCreatedDateQuery(query, workspaceCreatedFrom, workspaceCreatedTo);
        }
        const response = await fetch(`${API_BASE_URL}/backtests?${query.toString()}`, {
          headers: { Authorization: `Bearer ${authToken}` },
        });
        if (!response.ok) {
          throw new Error("Falha ao carregar backtests.");
        }
        const payload = (await response.json()) as BacktestRun[];
        setBacktestRuns(payload);
        setBacktestCompareRunIds((previous) =>
          previous.filter((id) => payload.some((run) => run.id === id)).slice(0, 2),
        );
      } catch (loadError) {
        setBacktestError(toUserFetchError(loadError, "Erro inesperado ao carregar backtests."));
      } finally {
        setBacktestLoading(false);
      }
    };

    loadBacktests();
  }, [
    authToken,
    isAuthenticated,
    backtestRefreshToken,
    selectedSymbol,
    selectedTimeframe,
    workspaceCreatedFrom,
    workspaceCreatedTo,
  ]);

  useEffect(() => {
    if (!isAuthenticated || !authToken || !selectedSymbol) {
      setBacktestLessons([]);
      return;
    }

    let cancelled = false;
    const loadLessons = async () => {
      setBacktestLessonsLoading(true);
      try {
        const query = new URLSearchParams({
          symbol: selectedSymbol,
          limit: String(BACKTEST_LESSONS_FETCH_LIMIT),
        });
        if (!workspaceCreatedFrom || !workspaceCreatedTo || workspaceCreatedFrom <= workspaceCreatedTo) {
          appendCreatedDateQuery(query, workspaceCreatedFrom, workspaceCreatedTo);
        }
        const response = await fetch(`${API_BASE_URL}/backtests/lessons?${query.toString()}`, {
          headers: { Authorization: `Bearer ${authToken}` },
        });
        if (!response.ok) {
          throw new Error("Falha ao carregar lições.");
        }
        if (!cancelled) {
          setBacktestLessons((await response.json()) as BacktestLesson[]);
        }
      } catch {
        if (!cancelled) {
          setBacktestLessons([]);
        }
      } finally {
        if (!cancelled) {
          setBacktestLessonsLoading(false);
        }
      }
    };

    void loadLessons();
    return () => {
      cancelled = true;
    };
  }, [
    authToken,
    isAuthenticated,
    selectedSymbol,
    backtestRefreshToken,
    workspaceCreatedFrom,
    workspaceCreatedTo,
  ]);

  useEffect(() => {
    setBacktestRunsPage(1);
    setBacktestLessonsPage(1);
  }, [workspaceCreatedFrom, workspaceCreatedTo, selectedSymbol, selectedTimeframe]);

  useEffect(() => {
    if (!isAuthenticated || !authToken || !selectedSymbol) {
      setBacktestRecommendations([]);
      return;
    }

    let cancelled = false;
    const loadRecommendations = async () => {
      setBacktestRecommendationsLoading(true);
      try {
        const query = new URLSearchParams({
          symbol: selectedSymbol,
          limit: String(BACKTEST_RECOMMENDATIONS_LIMIT),
        });
        const response = await fetch(`${API_BASE_URL}/backtests/recommendations?${query.toString()}`, {
          headers: { Authorization: `Bearer ${authToken}` },
        });
        if (!response.ok) {
          throw new Error("Falha ao carregar recomendações.");
        }
        if (!cancelled) {
          setBacktestRecommendations((await response.json()) as BacktestRecommendation[]);
        }
      } catch {
        if (!cancelled) {
          setBacktestRecommendations([]);
        }
      } finally {
        if (!cancelled) {
          setBacktestRecommendationsLoading(false);
        }
      }
    };

    void loadRecommendations();
    return () => {
      cancelled = true;
    };
  }, [authToken, isAuthenticated, selectedSymbol, backtestRefreshToken]);

  const sortedBacktestLessons = useMemo(
    () => sortBacktestLessons(backtestLessons),
    [backtestLessons],
  );

  const backtestFormSnapshot = useMemo(
    (): BacktestFormSnapshot => ({
      exitMode: backtestExitMode,
      stopLossPct: backtestStopLossPct,
      takeProfitPct: backtestTakeProfitPct,
      consensusStrengthPct: backtestConsensusStrengthPct,
      entryConfirmationBars: backtestEntryConfirmationBars,
      activeStrategies: [...activeStrategies],
      strategyMinStrengthPct: { ...backtestStrategyMinStrengthPct },
      timeframe: selectedTimeframe,
    }),
    [
      backtestExitMode,
      backtestStopLossPct,
      backtestTakeProfitPct,
      backtestConsensusStrengthPct,
      backtestEntryConfirmationBars,
      activeStrategies,
      backtestStrategyMinStrengthPct,
      selectedTimeframe,
    ],
  );

  const pendingFormChangesSummary = useMemo(
    () => Array.from(new Set(appliedRecommendations.flatMap((record) => record.previews))),
    [appliedRecommendations],
  );

  const backtestWorkspaceTabItems = useMemo(
    () => [
      {
        id: "results" as const,
        label: "Resultados",
        badge: backtestRuns.length,
      },
      {
        id: "recommendations" as const,
        label: "Recomendações",
        badge: backtestRecommendations.length,
        emphasis: pendingFormChangesSummary.length > 0,
      },
      { id: "data" as const, label: "Dados" },
      {
        id: "presets" as const,
        label: "Presets",
        badge: backtestPresets.length,
      },
      {
        id: "lessons" as const,
        label: "Lições",
        badge: sortedBacktestLessons.length,
      },
    ],
    [
      backtestRuns.length,
      backtestRecommendations.length,
      pendingFormChangesSummary.length,
      backtestPresets.length,
      sortedBacktestLessons.length,
    ],
  );

  const fulfilledRecommendationsCount = appliedRecommendations.length;

  const recommendationSourceRunLabel = useMemo(() => {
    if (backtestRecommendations.length === 0) {
      return null;
    }
    const latestRunId = Math.max(...backtestRecommendations.map((item) => item.run_id));
    const run = backtestRuns.find((item) => item.id === latestRunId);
    return run ? formatBacktestRunLabel(run) : null;
  }, [backtestRecommendations, backtestRuns]);

  const latestSymbolBacktestRun = useMemo(() => {
    const run = backtestRuns.find((item) => item.symbol === selectedSymbol);
    if (!run) {
      return null;
    }
    return {
      trades_count: run.trades_count,
      net_pnl_pct: run.net_pnl_pct,
      profit_factor: run.profit_factor,
    };
  }, [backtestRuns, selectedSymbol]);

  const recommendationBarCounts = useMemo(
    () => ({
      ...barCountsByTimeframe,
      [selectedTimeframe]: Math.max(barCountsByTimeframe[selectedTimeframe] ?? 0, bars.length),
    }),
    [barCountsByTimeframe, selectedTimeframe, bars.length],
  );

  useEffect(() => {
    if (!isAuthenticated || !authToken || !selectedSymbol) {
      setBarCountsByTimeframe({});
      return;
    }
    let cancelled = false;
    void fetchBarCountsByTimeframe(API_BASE_URL, authToken, selectedSymbol).then((counts) => {
      if (!cancelled) {
        setBarCountsByTimeframe(counts);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated, authToken, selectedSymbol, marketDataRefreshToken]);

  useEffect(() => {
    setAppliedRecommendations([]);
  }, [selectedSymbol]);

  const backtestRunsTotalPages = Math.max(1, Math.ceil(backtestRuns.length / BACKTEST_RUNS_PAGE_SIZE));

  useEffect(() => {
    setBacktestRunsPage(1);
  }, [backtestRuns]);

  useEffect(() => {
    if (backtestRunsPage > backtestRunsTotalPages) {
      setBacktestRunsPage(backtestRunsTotalPages);
    }
  }, [backtestRunsPage, backtestRunsTotalPages]);

  const paginatedBacktestRuns = useMemo(
    () =>
      backtestRuns.slice(
        (backtestRunsPage - 1) * BACKTEST_RUNS_PAGE_SIZE,
        backtestRunsPage * BACKTEST_RUNS_PAGE_SIZE,
      ),
    [backtestRuns, backtestRunsPage],
  );

  const backtestLessonsTotalPages = totalPagesFor(
    sortedBacktestLessons.length,
    BACKTEST_LESSONS_PAGE_SIZE,
  );

  const paginatedBacktestLessons = useMemo(
    () => paginateItems(sortedBacktestLessons, backtestLessonsPage, BACKTEST_LESSONS_PAGE_SIZE),
    [sortedBacktestLessons, backtestLessonsPage],
  );

  const workspaceDateFilterInvalid = Boolean(
    workspaceCreatedFrom && workspaceCreatedTo && workspaceCreatedFrom > workspaceCreatedTo,
  );

  const clearWorkspaceDateFilter = () => {
    setWorkspaceCreatedFrom("");
    setWorkspaceCreatedTo("");
  };

  const workspaceDateToolbar = (
    <BacktestWorkspaceDateFilter
      from={workspaceCreatedFrom}
      to={workspaceCreatedTo}
      onFromChange={setWorkspaceCreatedFrom}
      onToChange={setWorkspaceCreatedTo}
      onClear={clearWorkspaceDateFilter}
    />
  );

  useEffect(() => {
    if (backtestLessonsPage > backtestLessonsTotalPages) {
      setBacktestLessonsPage(backtestLessonsTotalPages);
    }
  }, [backtestLessonsPage, backtestLessonsTotalPages]);

  useEffect(() => {
    setBacktestTradesPage(1);
  }, [backtestSelectedRun?.id]);

  useEffect(() => {
    if (!selectedSymbol) {
      setBars([]);
      return;
    }
    if (hasDateFilterError) {
      setBars([]);
      return;
    }

    const loadBars = async () => {
      setLoading(true);
      setError(null);
      try {
        const query = buildMarketQueryParams();
        const response = await fetch(`${API_BASE_URL}/market-data/bars?${query.toString()}`, {
          headers: { Authorization: `Bearer ${authToken}` },
        });
        if (!response.ok) {
          throw new Error("Falha ao carregar velas.");
        }
        setBars((await response.json()) as ApiBar[]);
      } catch (loadError) {
        setError(toUserFetchError(loadError, "Erro inesperado ao carregar velas."));
      } finally {
        setLoading(false);
      }
    };

    loadBars();
  }, [
    selectedSymbol,
    selectedTimeframe,
    barLimit,
    periodMode,
    startDate,
    endDate,
    hasDateFilterError,
    authToken,
    marketDataRefreshToken,
  ]);

  useEffect(() => {
    if (!isAuthenticated || !selectedSymbol || activeStrategies.length === 0) {
      setSignals([]);
      setSignalsGenerating(false);
      return;
    }
    if (signalsSourceMode !== "historical") {
      return;
    }
    if (hasDateFilterError) {
      setSignalsGenerating(false);
      return;
    }

    const controller = new AbortController();
    const timeoutId = window.setTimeout(async () => {
      setSignalsGenerating(true);
      setSignalsError(null);
      try {
        const responses = await Promise.all(
          activeStrategies.map((strategy) =>
            fetch(`${API_BASE_URL}/signals/generate`, {
              method: "POST",
              headers: {
                "Content-Type": "application/json",
                Authorization: `Bearer ${authToken}`,
              },
              body: JSON.stringify(buildSignalGeneratePayload(strategy)),
              signal: controller.signal,
            }),
          ),
        );
        if (responses.some((response) => !response.ok)) {
          throw new Error("Falha ao gerar sinais.");
        }
        setSignalsRefreshToken((previous) => previous + 1);
      } catch (generationError) {
        if (generationError instanceof Error && generationError.name === "AbortError") {
          return;
        }
        setSignalsError("Falha ao gerar sinais.");
      } finally {
        setSignalsGenerating(false);
      }
    }, 650);

    return () => {
      window.clearTimeout(timeoutId);
      controller.abort();
    };
  }, [
    isAuthenticated,
    authToken,
    selectedSymbol,
    selectedTimeframe,
    activeStrategies,
    periodMode,
    barLimit,
    startDate,
    endDate,
    hasDateFilterError,
    signalsSourceMode,
  ]);

  useEffect(() => {
    if (!isAuthenticated || !selectedSymbol || activeStrategies.length === 0) {
      setSignals([]);
      setConsensusSignals([]);
      setSignalsGenerating(false);
      return;
    }
    if (signalsSourceMode !== "live") {
      return;
    }
    if (hasDateFilterError) {
      setSignalsGenerating(false);
      return;
    }

    let cancelled = false;
    const evaluateLive = async () => {
      setSignalsGenerating(true);
      setSignalsError(null);
      try {
        const response = await fetch(`${API_BASE_URL}/signals/evaluate-live`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${authToken}`,
          },
          body: JSON.stringify(
            buildLiveEvaluatePayload({
              symbol: selectedSymbol,
              timeframe: selectedTimeframe,
              strategies: activeStrategies,
              minStrength: signalMinStrengthPct / 100,
              periodMode,
              barLimit: periodMode === "window" ? barLimit : backtestLimit,
              startDate,
              endDate,
              contextQuotes: liveSignalQuotes,
              formingBar: liveSignalForming.forming,
            }),
          ),
        });
        if (!response.ok) {
          throw new Error("Falha ao avaliar sinais em tempo real.");
        }
        const payload = (await response.json()) as {
          signals: SignalItem[];
          is_forming_bar?: boolean;
        };
        if (cancelled) {
          return;
        }
        setLiveSignalIsForming(Boolean(payload.is_forming_bar));
        const filtered = payload.signals.filter((item) => {
          if (signalDirectionFilter !== "BOTH" && item.direction !== signalDirectionFilter) {
            return false;
          }
          return item.strength * 100 >= signalMinStrengthPct;
        });
        const sorted = [...filtered].sort(
          (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
        );
        setSignals(sorted);
        setConsensusSignals(sorted);
        setSignalsRefreshToken((previous) => previous + 1);
      } catch (liveError) {
        if (!cancelled) {
          setSignalsError("Falha ao avaliar sinais em tempo real.");
        }
      } finally {
        if (!cancelled) {
          setSignalsGenerating(false);
        }
      }
    };

    const debounceId = window.setTimeout(() => {
      void evaluateLive();
    }, tick?.last != null ? 800 : 0);
    const intervalId = window.setInterval(() => {
      void evaluateLive();
    }, LIVE_SIGNALS_POLL_MS);

    return () => {
      cancelled = true;
      window.clearTimeout(debounceId);
      window.clearInterval(intervalId);
    };
  }, [
    isAuthenticated,
    authToken,
    selectedSymbol,
    selectedTimeframe,
    activeStrategies,
    signalsSourceMode,
    periodMode,
    barLimit,
    startDate,
    endDate,
    hasDateFilterError,
    signalMinStrengthPct,
    signalDirectionFilter,
    liveSignalQuotes,
    liveSignalForming.forming,
    liveSignalForming.isLiveForming,
    tick?.last,
  ]);

  useEffect(() => {
    if (!isAuthenticated || !selectedSymbol || activeStrategies.length === 0) {
      setSignals([]);
      setConsensusSignals([]);
      return;
    }
    if (signalsSourceMode === "live") {
      return;
    }
    if (signalsGenerating) {
      return;
    }

    const loadConsensusSignals = async () => {
      try {
        const responses = await Promise.all(
          activeStrategies.map(async (strategy) => {
            const query = new URLSearchParams({
              symbol: selectedSymbol,
              timeframe: selectedTimeframe,
              strategy,
              limit: "1",
              source: "historical",
            });

            const response = await fetch(`${API_BASE_URL}/signals?${query.toString()}`, {
              headers: { Authorization: `Bearer ${authToken}` },
            });
            if (!response.ok) {
              throw new Error("Falha ao carregar sinais de consenso.");
            }
            return (await response.json()) as SignalItem[];
          }),
        );

        setConsensusSignals(
          responses
            .flat()
            .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()),
        );
      } catch {
        setConsensusSignals([]);
      }
    };

    loadConsensusSignals();
  }, [
    isAuthenticated,
    authToken,
    selectedSymbol,
    selectedTimeframe,
    activeStrategies,
    signalsRefreshToken,
    signalsGenerating,
    signalsSourceMode,
  ]);

  useEffect(() => {
    if (!isAuthenticated || !selectedSymbol || activeStrategies.length === 0) {
      setSignals([]);
      return;
    }
    if (signalsSourceMode === "live") {
      return;
    }
    if (signalsGenerating) {
      return;
    }

    const loadSignals = async () => {
      setSignalsLoading(true);
      try {
        const responses = await Promise.all(
          activeStrategies.map(async (strategy) => {
            const query = new URLSearchParams({
              symbol: selectedSymbol,
              timeframe: selectedTimeframe,
              strategy,
              limit: String(signalsFetchLimit),
              min_strength: String(signalMinStrengthPct / 100),
              source: "historical",
            });
            if (signalDirectionFilter !== "BOTH") {
              query.set("direction", signalDirectionFilter);
            }

            const response = await fetch(`${API_BASE_URL}/signals?${query.toString()}`, {
              headers: { Authorization: `Bearer ${authToken}` },
            });
            if (!response.ok) {
              throw new Error("Falha ao carregar sinais.");
            }
            return (await response.json()) as SignalItem[];
          }),
        );

        const merged = responses
          .flat()
          .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());
        setSignals(merged);
        setSignalsError(null);
      } catch {
        setSignalsError("Falha ao carregar sinais.");
      } finally {
        setSignalsLoading(false);
      }
    };

    loadSignals();
  }, [
    isAuthenticated,
    authToken,
    selectedSymbol,
    selectedTimeframe,
    activeStrategies,
    signalDirectionFilter,
    signalMinStrengthPct,
    signalsFetchLimit,
    signalsRefreshToken,
    signalsGenerating,
    signalsSourceMode,
  ]);

  const signalsTotalPages = Math.max(1, Math.ceil(signals.length / SIGNALS_PAGE_SIZE));

  useEffect(() => {
    setSignalsPage(1);
  }, [signals]);

  useEffect(() => {
    if (signalsPage > signalsTotalPages) {
      setSignalsPage(signalsTotalPages);
    }
  }, [signalsPage, signalsTotalPages]);

  const paginatedSignals = useMemo(
    () =>
      signals.slice(
        (signalsPage - 1) * SIGNALS_PAGE_SIZE,
        signalsPage * SIGNALS_PAGE_SIZE,
      ),
    [signals, signalsPage],
  );

  const strategyContributions = useMemo<StrategyContribution[]>(() => {
    return activeStrategies.map((strategy) => {
      const latest = consensusSignals.find((item) => item.strategy === strategy);
      if (!latest) {
        return {
          strategy,
          direction: "NEUTRAL",
          strength: 0,
          signedScore: 0,
          rationale: "Sem sinal para os filtros atuais.",
          timestamp: "",
        };
      }
      return {
        strategy,
        direction: latest.direction === "BUY" || latest.direction === "SELL" ? latest.direction : "NEUTRAL",
        strength: latest.strength,
        signedScore: toSignedScore(latest.direction, latest.strength),
        rationale: latest.rationale,
        timestamp: latest.timestamp,
      };
    });
  }, [activeStrategies, consensusSignals]);

  const consensus = useMemo(() => {
    if (strategyContributions.length === 0) {
      return { score: 0, direction: "NEUTRAL", confidence: 0 };
    }
    const score =
      strategyContributions.reduce((sum, item) => sum + item.signedScore, 0) / strategyContributions.length;
    const threshold = consensusThresholdPct / 100;
    const direction = score > threshold ? "BUY" : score < -threshold ? "SELL" : "NEUTRAL";
    const confidence = Math.min(1, Math.abs(score));
    return { score, direction, confidence };
  }, [strategyContributions, consensusThresholdPct]);

  const orderedStrategyContributions = useMemo(() => {
    return [...strategyContributions].sort((a, b) => {
      const impactDiff = Math.abs(b.signedScore) - Math.abs(a.signedScore);
      if (impactDiff !== 0) {
        return impactDiff;
      }
      return a.strategy.localeCompare(b.strategy);
    });
  }, [strategyContributions]);

  const comparedBacktestRuns = useMemo(
    () => backtestRuns.filter((run) => backtestCompareRunIds.includes(run.id)),
    [backtestRuns, backtestCompareRunIds],
  );

  const simulationBarLimit = periodMode === "window" ? barLimit : backtestLimit;

  const backtestDataAvailability = useMemo(() => {
    if (!selectedSymbol) {
      return { status: "no_symbol" as const };
    }
    if (loading) {
      return { status: "loading" as const, symbol: selectedSymbol, timeframe: selectedTimeframe };
    }
    const hasInstrument = instruments.some((item) => item.symbol === selectedSymbol);
    if (!hasInstrument) {
      return { status: "no_instrument" as const, symbol: selectedSymbol, timeframe: selectedTimeframe };
    }
    const availableBars = bars.length;
    if (availableBars === 0) {
      return { status: "no_bars" as const, symbol: selectedSymbol, timeframe: selectedTimeframe };
    }
    if (availableBars < BACKTEST_MIN_BARS) {
      return {
        status: "insufficient_bars" as const,
        symbol: selectedSymbol,
        timeframe: selectedTimeframe,
        availableBars,
        requiredBars: BACKTEST_MIN_BARS,
      };
    }
    if (availableBars < simulationBarLimit) {
      return {
        status: "partial_window" as const,
        symbol: selectedSymbol,
        timeframe: selectedTimeframe,
        availableBars,
        requestedBars: simulationBarLimit,
      };
    }
    return {
      status: "ready" as const,
      symbol: selectedSymbol,
      timeframe: selectedTimeframe,
      availableBars,
      requestedBars: simulationBarLimit,
    };
  }, [
    bars.length,
    instruments,
    loading,
    selectedSymbol,
    selectedTimeframe,
    simulationBarLimit,
  ]);

  const canRunBacktest =
    activeStrategies.length > 0 &&
    !backtestRunning &&
    (backtestDataAvailability.status === "ready" || backtestDataAvailability.status === "partial_window");

  const backtestRunStatusLine = useMemo(() => {
    if (backtestDataAvailability.status === "loading") {
      return "A verificar velas disponíveis...";
    }
    if (backtestDataAvailability.status === "ready") {
      return `Dados OK · ${backtestDataAvailability.availableBars} velas · ${backtestDataAvailability.symbol} / ${backtestDataAvailability.timeframe}`;
    }
    if (backtestDataAvailability.status === "partial_window") {
      return `Parcial · ${backtestDataAvailability.availableBars}/${backtestDataAvailability.requestedBars} velas · ${backtestDataAvailability.symbol} / ${backtestDataAvailability.timeframe}`;
    }
    if (backtestDataAvailability.status === "no_instrument") {
      return `${backtestDataAvailability.symbol} não está na base de dados.`;
    }
    if (backtestDataAvailability.status === "no_bars") {
      return `Sem velas para ${backtestDataAvailability.symbol} / ${backtestDataAvailability.timeframe}.`;
    }
    if (backtestDataAvailability.status === "insufficient_bars") {
      return `Só ${backtestDataAvailability.availableBars} velas (mín. ${backtestDataAvailability.requiredBars}).`;
    }
    return null;
  }, [backtestDataAvailability]);

  const backtestRunStatusTone =
    backtestDataAvailability.status === "ready"
      ? "ready"
      : backtestDataAvailability.status === "partial_window"
        ? "partial"
        : backtestDataAvailability.status === "loading"
          ? "loading"
          : "warning";

  const handleAuthSubmit = async () => {
    setAuthLoading(true);
    setAuthError(null);
    try {
      const response = await fetch(`${API_BASE_URL}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: authEmail, password: authPassword }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => null);
        throw new Error(parseApiError(data, "Falha de autenticação."));
      }

      const data = (await response.json()) as { access_token: string };
      localStorage.setItem(AUTH_TOKEN_STORAGE_KEY, data.access_token);
      setAuthToken(data.access_token);
      setAuthPassword("");
      setShowAuthPanel(false);
    } catch (submitError) {
      setAuthError(submitError instanceof Error ? submitError.message : "Erro inesperado.");
    } finally {
      setAuthLoading(false);
    }
  };

  const handleCreateCombination = async () => {
    if (!authToken || activeStrategies.length === 0 || !newCombinationName.trim()) {
      return;
    }
    setCombinationError(null);
    try {
      const response = await fetch(`${API_BASE_URL}/strategy-combinations`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify({
          name: newCombinationName.trim(),
          description: newCombinationDescription.trim() || null,
          strategies: activeStrategies,
          is_shared: true,
        }),
      });
      if (!response.ok) {
        throw new Error("Falha ao gravar combinação.");
      }
      setNewCombinationName("");
      setNewCombinationDescription("");
      setSignalsRefreshToken((previous) => previous + 1);
    } catch (createError) {
      setCombinationError(createError instanceof Error ? createError.message : "Erro inesperado.");
    }
  };

  const handleCloneCombination = async (combinationId: number) => {
    if (!authToken) {
      return;
    }
    setCombinationError(null);
    try {
      const response = await fetch(`${API_BASE_URL}/strategy-combinations/${combinationId}/clone`, {
        method: "POST",
        headers: { Authorization: `Bearer ${authToken}` },
      });
      if (!response.ok) {
        throw new Error("Falha ao clonar combinação.");
      }
      setSignalsRefreshToken((previous) => previous + 1);
    } catch (cloneError) {
      setCombinationError(cloneError instanceof Error ? cloneError.message : "Erro inesperado.");
    }
  };

  const parseBrokerMetadata = (): Record<string, string | number | boolean | null> => {
    const raw = newBrokerMetadataJson.trim();
    if (!raw) {
      return {};
    }
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error("Metadata deve ser um objeto JSON (ex.: {\"region\":\"EU\"}).");
    }
    return parsed as Record<string, string | number | boolean | null>;
  };

  const handleCreateBrokerConnection = async () => {
    if (!authToken) {
      return;
    }
    if (!newBrokerName.trim() || !newBrokerLabel.trim()) {
      setBrokerFormError("Preencha broker e etiqueta da conta.");
      return;
    }

    setBrokerFormError(null);
    try {
      const metadata = parseBrokerMetadata();
      const response = await fetch(`${API_BASE_URL}/broker-connections`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify({
          broker_name: newBrokerName.trim(),
          account_label: newBrokerLabel.trim(),
          environment: newBrokerEnvironment,
          connection_metadata: metadata,
          is_active: true,
        }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(parseApiError(payload, "Falha ao criar ligação de broker."));
      }

      setNewBrokerLabel("");
      setNewBrokerMetadataJson("{}");
      setBrokerRefreshToken((previous) => previous + 1);
    } catch (createError) {
      setBrokerFormError(createError instanceof Error ? createError.message : "Erro inesperado.");
    }
  };

  const handleToggleBrokerConnection = async (connection: BrokerConnection) => {
    if (!authToken) {
      return;
    }
    setBrokerConnectionsError(null);
    try {
      const response = await fetch(`${API_BASE_URL}/broker-connections/${connection.id}`, {
        method: "PUT",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify({ is_active: !connection.is_active }),
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(parseApiError(payload, "Falha ao atualizar ligação."));
      }
      setBrokerRefreshToken((previous) => previous + 1);
    } catch (toggleError) {
      setBrokerConnectionsError(toggleError instanceof Error ? toggleError.message : "Erro inesperado.");
    }
  };

  const handleDeleteBrokerConnection = async (connectionId: number) => {
    if (!authToken) {
      return;
    }
    setBrokerConnectionsError(null);
    try {
      const response = await fetch(`${API_BASE_URL}/broker-connections/${connectionId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${authToken}` },
      });
      if (!response.ok) {
        const payload = await response.json().catch(() => null);
        throw new Error(parseApiError(payload, "Falha ao remover ligação."));
      }
      setBrokerRefreshToken((previous) => previous + 1);
    } catch (deleteError) {
      setBrokerConnectionsError(deleteError instanceof Error ? deleteError.message : "Erro inesperado.");
    }
  };

  const handleResetSignalListFilters = () => {
    setSignalDirectionFilter("BOTH");
    setSignalMinStrengthPct(0);
    setSignalsPage(1);
  };

  const handleLoadDemoMarketData = async () => {
    if (!authToken || !selectedSymbol) {
      return;
    }
    setDemoDataLoading(true);
    setBacktestError(null);
    try {
      const response = await fetch(`${API_BASE_URL}/market-data/load-demo`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${authToken}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          symbols: [selectedSymbol],
          period: "2y",
          include_weekly: selectedTimeframe === "1w",
        }),
      });
      if (!response.ok) {
        const errorPayload = await response.json().catch(() => null);
        throw new Error(parseApiError(errorPayload, "Falha ao carregar dados demo."));
      }
      const payload = (await response.json()) as {
        results: Array<{ symbol: string; imported_rows_1d: number; imported_rows_1w: number }>;
      };
      const result = payload.results[0];
      if (!result) {
        throw new Error("Nenhum dado foi importado.");
      }
      const importedForTimeframe =
        selectedTimeframe === "1w" ? result.imported_rows_1w : result.imported_rows_1d;
      if (importedForTimeframe === 0) {
        throw new Error(
          selectedTimeframe === "1w"
            ? "Dados diários importados, mas sem velas semanais. Tente intervalo 1d ou volte a carregar com semanal."
            : "Nenhuma vela diária foi importada para este símbolo.",
        );
      }
      setMarketDataRefreshToken((previous) => previous + 1);
    } catch (loadError) {
      setBacktestError(toUserFetchError(loadError, "Erro inesperado ao carregar dados demo."));
    } finally {
      setDemoDataLoading(false);
    }
  };

  const handleRunBacktest = async () => {
    if (!authToken || !selectedSymbol || activeStrategies.length === 0) {
      return;
    }
    if (hasDateFilterError) {
      setBacktestError("Defina um intervalo de datas válido para correr backtest.");
      return;
    }
    if (backtestDataAvailability.status === "no_instrument" || backtestDataAvailability.status === "no_bars") {
      setBacktestError(
        `Sem velas para ${selectedSymbol} / ${selectedTimeframe}. Importe dados ou use "Carregar dados demo".`,
      );
      return;
    }
    if (backtestDataAvailability.status === "insufficient_bars") {
      setBacktestError(
        `Só ${backtestDataAvailability.availableBars} velas disponíveis; o backtest precisa de pelo menos ${BACKTEST_MIN_BARS}.`,
      );
      return;
    }

    setBacktestRunning(true);
    setAppliedReuseRun(null);
    setBacktestError(null);
    setBacktestSelectedRun(null);
    try {
      const strategyMinStrengths = Object.fromEntries(
        activeStrategies.map((strategy) => [
          strategy,
          (backtestStrategyMinStrengthPct[strategy] ?? DEFAULT_BACKTEST_STRENGTH_PCT) / 100,
        ]),
      );
      const singleStrategyOnly = activeStrategies.length === 1;
      const fallbackMinStrength = singleStrategyOnly
        ? strategyMinStrengths[activeStrategies[0]]
        : backtestConsensusStrengthPct / 100;

      const payload: Record<string, string | number | boolean | string[] | Record<string, number> | null> = {
        symbol: selectedSymbol,
        timeframe: selectedTimeframe,
        strategies: activeStrategies,
        initial_capital: backtestInitialCapital,
        fee_bps: backtestFeeBps,
        fee_model: backtestFeeModel,
        slippage_bps: backtestSlippageBps,
        slippage_model: backtestSlippageModel,
        min_signal_strength: fallbackMinStrength,
        strategy_min_strengths: strategyMinStrengths,
        min_consensus_strength: singleStrategyOnly ? null : backtestConsensusStrengthPct / 100,
        limit: simulationBarLimit,
        position_size_pct: backtestPositionSizePct,
        position_sizing_model: backtestPositionSizingModel,
        risk_per_trade_pct: backtestRiskPerTradePct,
        entry_confirmation_bars: backtestEntryConfirmationBars,
        execution_timing: backtestExecutionTiming,
        exit_mode: backtestExitMode,
        stop_loss_pct: backtestExitMode === "opposite_signal" ? null : backtestStopLossPct,
        take_profit_pct: backtestExitMode === "opposite_signal" ? null : backtestTakeProfitPct,
        max_bars_in_trade: backtestMaxBarsInTrade > 0 ? backtestMaxBarsInTrade : null,
        walkforward_split_pct: backtestWalkforwardSplitPct,
        walkforward_mode: backtestWalkforwardMode,
        walkforward_folds: backtestWalkforwardFolds,
        benchmark_enabled: backtestBenchmarkEnabled,
        period_mode: periodMode,
        chart_window: periodMode === "window" ? chartWindow : null,
      };

      if (periodMode === "date") {
        payload.start = `${startDate}T00:00:00Z`;
        payload.end = `${endDate}T23:59:59Z`;
      }

      const response = await fetch(`${API_BASE_URL}/backtests/run`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${authToken}`,
        },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const errorPayload = await response.json().catch(() => null);
        throw new Error(parseApiError(errorPayload, "Falha ao correr backtest."));
      }

      const created = (await response.json()) as BacktestRun;
      setAppliedRecommendations([]);
      setBacktestRefreshToken((previous) => previous + 1);
      setBacktestWorkspaceTab("results");
      await handleOpenBacktestRun(created.id);
    } catch (runError) {
      setBacktestError(toUserFetchError(runError, "Erro inesperado ao correr backtest."));
    } finally {
      setBacktestRunning(false);
    }
  };

  const handleExportBacktestCsv = async (runId: number, exportType: "trades" | "equity") => {
    if (!authToken) {
      return;
    }
    setBacktestError(null);
    try {
      const response = await fetch(
        `${API_BASE_URL}/backtests/${runId}/export?type=${exportType}`,
        { headers: { Authorization: `Bearer ${authToken}` } },
      );
      if (!response.ok) {
        const errorPayload = await response.json().catch(() => null);
        throw new Error(parseApiError(errorPayload, "Falha ao exportar CSV."));
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `backtest_${runId}_${exportType}.csv`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (exportError) {
      setBacktestError(toUserFetchError(exportError, "Erro inesperado ao exportar CSV."));
    }
  };

  const handleToggleBacktestRunDetail = async (runId: number) => {
    if (backtestSelectedRun?.id === runId) {
      setBacktestSelectedRun(null);
      return;
    }
    await handleOpenBacktestRun(runId);
  };

  const renderBacktestRunDetail = (run: BacktestRun) => {
    const equityCurve = getSummaryCurve(run.result_summary);
    const walkforwardBlock =
      typeof run.result_summary.walkforward === "object" && run.result_summary.walkforward !== null
        ? (run.result_summary.walkforward as Record<string, unknown>)
        : null;
    const walkforwardInSample = walkforwardBlock ? getWalkforwardMetrics(walkforwardBlock.in_sample) : null;
    const walkforwardOutSample = walkforwardBlock ? getWalkforwardMetrics(walkforwardBlock.out_sample) : null;
    const walkforwardAggregate = walkforwardBlock
      ? getWalkforwardMetrics(walkforwardBlock.out_sample_aggregate)
      : null;
    const walkforwardMode =
      typeof walkforwardBlock?.mode === "string" ? walkforwardBlock.mode : "holdout";
    const walkforwardFolds =
      Array.isArray(walkforwardBlock?.folds) ? (walkforwardBlock.folds as Record<string, unknown>[]) : [];
    const benchmarkReturnPct = getSummaryNumber(run.result_summary, "benchmark_return_pct");
    const runConfig = getRunConfigSnapshot(run);
    const benchmarkEnabled = runConfig.benchmark_enabled !== false;
    const trades = run.trades ?? [];
    const totalTradePages = Math.max(1, Math.ceil(trades.length / BACKTEST_TRADES_PAGE_SIZE));

    const renderWalkforwardColumn = (label: string, metrics: WalkforwardMetrics) => (
      <article className="backtest-wf-col">
        <strong>{label}</strong>
        <p>PnL {formatPct(metrics.net_pnl_pct)}</p>
        <p>
          {metrics.trades_count} trades · Win {formatPct(metrics.win_rate, 0)}
        </p>
        <p>
          PF {metrics.profit_factor.toFixed(2)} · DD {formatPct(metrics.max_drawdown_pct, 1)}
        </p>
        <p className="hint">{metrics.bars_processed} barras</p>
      </article>
    );

    return (
      <div className="backtest-detail-panel backtest-detail-inline">
        <div className="stats">
          <div>
            <span className="stats-label">Capital inicial {"->"} final</span>
            <strong>
              {run.initial_capital.toFixed(2)} {"->"}{" "}
              {getSummaryNumber(run.result_summary, "final_capital").toFixed(2)}
            </strong>
          </div>
          <div>
            <span className="stats-label">Profit factor</span>
            <strong>{run.profit_factor.toFixed(2)}</strong>
          </div>
          <div>
            <span className="stats-label">Expectancy</span>
            <strong>{getSummaryNumber(run.result_summary, "expectancy").toFixed(2)}</strong>
          </div>
          <div>
            <span className="stats-label">Retorno buy & hold</span>
            <strong>{formatPct(benchmarkReturnPct)}</strong>
          </div>
          <div>
            <span className="stats-label">Alpha vs benchmark</span>
            <strong>{formatPct(getSummaryNumber(run.result_summary, "alpha_vs_benchmark_pct"))}</strong>
          </div>
        </div>

        <div className="backtest-run-config-panel">
          <span className="stats-label">Configuração deste run</span>
          <div className="backtest-run-config-grid">
            <div>
              <span className="stats-label">Estratégias</span>
              <strong>
                {(Array.isArray(runConfig.strategies) ? runConfig.strategies : run.strategy_names)
                  .map((name) => STRATEGY_SUMMARY[String(name)]?.title ?? String(name))
                  .join(" · ")}
              </strong>
            </div>
            <div>
              <span className="stats-label">Fees / slippage</span>
              <strong>
                {typeof runConfig.fee_model === "string"
                  ? formatFeeModelLabel(runConfig.fee_model)
                  : `${Number(runConfig.fee_bps ?? run.fee_bps).toFixed(1)} bps`}
                {typeof runConfig.fee_model === "string" && runConfig.fee_model === "fixed_bps"
                  ? ` (${Number(runConfig.fee_bps ?? run.fee_bps).toFixed(1)} bps)`
                  : ""}
                {" · "}
                {Number(runConfig.slippage_bps ?? run.slippage_bps).toFixed(1)} bps slippage
                {typeof runConfig.slippage_model === "string"
                  ? ` · ${formatSlippageModelLabel(runConfig.slippage_model)}`
                  : ""}
              </strong>
            </div>
            {typeof runConfig.position_size_pct === "number" && (
              <div>
                <span className="stats-label">Capital por trade</span>
                <strong>
                  {typeof runConfig.position_sizing_model === "string"
                    ? `${formatPositionSizingLabel(runConfig.position_sizing_model)} · `
                    : ""}
                  {runConfig.position_sizing_model === "atr_risk" &&
                  typeof runConfig.risk_per_trade_pct === "number"
                    ? `${Number(runConfig.risk_per_trade_pct).toFixed(1)}% risco`
                    : `${runConfig.position_size_pct.toFixed(0)}%`}
                  {runConfig.position_sizing_model === "atr_risk" &&
                  typeof runConfig.position_size_pct === "number"
                    ? ` · teto ${runConfig.position_size_pct.toFixed(0)}%`
                    : ""}
                </strong>
              </div>
            )}
            {typeof runConfig.entry_confirmation_bars === "number" && (
              <div>
                <span className="stats-label">Confirmação entrada</span>
                <strong>{runConfig.entry_confirmation_bars} vela(s)</strong>
              </div>
            )}
            {typeof runConfig.execution_timing === "string" && (
              <div>
                <span className="stats-label">Timing execução</span>
                <strong>{formatExecutionTimingLabel(runConfig.execution_timing)}</strong>
              </div>
            )}
            {(typeof runConfig.execution_timing !== "string" &&
              typeof runConfig.entry_timing === "string") && (
              <div>
                <span className="stats-label">Timing execução</span>
                <strong>{formatExecutionTimingLabel(runConfig.entry_timing)}</strong>
              </div>
            )}
            {typeof runConfig.exit_mode === "string" && (
              <div>
                <span className="stats-label">Modo de saída</span>
                <strong>{formatExitModeLabel(runConfig.exit_mode)}</strong>
              </div>
            )}
            {typeof runConfig.stop_loss_pct === "number" && (
              <div>
                <span className="stats-label">Stop-loss</span>
                <strong>{runConfig.stop_loss_pct.toFixed(1)}%</strong>
              </div>
            )}
            {typeof runConfig.take_profit_pct === "number" && (
              <div>
                <span className="stats-label">Take-profit</span>
                <strong>{runConfig.take_profit_pct.toFixed(1)}%</strong>
              </div>
            )}
            {typeof runConfig.max_bars_in_trade === "number" && (
              <div>
                <span className="stats-label">Máx. barras</span>
                <strong>{runConfig.max_bars_in_trade}</strong>
              </div>
            )}
            {typeof runConfig.walkforward_split_pct === "number" && runConfig.walkforward_split_pct > 0 && (
              <div>
                <span className="stats-label">Walk-forward</span>
                <strong>
                  {formatWalkforwardModeLabel(
                    typeof runConfig.walkforward_mode === "string" ? runConfig.walkforward_mode : "holdout",
                  )}{" "}
                  · {Number(runConfig.walkforward_split_pct).toFixed(0)}% OOS
                  {typeof runConfig.walkforward_folds === "number" &&
                  runConfig.walkforward_mode === "rolling"
                    ? ` · ${runConfig.walkforward_folds} folds`
                    : ""}
                </strong>
              </div>
            )}
            {typeof runConfig.min_consensus_strength === "number" && run.strategy_names.length > 1 && (
              <div>
                <span className="stats-label">Consenso mínimo</span>
                <strong>{formatStrengthPct(runConfig.min_consensus_strength)}</strong>
              </div>
            )}
            {typeof runConfig.min_consensus_strength === "number" && run.strategy_names.length === 1 && (
              <div>
                <span className="stats-label">Limiar de força</span>
                <strong>{formatStrengthPct(runConfig.min_consensus_strength)}</strong>
              </div>
            )}
          </div>
          {typeof runConfig.strategy_min_strengths === "object" && runConfig.strategy_min_strengths !== null && (
            <div className="backtest-run-config-thresholds">
              {Object.entries(runConfig.strategy_min_strengths as Record<string, number>).map(
                ([strategy, strength]) => (
                  <span key={strategy} className="backtest-config-chip">
                    {STRATEGY_SUMMARY[strategy]?.title ?? strategy}: {formatStrengthPct(strength)}
                  </span>
                ),
              )}
            </div>
          )}
          <p className="hint backtest-run-config-meta">
            {run.bars_processed} barras processadas
            {run.start_at || run.end_at
              ? ` · ${run.start_at ? formatDateLabel(run.start_at) : "…"} – ${run.end_at ? formatDateLabel(run.end_at) : "…"}`
              : ""}
          </p>
        </div>

        {walkforwardMode === "holdout" && walkforwardInSample && walkforwardOutSample && walkforwardBlock && (
          <div className="backtest-walkforward-panel">
            <span className="stats-label">
              Walk-forward · holdout {getSummaryNumber(walkforwardBlock, "split_pct", 0).toFixed(0)}%
            </span>
            <div className="backtest-wf-grid">
              {renderWalkforwardColumn("In-sample", walkforwardInSample)}
              {renderWalkforwardColumn("Out-of-sample", walkforwardOutSample)}
            </div>
          </div>
        )}

        {walkforwardMode === "rolling" && walkforwardBlock && (
          <div className="backtest-walkforward-panel">
            <span className="stats-label">
              Walk-forward rolling · {getSummaryNumber(walkforwardBlock, "split_pct", 0).toFixed(0)}% por bloco
              {typeof walkforwardBlock.folds_count === "number"
                ? ` · ${walkforwardBlock.folds_count} folds`
                : ""}
            </span>
            {walkforwardAggregate && (
              <div className="backtest-wf-grid">
                {renderWalkforwardColumn("OOS agregado", walkforwardAggregate)}
              </div>
            )}
            {walkforwardFolds.length > 0 && (
              <div className="backtest-wf-grid">
                {walkforwardFolds.map((fold, index) => {
                  const foldMetrics = getWalkforwardMetrics(fold.out_sample);
                  if (!foldMetrics) {
                    return null;
                  }
                  const foldNumber = typeof fold.fold === "number" ? fold.fold : index + 1;
                  return (
                    <div key={`wf-fold-${foldNumber}`}>
                      {renderWalkforwardColumn(`Fold ${foldNumber} OOS`, foldMetrics)}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        )}

        {equityCurve.length > 0 && (
          <div className="equity-curve-list">
            <span className="stats-label">Curva de equity</span>
            <BacktestEquityChart
              points={equityCurve}
              initialCapital={run.initial_capital}
              benchmarkReturnPct={benchmarkReturnPct}
              benchmarkEnabled={benchmarkEnabled}
              tradesCount={run.trades_count}
              netPnlPct={run.net_pnl_pct}
            />
          </div>
        )}

        {run.insight && (
          <details className="backtest-insight-expand">
            <summary>
              <span>Análise crítica</span>
              <span className="backtest-insight-expand-meta">
                {run.insight.lessons.length} lições · {run.insight.recommendations.length} recomendações
              </span>
            </summary>
            <div className="backtest-insight-body">
              <p className="backtest-insight-summary">{run.insight.narrative_summary}</p>

              {run.insight.timeline.length > 0 && (
                <div className="backtest-insight-section">
                  <strong className="backtest-insight-section-title">Cronologia</strong>
                  <ol className="backtest-insight-timeline">
                    {run.insight.timeline.map((item) => (
                      <li
                        key={`${item.step}-${item.phase}`}
                        className={`backtest-insight-timeline-item backtest-insight-severity-${item.severity}`}
                      >
                        <strong>{item.title}</strong>
                        <p>{item.detail}</p>
                      </li>
                    ))}
                  </ol>
                </div>
              )}

              {run.insight.failure_modes.length > 0 && (
                <div className="backtest-insight-section">
                  <strong className="backtest-insight-section-title">Modos de falha</strong>
                  <ul className="backtest-insight-list">
                    {run.insight.failure_modes.map((item) => (
                      <li
                        key={item.code}
                        className={`backtest-insight-list-item backtest-insight-severity-${item.severity}`}
                      >
                        <strong>{item.title}</strong>
                        <p>{item.detail}</p>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {run.insight.lessons.length > 0 && (
                <div className="backtest-insight-section">
                  <strong className="backtest-insight-section-title">Lições aprendidas</strong>
                  <ul className="backtest-insight-list">
                    {run.insight.lessons.map((item) => (
                      <li key={item.title} className="backtest-insight-list-item">
                        <strong>
                          {item.title}
                          <span className="backtest-insight-priority"> · {item.priority}</span>
                        </strong>
                        <p>{item.detail}</p>
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              {run.insight.recommendations.length > 0 && (
                <div className="backtest-insight-section">
                  <strong className="backtest-insight-section-title">Sugestões (ver painel «próximo run» para aplicar)</strong>
                  <ul className="backtest-insight-list backtest-insight-list-compact">
                    {run.insight.recommendations.map((item) => (
                      <li key={`${item.area}-${item.suggestion}`} className="backtest-insight-list-item">
                        <strong>{item.suggestion}</strong>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </details>
        )}

        {(run.trades_count > 0 || equityCurve.length > 0) && (
          <div className="backtest-detail-chart-action">
            {run.trades_count > 0 && (
              <>
                <button
                  type="button"
                  className="tab-button"
                  onClick={() => void handleShowBacktestTradesOnChart(run)}
                >
                  {backtestTradesOnChartRunId === run.id
                    ? "Trades visíveis no gráfico"
                    : "Ver trades no gráfico"}
                </button>
                {backtestTradesOnChartRunId === run.id && (
                  <button type="button" className="config-button" onClick={handleClearBacktestTradesOnChart}>
                    Ocultar do gráfico
                  </button>
                )}
              </>
            )}
            <button
              type="button"
              className="config-button"
              onClick={() => void handleExportBacktestCsv(run.id, "trades")}
            >
              Exportar trades CSV
            </button>
            {equityCurve.length > 0 && (
              <button
                type="button"
                className="config-button"
                onClick={() => void handleExportBacktestCsv(run.id, "equity")}
              >
                Exportar equity CSV
              </button>
            )}
          </div>
        )}

        {trades.length > 0 ? (
          <div className="backtest-trades-list">
            <div className="backtest-trades-list-header">
              <span className="stats-label">Trades ({trades.length})</span>
              {trades.length > BACKTEST_TRADES_PAGE_SIZE && (
                <div className="backtest-trades-pagination">
                  <button
                    type="button"
                    className="config-button"
                    disabled={backtestTradesPage <= 1}
                    onClick={() => setBacktestTradesPage((page) => Math.max(1, page - 1))}
                  >
                    Anterior
                  </button>
                  <span className="hint">
                    {Math.min((backtestTradesPage - 1) * BACKTEST_TRADES_PAGE_SIZE + 1, trades.length)}–
                    {Math.min(backtestTradesPage * BACKTEST_TRADES_PAGE_SIZE, trades.length)} de {trades.length}
                  </span>
                  <button
                    type="button"
                    className="config-button"
                    disabled={backtestTradesPage >= totalTradePages}
                    onClick={() => setBacktestTradesPage((page) => Math.min(totalTradePages, page + 1))}
                  >
                    Seguinte
                  </button>
                </div>
              )}
            </div>
            <div className="signals-list">
              {trades
                .slice(
                  (backtestTradesPage - 1) * BACKTEST_TRADES_PAGE_SIZE,
                  backtestTradesPage * BACKTEST_TRADES_PAGE_SIZE,
                )
                .map((trade) => (
                  <article key={trade.id} className="signal-row">
                    <div className="signal-main">
                      <div className="signal-top">
                        <strong>{trade.direction}</strong>
                        <span>{formatDateTimeLabel(trade.entry_timestamp)}</span>
                        <span>{formatDateTimeLabel(trade.exit_timestamp)}</span>
                        <span>Barras: {trade.bars_held}</span>
                      </div>
                      <p>
                        PnL:{" "}
                        <strong className={trade.net_pnl >= 0 ? "signal-buy" : "signal-sell"}>
                          {trade.net_pnl.toFixed(2)}
                        </strong>{" "}
                        | Retorno: {(trade.return_pct * 100).toFixed(2)}% | Entry {trade.entry_price.toFixed(2)}{" "}
                        {"->"} Exit {trade.exit_price.toFixed(2)}
                      </p>
                      <p className="backtest-trade-reason">
                        <span>Entrada: {trade.entry_reason}</span>
                        <span>Saída: {trade.exit_reason}</span>
                      </p>
                    </div>
                  </article>
                ))}
            </div>
          </div>
        ) : (
          <p className="hint">Este run não gerou trades.</p>
        )}
      </div>
    );
  };

  const handleOpenBacktestRun = async (runId: number) => {
    if (!authToken) {
      return;
    }
    setBacktestError(null);
    try {
      const response = await fetch(`${API_BASE_URL}/backtests/${runId}`, {
        headers: { Authorization: `Bearer ${authToken}` },
      });
      if (!response.ok) {
        const errorPayload = await response.json().catch(() => null);
        throw new Error(parseApiError(errorPayload, "Falha ao carregar detalhe do backtest."));
      }
      setBacktestSelectedRun((await response.json()) as BacktestRun);
    } catch (loadError) {
      setBacktestError(loadError instanceof Error ? loadError.message : "Erro inesperado.");
    }
  };

  const handleViewLessonRun = async (runId: number) => {
    setActiveTab("backtests");
    setBacktestWorkspaceTab("results");
    const runIndex = backtestRuns.findIndex((run) => run.id === runId);
    if (runIndex >= 0) {
      setBacktestRunsPage(Math.floor(runIndex / BACKTEST_RUNS_PAGE_SIZE) + 1);
    }
    await handleOpenBacktestRun(runId);
  };

  const handleApplySelectedRecommendations = (newRecords: AppliedRecommendationRecord[]) => {
    setAppliedRecommendations((previous) => {
      const keys = new Set(newRecords.map((record) => record.key));
      return [...previous.filter((record) => !keys.has(record.key)), ...newRecords];
    });
    setBacktestWorkspaceTab("recommendations");
    setBacktestError(null);
  };

  const backtestRecommendationSetters = useMemo(
    (): BacktestFormSetters => ({
      setExitMode: setBacktestExitMode,
      setStopLossPct: setBacktestStopLossPct,
      setTakeProfitPct: setBacktestTakeProfitPct,
      setConsensusStrengthPct: setBacktestConsensusStrengthPct,
      setEntryConfirmationBars: setBacktestEntryConfirmationBars,
      setStrategyMinStrengthPct: setBacktestStrategyMinStrengthPct,
      setActiveStrategies,
      setTimeframe: (timeframe: string) => setCandle(parseCandleCode(timeframe)),
    }),
    [],
  );

  const handleToggleCompareRun = (runId: number) => {
    setBacktestCompareRunIds((previous) => {
      if (previous.includes(runId)) {
        return previous.filter((id) => id !== runId);
      }
      if (previous.length >= 2) {
        return [previous[1], runId];
      }
      return [...previous, runId];
    });
  };

  const handleSaveBacktestPreset = () => {
    const name = backtestPresetName.trim();
    if (!name) {
      setBacktestError("Defina um nome para guardar preset.");
      return;
    }
    const barLimitForPreset = periodMode === "window" ? barLimit : backtestLimit;
    const preset: BacktestPreset = normalizeBacktestPreset({
      id: `${Date.now()}`,
      name,
      strategies: activeStrategies,
      initialCapital: backtestInitialCapital,
      feeBps: backtestFeeBps,
      feeModel: backtestFeeModel,
      slippageBps: backtestSlippageBps,
      slippageModel: backtestSlippageModel,
      strategyMinStrengthPct: Object.fromEntries(
        activeStrategies.map((strategy) => [
          strategy,
          backtestStrategyMinStrengthPct[strategy] ?? DEFAULT_BACKTEST_STRENGTH_PCT,
        ]),
      ),
      consensusStrengthPct: backtestConsensusStrengthPct,
      periodMode,
      chartWindow: periodMode === "window" ? chartWindow : null,
      barLimit: barLimitForPreset,
      limit: barLimitForPreset,
      startDate: periodMode === "date" ? startDate : null,
      endDate: periodMode === "date" ? endDate : null,
      positionSizePct: backtestPositionSizePct,
      positionSizingModel: backtestPositionSizingModel,
      riskPerTradePct: backtestRiskPerTradePct,
      entryConfirmationBars: backtestEntryConfirmationBars,
      executionTiming: backtestExecutionTiming,
      exitMode: backtestExitMode,
      stopLossPct: backtestStopLossPct,
      takeProfitPct: backtestTakeProfitPct,
      maxBarsInTrade: backtestMaxBarsInTrade,
      walkforwardSplitPct: backtestWalkforwardSplitPct,
      walkforwardMode: backtestWalkforwardMode,
      walkforwardFolds: backtestWalkforwardFolds,
      benchmarkEnabled: backtestBenchmarkEnabled,
    });
    setBacktestPresets((previous) => [preset, ...previous].slice(0, 20));
    setBacktestPresetName("");
    setBacktestError(null);
  };

  const handleApplyBacktestPreset = (presetId: string) => {
    const preset = backtestPresets.find((item) => item.id === presetId);
    if (!preset) {
      return;
    }
    applyBacktestPresetConfig(normalizeBacktestPreset(preset), backtestRunConfigSetters);
    setBacktestError(null);
  };

  const applyBacktestConfigFromRun = (run: BacktestRun) => {
    const parsed = applyBacktestRunConfig(run, backtestRunConfigSetters, {
      symbolAvailable: instruments.some((item) => item.symbol === run.symbol),
    });
    setAppliedReuseRun({
      runId: run.id,
      label: formatBacktestRunLabel(run),
      summaryLines: summarizeAppliedRunConfig(run, parsed, STRATEGY_LABELS),
    });
    setBacktestError(null);
  };

  const handleApplyBacktestRunConfig = (run: BacktestRun) => {
    applyBacktestConfigFromRun(run);
    setActiveTab("backtests");
    setBacktestWorkspaceTab("results");
    window.requestAnimationFrame(() => {
      reuseBannerRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    });
  };

  const handleClearBacktestTradesOnChart = () => {
    setBacktestTradesOnChart([]);
    setBacktestTradesOnChartRunId(null);
  };

  const handleClearSignalsOnChart = () => {
    setPinnedSignalsOnChart([]);
    setSignalsChartOverlayEnabled(false);
    setSelectedChartSignal(null);
    setChartSignalMatches([]);
  };

  const hasSignalsOnChart =
    signalsChartOverlayEnabled || pinnedSignalsOnChart.length > 0;

  const handleShowFilteredSignalsOnChart = () => {
    if (signals.length === 0) {
      return;
    }
    setSignalsChartOverlayEnabled(true);
    setPinnedSignalsOnChart([]);
    setSelectedChartSignal(null);
    setChartSignalMatches([]);
    setActiveTab("market");
    setChartMode("historico");
  };

  const handleSignalsChartAction = () => {
    if (signals.length === 0) {
      return;
    }
    if (hasSignalsOnChart) {
      setActiveTab("market");
      setChartMode("historico");
      return;
    }
    handleShowFilteredSignalsOnChart();
  };

  const handleShowSignalOnChart = (signal: SignalItem) => {
    if (instruments.some((item) => item.symbol === signal.symbol)) {
      setSelectedSymbol(signal.symbol);
    }
    setCandle(parseCandleCode(signal.timeframe));
    setManualCandle(true);
    setPinnedSignalsOnChart([signal]);
    setSignalsChartOverlayEnabled(false);
    setSelectedChartSignal(signal);
    setChartSignalMatches([signal]);
    setActiveTab("market");
    setChartMode("historico");
  };

  const handleChartSignalClick = (timeSec: number) => {
    const matches = findSignalsAtChartTime(chartSignals, timeSec) as SignalItem[];
    if (matches.length === 0) {
      return;
    }
    setChartSignalMatches(matches);
    setSelectedChartSignal(matches[0]);
  };

  const handleShowBacktestTradesOnChart = async (run: BacktestRun) => {
    if (!authToken) {
      return;
    }
    setBacktestError(null);
    try {
      let trades = run.trades ?? [];
      let chartRun = run;
      if (trades.length === 0) {
        const response = await fetch(`${API_BASE_URL}/backtests/${run.id}`, {
          headers: { Authorization: `Bearer ${authToken}` },
        });
        if (!response.ok) {
          const errorPayload = await response.json().catch(() => null);
          throw new Error(parseApiError(errorPayload, "Falha ao carregar trades do run."));
        }
        chartRun = (await response.json()) as BacktestRun;
        trades = chartRun.trades ?? [];
      }
      if (trades.length === 0) {
        setBacktestError("Este run não tem trades para mostrar no gráfico.");
        return;
      }

      applyBacktestRunConfig(chartRun, backtestRunConfigSetters, {
        symbolAvailable: instruments.some((item) => item.symbol === chartRun.symbol),
      });
      setBacktestTradesOnChart(trades);
      setBacktestTradesOnChartRunId(chartRun.id);
      setActiveTab("market");
      setChartMode("historico");
    } catch (showError) {
      setBacktestError(toUserFetchError(showError, "Erro inesperado ao preparar gráfico."));
    }
  };

  const handleDeleteBacktestRun = async (runId: number) => {
    if (!authToken) {
      return;
    }
    if (!window.confirm(`Apagar a simulação #${runId}? Esta ação não pode ser desfeita.`)) {
      return;
    }
    setBacktestError(null);
    try {
      const response = await fetch(`${API_BASE_URL}/backtests/${runId}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${authToken}` },
      });
      if (!response.ok) {
        const errorPayload = await response.json().catch(() => null);
        throw new Error(parseApiError(errorPayload, "Falha ao apagar simulação."));
      }
      if (backtestSelectedRun?.id === runId) {
        setBacktestSelectedRun(null);
      }
      if (backtestTradesOnChartRunId === runId) {
        handleClearBacktestTradesOnChart();
      }
      setBacktestCompareRunIds((previous) => previous.filter((id) => id !== runId));
      setBacktestRefreshToken((previous) => previous + 1);
    } catch (deleteError) {
      setBacktestError(toUserFetchError(deleteError, "Erro inesperado ao apagar simulação."));
    }
  };

  const toggleActiveStrategy = (strategy: string) => {
    setActiveStrategies((previous) => {
      if (previous.includes(strategy)) {
        return previous.filter((value) => value !== strategy);
      }
      setBacktestStrategyMinStrengthPct((strengths) => ({
        ...strengths,
        [strategy]: strengths[strategy] ?? DEFAULT_BACKTEST_STRENGTH_PCT,
      }));
      return [...previous, strategy];
    });
  };

  const toggleActiveIndicator = (id: IndicatorId) => {
    setActiveIndicators((previous) => {
      const next = new Set(previous);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const handleBacktestStrategyStrengthChange = (strategy: string, pct: number) => {
    const normalized = Math.max(0, Math.min(100, pct));
    setBacktestStrategyMinStrengthPct((previous) => ({
      ...previous,
      [strategy]: normalized,
    }));
  };

  return (
    <main className="layout app-shell">
      <header className="app-topbar">
        <div className="app-topbar-left">
          <h1>Painel de Mercado</h1>
          <span className="app-env-badge">PAPER</span>
        </div>
        <div className="app-topbar-actions">
          {currentUser ? (
            <>
              <span className="app-user-label" title={currentUser.email}>
                {currentUser.display_name ?? currentUser.email}
              </span>
              <button type="button" className="config-button" onClick={() => setShowAuthPanel(true)}>
                Conta
              </button>
              <button type="button" className="config-button" onClick={logout}>
                Sair
              </button>
            </>
          ) : authChecking ? (
            <span className="hint">A validar sessão...</span>
          ) : (
            <>
              <span className="hint">Sem sessão</span>
              <button type="button" className="config-button" onClick={() => setShowAuthPanel(true)}>
                Entrar
              </button>
            </>
          )}
          <button
            type="button"
            className={showConfigPanel ? "config-button config-button-active" : "config-button"}
            onClick={() => setShowConfigPanel((previous) => !previous)}
          >
            Configuração
          </button>
        </div>
      </header>

      {showAuthPanel && (
        <div className="auth-overlay" role="presentation">
          <button
            type="button"
            className="auth-overlay-backdrop"
            aria-label="Fechar acesso de utilizador"
            onClick={() => setShowAuthPanel(false)}
          />
          <section className="auth-modal">
            <div className="config-panel-header">
              <div className="config-title-block">
                <p className="config-kicker">Sessão</p>
                <h2>Acesso de utilizador</h2>
              </div>
              <button
                type="button"
                className="config-close-button"
                onClick={() => setShowAuthPanel(false)}
              >
                Fechar
              </button>
            </div>
            <p className="hint config-description">
              Faça login para gerar sinais, guardar combinações e clonar estratégias partilhadas.
            </p>
            <div className="auth-grid">
              <label className="field">
                <span>Email</span>
                <input value={authEmail} onChange={(event) => setAuthEmail(event.target.value)} />
              </label>
              <label className="field">
                <span>Password</span>
                <input
                  type="password"
                  value={authPassword}
                  onChange={(event) => setAuthPassword(event.target.value)}
                />
              </label>
            </div>
            <div className="auth-actions">
              <button type="button" className="tab-button" disabled={authLoading} onClick={handleAuthSubmit}>
                Entrar
              </button>
            </div>
            {authError && <p className="error">{authError}</p>}
          </section>
        </div>
      )}

      {showConfigPanel && (
        <div className="config-overlay" role="presentation">
          <button
            type="button"
            className="config-overlay-backdrop"
            aria-label="Fechar configuração"
            onClick={() => setShowConfigPanel(false)}
          />
          <section className="config-panel global-config-panel">
            <div className="config-panel-header">
              <div className="config-title-block">
                <p className="config-kicker">Centro de configuração</p>
                <h2>Configuração global</h2>
              </div>
              <button
                type="button"
                className="config-close-button"
                onClick={() => setShowConfigPanel(false)}
              >
                Fechar
              </button>
            </div>
            <p className="hint config-description">
              Parâmetros estáticos da aplicação. Esta área está preparada para crescer por secções.
            </p>
            <nav className="app-tabs config-tabs-nav" aria-label="Configuração">
              <div className="rt-seg">
                <button
                  type="button"
                  className={activeConfigTab === "data" ? "rt-seg-active" : ""}
                  onClick={() => setActiveConfigTab("data")}
                >
                  Dados
                </button>
                <button
                  type="button"
                  className={activeConfigTab === "signals" ? "rt-seg-active" : ""}
                  onClick={() => setActiveConfigTab("signals")}
                >
                  Sinais
                </button>
                <button
                  type="button"
                  className={activeConfigTab === "execution" ? "rt-seg-active" : ""}
                  onClick={() => setActiveConfigTab("execution")}
                >
                  Execução
                </button>
                <button
                  type="button"
                  className={activeConfigTab === "alerts" ? "rt-seg-active" : ""}
                  onClick={() => setActiveConfigTab("alerts")}
                >
                  Alertas
                </button>
              </div>
            </nav>
            <div className="config-sections">
              {activeConfigTab === "data" && (
                <section className="config-section">
                  <div className="config-section-header">
                    <h4>Dados de mercado</h4>
                    <p>Preferências globais de origem, retenção e qualidade de dados.</p>
                  </div>
                  <div className="config-placeholder">
                    Em breve: origem de dados, granularidades permitidas, validações de import e janela de retenção.
                  </div>
                </section>
              )}

              {activeConfigTab === "signals" && (
                <section className="config-section">
                  <div className="config-section-header">
                    <h4>Consenso e sinais</h4>
                    <p>Parâmetros base usados no cálculo combinado e na recolha de sinais.</p>
                  </div>
                  <div className="config-grid">
                    <label className="field">
                      <span>Limiar consenso (%)</span>
                      <input
                        type="number"
                        min={0}
                        max={100}
                        step={1}
                        value={consensusThresholdPct}
                        onChange={(event) => {
                          const parsed = Number(event.target.value);
                          if (Number.isNaN(parsed)) {
                            return;
                          }
                          setConsensusThresholdPct(Math.max(0, Math.min(100, parsed)));
                        }}
                      />
                    </label>
                    <label className="field">
                      <span>Limite de sinais</span>
                      <input
                        type="number"
                        min={50}
                        max={2000}
                        step={50}
                        value={signalsFetchLimit}
                        onChange={(event) => {
                          const parsed = Number(event.target.value);
                          if (Number.isNaN(parsed)) {
                            return;
                          }
                          setSignalsFetchLimit(Math.max(50, Math.min(2000, parsed)));
                        }}
                      />
                    </label>
                  </div>
                </section>
              )}

              {activeConfigTab === "execution" && (
                <section className="config-section">
                  <div className="config-section-header">
                    <h4>Execução e brokers</h4>
                    <p>Ligações por utilizador para preparar execução, posições e integração com corretoras.</p>
                  </div>
                  <div className="broker-config-grid">
                    <label className="field">
                      <span>Broker</span>
                      <input
                        value={newBrokerName}
                        onChange={(event) => setNewBrokerName(event.target.value)}
                        placeholder="Ex.: Binance, XTB, Interactive Brokers"
                      />
                    </label>
                    <label className="field">
                      <span>Etiqueta da conta</span>
                      <input
                        value={newBrokerLabel}
                        onChange={(event) => setNewBrokerLabel(event.target.value)}
                        placeholder="Ex.: Principal, Demo, Conta PT"
                      />
                    </label>
                    <label className="field">
                      <span>Ambiente</span>
                      <select
                        value={newBrokerEnvironment}
                        onChange={(event) => setNewBrokerEnvironment(event.target.value)}
                      >
                        <option value="paper">paper</option>
                        <option value="live">live</option>
                      </select>
                    </label>
                    <label className="field">
                      <span>Metadata (JSON)</span>
                      <input
                        value={newBrokerMetadataJson}
                        onChange={(event) => setNewBrokerMetadataJson(event.target.value)}
                        placeholder='Ex.: {"region":"EU","leverage":2}'
                      />
                    </label>
                  </div>
                  <div className="auth-actions">
                    <button type="button" className="tab-button" onClick={handleCreateBrokerConnection}>
                      Guardar ligação de broker
                    </button>
                  </div>
                  {brokerFormError && <p className="error">{brokerFormError}</p>}
                  {brokerConnectionsError && <p className="error">{brokerConnectionsError}</p>}
                  {brokerConnectionsLoading && <p className="hint">A carregar ligações...</p>}
                  {!brokerConnectionsLoading && brokerConnections.length === 0 && (
                    <p className="hint">Sem ligações configuradas para este utilizador.</p>
                  )}
                  {brokerConnections.length > 0 && (
                    <div className="broker-connection-list">
                      {brokerConnections.map((connection) => (
                        <article key={connection.id} className="broker-connection-row">
                          <div>
                            <strong>{connection.broker_name}</strong>
                            <p>
                              {connection.account_label} | {connection.environment} |{" "}
                              {connection.is_active ? "ativa" : "inativa"}
                            </p>
                          </div>
                          <div className="auth-actions">
                            <button
                              type="button"
                              className="config-button"
                              onClick={() => handleToggleBrokerConnection(connection)}
                            >
                              {connection.is_active ? "Desativar" : "Ativar"}
                            </button>
                            <button
                              type="button"
                              className="config-button"
                              onClick={() => handleDeleteBrokerConnection(connection.id)}
                            >
                              Remover
                            </button>
                          </div>
                        </article>
                      ))}
                    </div>
                  )}
                  <div className="config-placeholder">
                    Próximo passo: credenciais cifradas, teste de conectividade e seleção de conta para execução.
                  </div>
                </section>
              )}

              {activeConfigTab === "alerts" && (
                <section className="config-section">
                  <div className="config-section-header">
                    <h4>Alertas e notificações</h4>
                    <p>Gestão de avisos do sistema e eventos de estratégia.</p>
                  </div>
                  <div className="config-placeholder">
                    Em breve: canais de alerta, severidade, regras de silêncio e agregação de notificações.
                  </div>
                </section>
              )}
            </div>
          </section>
        </div>
      )}

      {!isAuthenticated ? (
        <section className="panel auth-gate-panel">
          <h3>Acesso necessário</h3>
          <p className="hint">
            Faça login para aceder ao painel, gerar sinais e utilizar combinações partilhadas.
          </p>
          <button type="button" className="tab-button" onClick={() => setShowAuthPanel(true)}>
            Entrar
          </button>
        </section>
      ) : (
      <div className="app-workspace">
        <nav className="app-tabs-hanging" aria-label="Secções">
          <button
            type="button"
            className={activeTab === "market" ? "app-tab-btn app-tab-btn-active" : "app-tab-btn"}
            onClick={() => setActiveTab("market")}
          >
            Mercado
          </button>
          <button
            type="button"
            className={activeTab === "signals" ? "app-tab-btn app-tab-btn-active" : "app-tab-btn"}
            onClick={() => setActiveTab("signals")}
          >
            Sinais
          </button>
          <button
            type="button"
            className={activeTab === "backtests" ? "app-tab-btn app-tab-btn-active" : "app-tab-btn"}
            onClick={() => setActiveTab("backtests")}
          >
            Simulação
          </button>
        </nav>

      <section className="panel app-panel-card">
        {activeTab === "market" && (
          <MarketChartModeToggle mode={chartMode} onChange={setChartMode} />
        )}
        {activeTab === "signals" && (
          <MarketChartModeToggle
            mode={signalsSourceMode === "historical" ? "historico" : "aovivo"}
            onChange={(mode) => setSignalsSourceMode(mode === "historico" ? "historical" : "live")}
          />
        )}

        <GlobalMarketFilters
          activeTab={activeTab}
          chartMode={chartMode}
          signalsSourceMode={signalsSourceMode}
          apiBaseUrl={API_BASE_URL}
          authToken={authToken}
          instruments={instruments}
          symbol={selectedSymbol}
          followed={followedSymbols}
          isFollowing={isFollowingSelected}
          onFollowChange={() => setMarketDataRefreshToken((previous) => previous + 1)}
          candle={candle}
          window={chartWindow}
          manualCandle={manualCandle}
          periodMode={periodMode}
          startDate={startDate}
          endDate={endDate}
          streamStatus={streamStatus}
          lastBarMs={lastBarMs}
          nowMs={marketNowMs}
          onSymbol={setSelectedSymbol}
          onCandle={handleMarketCandle}
          onWindow={handleMarketWindow}
          onPeriodMode={setPeriodMode}
          onStartDate={setStartDate}
          onEndDate={setEndDate}
          barCountLimit={backtestLimit}
          onBarCountLimit={setBacktestLimit}
          availableStrategies={availableStrategies}
          strategyLabels={STRATEGY_LABELS}
          activeStrategies={activeStrategies}
          onToggleStrategy={toggleActiveStrategy}
          activeIndicators={activeIndicators}
          onToggleIndicator={toggleActiveIndicator}
        />

        {!error && isDateFilterIncomplete && <p className="hint">Defina data início e data fim.</p>}
        {!error && isDateRangeInvalid && <p className="hint">A data fim tem de ser igual ou posterior à data início.</p>}
        {!error && loading && <p className="hint">A carregar dados...</p>}

        {error && <p className="error">{error}</p>}

        <div className="tab-content">
          <div
            className={activeTab === "market" ? "tab-pane tab-pane-active mkt-tab-pane" : "tab-pane mkt-tab-pane"}
          >
            {activeTab === "market" && chartMode === "aovivo" ? (
              <RealtimePage
                apiBaseUrl={API_BASE_URL}
                authToken={authToken}
                symbol={selectedSymbol}
                onSymbolChange={setSelectedSymbol}
                candle={candle}
                window={chartWindow}
                manualCandle={manualCandle}
                onCandleChange={handleMarketCandle}
                onWindowChange={handleMarketWindow}
                hideTimeframeControls
                hideIndicatorControls
                hideSymbolBar
                activeIndicators={activeIndicators}
                onToggleIndicator={toggleActiveIndicator}
                useParentStream
                tick={tick}
                indices={indices}
                streamStatus={streamStatus}
                streamError={streamError}
              />
            ) : activeTab === "market" && chartMode === "historico" ? (
              <HistoricalMarketView
                symbol={selectedSymbol}
                bars={bars}
                periodMode={periodMode}
                chartWindow={chartWindow}
                activeIndicators={activeIndicators}
                tradeMarkers={backtestTradesOnChart}
                signalMarkers={chartSignals}
                signalsOverlayEnabled={signalsChartOverlayEnabled}
                selectedChartSignal={selectedChartSignal}
                selectedChartSignalMatches={chartSignalMatches}
                strategyLabels={STRATEGY_LABELS}
                loading={loading}
                error={error}
                hasDateFilterError={hasDateFilterError}
                barLimit={periodMode === "window" ? barLimit : backtestLimit}
                backtestTradesOnChartRunId={backtestTradesOnChartRunId}
                backtestTradesCount={backtestTradesOnChart.length}
                signalsListCount={signals.length}
                onClearBacktestTrades={handleClearBacktestTradesOnChart}
                onClearSignalsOnChart={handleClearSignalsOnChart}
                onShowSignalsOnChart={handleShowFilteredSignalsOnChart}
                onChartSignalClick={handleChartSignalClick}
                onSelectChartSignal={(signal) => {
                  setSelectedChartSignal(signal as SignalItem | null);
                  if (signal) {
                    setChartSignalMatches([signal as SignalItem]);
                  } else {
                    setChartSignalMatches([]);
                  }
                }}
              />
            ) : null}

            {activeTab === "market" && (
              <HotMoversGrid
                apiBaseUrl={API_BASE_URL}
                authToken={authToken}
                symbol={selectedSymbol}
                onSelect={setSelectedSymbol}
              />
            )}
          </div>

          <div
            className={activeTab === "signals" ? "tab-pane tab-pane-active" : "tab-pane"}
          >
            <div className="rt-page signals-panel">
              <div className="signals-header">
                <h3 className="section-title">Sinais da estratégia</h3>
              </div>
              <p className="hint">
                {signalsSourceMode === "historical"
                  ? "Gera sinais sobre o período de barras seleccionado nos filtros globais."
                  : liveSignalIsForming
                    ? "Sinal na vela em formação (stream + ticks). Janela/datas definem o contexto dos indicadores."
                    : "Última vela fechada na BD. Com stream IBKR activo, o sinal passa a reflectir a vela em formação."}
              </p>
              {signalsSourceMode === "live" && streamError && (
                <p className="error">{streamError}</p>
              )}
              {liveSignalsDataStale && lastBarMs !== null && (
                <p className="hint">{formatStaleBarMessage(candle, lastBarMs)}</p>
              )}

              {!isAuthenticated && !authChecking && (
                <p className="hint">Inicie sessão no topo para gerar sinais e usar partilha.</p>
              )}
              {!isAuthenticated && authChecking && <p className="hint">A validar sessão...</p>}

              {isAuthenticated && (
                <details className="strategy-library-expand">
                  <summary>Biblioteca partilhada de combinações</summary>
                  <div className="strategy-library">
                    <div className="auth-grid">
                      <label className="field">
                        <span>Nome da combinação</span>
                        <input
                          value={newCombinationName}
                          onChange={(event) => setNewCombinationName(event.target.value)}
                          placeholder="Ex.: Trend + Reversal"
                        />
                      </label>
                      <label className="field">
                        <span>Descrição</span>
                        <input
                          value={newCombinationDescription}
                          onChange={(event) => setNewCombinationDescription(event.target.value)}
                          placeholder="Opcional"
                        />
                      </label>
                    </div>
                    <div className="auth-actions">
                      <button type="button" className="tab-button" onClick={handleCreateCombination}>
                        Guardar combinação atual
                      </button>
                    </div>
                    {combinationError && <p className="error">{combinationError}</p>}
                    <div className="combination-list">
                      {savedCombinations.map((item) => (
                        <article key={item.id} className="combination-row">
                          <div>
                            <strong>{item.name}</strong>
                            <p>
                              {item.owner_email} | {item.strategies.join(", ")}
                            </p>
                          </div>
                          <div className="auth-actions">
                            <button
                              type="button"
                              className="config-button"
                              onClick={() => setActiveStrategies(item.strategies)}
                            >
                              Aplicar
                            </button>
                            {item.owner_user_id !== currentUser?.id && (
                              <button
                                type="button"
                                className="config-button"
                                onClick={() => handleCloneCombination(item.id)}
                              >
                                Clonar
                              </button>
                            )}
                          </div>
                        </article>
                      ))}
                    </div>
                  </div>
                </details>
              )}

              <section className="strategy-consensus-card">
                <p className="strategy-consensus-caption">
                  O sinal combinado é calculado a partir das estratégias ativas selecionadas nos filtros
                  globais.
                </p>

                {activeStrategies.length > 0 ? (
                  <div className="strategy-summary">
                    <strong>
                      Sinal combinado:{" "}
                      <span
                        className={
                          consensus.direction === "BUY"
                            ? "consensus-buy"
                            : consensus.direction === "SELL"
                              ? "consensus-sell"
                              : "consensus-neutral"
                        }
                      >
                        {consensus.direction}
                      </span>
                    </strong>
                    <p>
                      Score {consensus.score.toFixed(3)} | Confiança {(consensus.confidence * 100).toFixed(1)}%
                    </p>
                    {orderedStrategyContributions.length > 0 && (
                      <div className="strategy-summary-contributions">
                        <div className="contributions-list">
                          {orderedStrategyContributions.map((item) => {
                            const info = STRATEGY_SUMMARY[item.strategy];
                            return (
                              <article key={item.strategy} className="contribution-row">
                                <strong>{info?.title ?? item.strategy}</strong>
                                <span
                                  className={
                                    item.direction === "BUY"
                                      ? "signal-buy"
                                      : item.direction === "SELL"
                                        ? "signal-sell"
                                        : "consensus-neutral"
                                  }
                                >
                                  {item.direction}
                                </span>
                                <span>Score {item.signedScore.toFixed(3)}</span>
                              </article>
                            );
                          })}
                        </div>
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="hint">Selecione pelo menos uma estratégia para calcular o sinal combinado.</p>
                )}
              </section>

              <p className="hint signals-filter-note">Filtros da lista (não afetam o sinal combinado).</p>
              <div className="signals-filter-grid">
                <label className="field">
                  <span>Direção</span>
                  <select
                    value={signalDirectionFilter}
                    onChange={(event) =>
                      setSignalDirectionFilter(event.target.value as SignalDirectionFilter)
                    }
                    disabled={loading}
                  >
                    <option value="BOTH">Ambos</option>
                    <option value="BUY">Buy</option>
                    <option value="SELL">Sell</option>
                  </select>
                </label>

                <label className="field">
                  <span>Força mínima (%)</span>
                  <input
                    type="number"
                    min={0}
                    max={100}
                    step={1}
                    value={signalMinStrengthPct}
                    onChange={(event) => {
                      const parsed = Number(event.target.value);
                      if (Number.isNaN(parsed)) {
                        return;
                      }
                      const normalized = Math.max(0, Math.min(100, parsed));
                      setSignalMinStrengthPct(normalized);
                    }}
                    disabled={loading}
                  />
                </label>
              </div>
              <div className="signals-filter-actions">
                <button type="button" className="config-button" onClick={handleResetSignalListFilters}>
                  Limpar filtros da lista
                </button>
                <button
                  type="button"
                  className="config-button"
                  disabled={signals.length === 0}
                  onClick={handleSignalsChartAction}
                >
                  {hasSignalsOnChart
                    ? "Sinais visíveis no gráfico"
                    : "Mostrar sinais no gráfico"}
                </button>
                {hasSignalsOnChart && (
                  <button
                    type="button"
                    className="config-button"
                    onClick={handleClearSignalsOnChart}
                  >
                    Ocultar do gráfico
                  </button>
                )}
              </div>
              {signalsChartOverlayEnabled && (
                <p className="hint">
                  Até {SIGNALS_CHART_OVERLAY_MAX} sinais da lista no Mercado (histórico). Cores por
                  estratégia.
                </p>
              )}

              <p className="hint signals-order-note">Mais recente {"->"} mais antigo.</p>
              {(signalsGenerating || signalsLoading) && <p className="hint">A atualizar sinais...</p>}
              {signalsError && <p className="error">{signalsError}</p>}
              {!signalsGenerating && !signalsLoading && signals.length === 0 && (
                <p className="hint">Sem sinais para os filtros atuais.</p>
              )}
              {signals.length > 0 && (
                <>
                  <div className="signals-list-header">
                    <span className="stats-label">Sinais ({signals.length})</span>
                    {signals.length > SIGNALS_PAGE_SIZE && (
                      <div className="backtest-trades-pagination">
                        <button
                          type="button"
                          className="config-button"
                          disabled={signalsPage <= 1}
                          onClick={() => setSignalsPage((page) => Math.max(1, page - 1))}
                        >
                          Anterior
                        </button>
                        <span className="hint">
                          {Math.min((signalsPage - 1) * SIGNALS_PAGE_SIZE + 1, signals.length)}–
                          {Math.min(signalsPage * SIGNALS_PAGE_SIZE, signals.length)} de {signals.length}
                        </span>
                        <button
                          type="button"
                          className="config-button"
                          disabled={signalsPage >= signalsTotalPages}
                          onClick={() =>
                            setSignalsPage((page) => Math.min(signalsTotalPages, page + 1))
                          }
                        >
                          Seguinte
                        </button>
                      </div>
                    )}
                  </div>
                  <div className="signals-list">
                    {paginatedSignals.map((signal) => (
                    <article key={signal.id} className="signal-row">
                      <div className="signal-main">
                        <div className="signal-top">
                          <strong className={signal.direction === "BUY" ? "signal-buy" : "signal-sell"}>
                            {signal.direction}
                          </strong>
                          <span>{STRATEGY_SUMMARY[signal.strategy]?.title ?? signal.strategy}</span>
                          <span>{formatDateTimeLabel(signal.timestamp)}</span>
                          <span>Força: {(signal.strength * 100).toFixed(1)}%</span>
                          <span className="signal-source-badge">
                            {signal.source === "live" ? "Live" : "Hist."}
                          </span>
                        </div>
                        <p>{signal.rationale}</p>
                      </div>
                      <div className="signal-row-actions">
                        <button
                          type="button"
                          className="config-button"
                          onClick={() => handleShowSignalOnChart(signal)}
                        >
                          Ver no gráfico
                        </button>
                      </div>
                    </article>
                  ))}
                  </div>
                </>
              )}
            </div>
          </div>

          <div className={activeTab === "backtests" ? "tab-pane tab-pane-active" : "tab-pane"}>
            <div className="rt-page backtests-panel">
              <div className="signals-header">
                <h3 className="section-title">Backtesting (simulação histórica)</h3>
              </div>
              <p className="hint">Configura o run, executa e compara resultados entre simulações.</p>

              {appliedReuseRun && (
                <BacktestReuseBanner
                  bannerRef={reuseBannerRef}
                  runLabel={appliedReuseRun.label}
                  summaryLines={appliedReuseRun.summaryLines}
                  canRun={canRunBacktest}
                  running={backtestRunning}
                  onRun={() => void handleRunBacktest()}
                  onDismiss={() => setAppliedReuseRun(null)}
                />
              )}

              <section className="strategy-consensus-card">
                <div className="signals-header">
                  <h3>Sinais e entrada</h3>
                </div>
                <p className="strategy-consensus-caption">
                  {activeStrategies.length > 1
                    ? "Cada estratégia activa (filtros globais) tem o seu limiar de força mínima (0–100%). O consenso final exige acordo mínimo entre as estratégias activas — quanto maior a %, menos entradas."
                    : "Defina o limiar de força mínima (0–100%) da estratégia activa. Com uma só estratégia não há consenso combinado."}
                </p>

                {activeStrategies.length > 0 ? (
                  <>
                    <div className="backtest-strength-section">
                      <span className="stats-label">
                        {activeStrategies.length > 1 ? "Limiar por estratégia" : "Limiar de força"}
                      </span>
                      <div className="backtest-strength-list">
                        {activeStrategies.map((strategy) => {
                          const strengthPct =
                            backtestStrategyMinStrengthPct[strategy] ?? DEFAULT_BACKTEST_STRENGTH_PCT;
                          const info = STRATEGY_SUMMARY[strategy];
                          return (
                            <article key={`strength-${strategy}`} className="backtest-strength-row">
                              <div className="backtest-strength-header">
                                <strong>{info?.title ?? strategy}</strong>
                                <div className="backtest-strength-values">
                                  <span className="strength-value-pct">{strengthPct}%</span>
                                  <span
                                    className={`strength-level-badge ${strengthLevelClass(strengthPct)}`}
                                  >
                                    {strengthLevelLabel(strengthPct)}
                                  </span>
                                </div>
                              </div>
                              <input
                                type="range"
                                className="strength-range"
                                min={0}
                                max={100}
                                step={5}
                                value={strengthPct}
                                onChange={(event) =>
                                  handleBacktestStrategyStrengthChange(
                                    strategy,
                                    Number(event.target.value),
                                  )
                                }
                              />
                              <div className="strength-range-labels">
                                <span>0%</span>
                                <span>100%</span>
                              </div>
                            </article>
                          );
                        })}
                      </div>
                    </div>

                    {activeStrategies.length > 1 && (
                      <div className="backtest-strength-section backtest-consensus-threshold">
                        <span className="stats-label">Limiar do sinal combinado</span>
                        <div className="backtest-strength-row">
                          <div className="backtest-strength-header">
                            <strong>Consenso final</strong>
                            <div className="backtest-strength-values">
                              <span className="strength-value-pct">{backtestConsensusStrengthPct}%</span>
                              <span
                                className={`strength-level-badge ${strengthLevelClass(backtestConsensusStrengthPct)}`}
                              >
                                {strengthLevelLabel(backtestConsensusStrengthPct)}
                              </span>
                            </div>
                          </div>
                          <input
                            type="range"
                            className="strength-range"
                            min={0}
                            max={100}
                            step={5}
                            value={backtestConsensusStrengthPct}
                            onChange={(event) =>
                              setBacktestConsensusStrengthPct(Number(event.target.value))
                            }
                          />
                          <div className="strength-range-labels">
                            <span>0%</span>
                            <span>100%</span>
                          </div>
                        </div>
                      </div>
                    )}
                  </>
                ) : (
                  <p className="hint">Selecione pelo menos uma estratégia para definir limiares.</p>
                )}

                <div className="backtests-grid backtests-entry-grid">
                  <label className="field">
                    <span>Confirmação de entrada</span>
                    <select
                      value={String(backtestEntryConfirmationBars)}
                      onChange={(event) =>
                        setBacktestEntryConfirmationBars(Number(event.target.value))
                      }
                    >
                      <option value="1">Imediata (1 vela)</option>
                      <option value="2">2 velas seguidas</option>
                      <option value="3">3 velas seguidas</option>
                      <option value="4">4 velas seguidas</option>
                      <option value="5">5 velas seguidas</option>
                    </select>
                  </label>
                  <label className="field">
                    <span>Timing de execução</span>
                    <select
                      value={backtestExecutionTiming}
                      onChange={(event) =>
                        setBacktestExecutionTiming(event.target.value as "signal_close" | "next_open")
                      }
                    >
                      <option value="next_open">Abertura da vela seguinte (entrada e saída)</option>
                      <option value="signal_close">Fecho da vela do sinal</option>
                    </select>
                  </label>
                  <label className="field">
                    <span>Modo de saída</span>
                    <select
                      value={backtestExitMode}
                      onChange={(event) =>
                        setBacktestExitMode(
                          event.target.value as "opposite_signal" | "tp_sl_or_opposite" | "tp_sl_only",
                        )
                      }
                    >
                      <option value="opposite_signal">Só sinal oposto</option>
                      <option value="tp_sl_or_opposite">TP/SL + sinal oposto</option>
                      <option value="tp_sl_only">Só TP/SL</option>
                    </select>
                  </label>
                </div>
              </section>

              <section className="strategy-consensus-card">
                <div className="signals-header">
                  <h3>Execução e risco</h3>
                </div>
                <div className="backtests-grid">
                  <label className="field">
                    <span>Capital inicial</span>
                    <input
                      type="number"
                      min={100}
                      max={10000000}
                      step={100}
                      value={backtestInitialCapital}
                      onChange={(event) => setBacktestInitialCapital(Number(event.target.value))}
                    />
                  </label>
                  <label className="field">
                    <span>Modelo de tamanho</span>
                    <select
                      value={backtestPositionSizingModel}
                      onChange={(event) =>
                        setBacktestPositionSizingModel(event.target.value as "fixed_pct" | "atr_risk")
                      }
                    >
                      <option value="fixed_pct">% fixo do capital</option>
                      <option value="atr_risk">Risco por trade (ATR/SL)</option>
                    </select>
                  </label>
                  {backtestPositionSizingModel === "fixed_pct" ? (
                    <label className="field">
                      <span>% do capital por trade</span>
                      <input
                        type="number"
                        min={1}
                        max={100}
                        step={1}
                        value={backtestPositionSizePct}
                        onChange={(event) => setBacktestPositionSizePct(Number(event.target.value))}
                      />
                    </label>
                  ) : (
                    <>
                      <label className="field">
                        <span>Risco por trade (%)</span>
                        <input
                          type="number"
                          min={0.1}
                          max={100}
                          step={0.1}
                          value={backtestRiskPerTradePct}
                          onChange={(event) => setBacktestRiskPerTradePct(Number(event.target.value))}
                        />
                      </label>
                      <label className="field">
                        <span>Teto (% capital)</span>
                        <input
                          type="number"
                          min={1}
                          max={100}
                          step={1}
                          value={backtestPositionSizePct}
                          onChange={(event) => setBacktestPositionSizePct(Number(event.target.value))}
                        />
                      </label>
                    </>
                  )}
                  <label className="field">
                    <span>Modelo de fees</span>
                    <select
                      value={backtestFeeModel}
                      onChange={(event) =>
                        setBacktestFeeModel(event.target.value as "fixed_bps" | "ibkr_us_tiered")
                      }
                    >
                      <option value="fixed_bps">Bps fixos</option>
                      <option value="ibkr_us_tiered">IBKR US tiered</option>
                    </select>
                  </label>
                  <label className="field">
                    <span>Fee (bps)</span>
                    <input
                      type="number"
                      min={0}
                      max={500}
                      step={0.5}
                      value={backtestFeeBps}
                      onChange={(event) => setBacktestFeeBps(Number(event.target.value))}
                      disabled={backtestFeeModel === "ibkr_us_tiered"}
                    />
                  </label>
                  <label className="field">
                    <span>Slippage (bps)</span>
                    <input
                      type="number"
                      min={0}
                      max={500}
                      step={0.5}
                      value={backtestSlippageBps}
                      onChange={(event) => setBacktestSlippageBps(Number(event.target.value))}
                    />
                  </label>
                  <label className="field">
                    <span>Modelo slippage</span>
                    <select
                      value={backtestSlippageModel}
                      onChange={(event) =>
                        setBacktestSlippageModel(event.target.value as "fixed" | "atr_volume")
                      }
                    >
                      <option value="atr_volume">Dinâmico (ATR + volume)</option>
                      <option value="fixed">Fixo</option>
                    </select>
                  </label>
                  <label className="field">
                    <span>Stop-loss (%)</span>
                    <input
                      type="number"
                      min={0.1}
                      max={100}
                      step={0.1}
                      value={backtestStopLossPct}
                      onChange={(event) => setBacktestStopLossPct(Number(event.target.value))}
                      disabled={backtestExitMode === "opposite_signal"}
                    />
                  </label>
                  <label className="field">
                    <span>Take-profit (%)</span>
                    <input
                      type="number"
                      min={0.1}
                      max={200}
                      step={0.1}
                      value={backtestTakeProfitPct}
                      onChange={(event) => setBacktestTakeProfitPct(Number(event.target.value))}
                      disabled={backtestExitMode === "opposite_signal"}
                    />
                  </label>
                  <label className="field">
                    <span>Máx. barras por trade</span>
                    <input
                      type="number"
                      min={1}
                      max={500}
                      step={1}
                      value={backtestMaxBarsInTrade}
                      onChange={(event) => setBacktestMaxBarsInTrade(Number(event.target.value))}
                    />
                  </label>
                  {(periodMode === "date" || periodMode === "bars") && (
                    <label className="field">
                      <span>{periodMode === "bars" ? "Número de velas" : "Limite máx. de velas"}</span>
                      <input
                        type="number"
                        min={200}
                        max={10000}
                        step={100}
                        value={backtestLimit}
                        onChange={(event) => setBacktestLimit(Number(event.target.value))}
                      />
                    </label>
                  )}
                  <label className="field">
                    <span>Walk-forward OOS (%)</span>
                    <input
                      type="number"
                      min={0}
                      max={80}
                      step={5}
                      value={backtestWalkforwardSplitPct}
                      onChange={(event) => setBacktestWalkforwardSplitPct(Number(event.target.value))}
                    />
                  </label>
                  <label className="field">
                    <span>Modo walk-forward</span>
                    <select
                      value={backtestWalkforwardMode}
                      onChange={(event) =>
                        setBacktestWalkforwardMode(event.target.value as "holdout" | "rolling")
                      }
                      disabled={backtestWalkforwardSplitPct <= 0}
                    >
                      <option value="holdout">Holdout único</option>
                      <option value="rolling">Rolling (vários blocos)</option>
                    </select>
                  </label>
                  {backtestWalkforwardMode === "rolling" && backtestWalkforwardSplitPct > 0 && (
                    <label className="field">
                      <span>Folds rolling</span>
                      <input
                        type="number"
                        min={1}
                        max={8}
                        step={1}
                        value={backtestWalkforwardFolds}
                        onChange={(event) => setBacktestWalkforwardFolds(Number(event.target.value))}
                      />
                    </label>
                  )}
                  <label className="field">
                    <span>Benchmark buy & hold</span>
                    <select
                      value={backtestBenchmarkEnabled ? "on" : "off"}
                      onChange={(event) => setBacktestBenchmarkEnabled(event.target.value === "on")}
                    >
                      <option value="on">Ativo</option>
                      <option value="off">Desligado</option>
                    </select>
                  </label>
                </div>

                <section className="backtest-run-bar">
                  <div className="backtest-run-bar-main">
                    <button
                      type="button"
                      className="tab-button backtest-run-bar-button"
                      onClick={handleRunBacktest}
                      disabled={!canRunBacktest}
                    >
                      {backtestRunning ? "A correr..." : "Correr backtest"}
                    </button>
                    {backtestRunStatusLine && (
                      <p className={`backtest-run-bar-status backtest-run-bar-status-${backtestRunStatusTone}`}>
                        {backtestRunStatusLine}
                      </p>
                    )}
                  </div>
                </section>
              </section>

              {backtestError && <p className="error">{backtestError}</p>}

              <section className="backtest-workspace">
                <BacktestWorkspaceTabBar
                  active={backtestWorkspaceTab}
                  items={backtestWorkspaceTabItems}
                  onChange={setBacktestWorkspaceTab}
                />

                {backtestWorkspaceTab === "data" && (
                  <BacktestWorkspacePane
                    title="Dados de mercado"
                    description="Velas disponíveis para o símbolo e timeframe activos nos filtros globais."
                    loading={backtestDataAvailability.status === "loading"}
                    loadingMessage="A verificar velas disponíveis..."
                  >
                    <article className="backtest-workspace-card">
                      <div className="backtest-workspace-card-head">
                        <span className="stats-label">Estado</span>
                        {backtestDataAvailability.status === "ready" && (
                          <span className="backtest-support-pill backtest-support-pill-ok">OK</span>
                        )}
                        {backtestDataAvailability.status === "partial_window" && (
                          <span className="backtest-support-pill backtest-support-pill-warn">Parcial</span>
                        )}
                      </div>
                      {backtestDataAvailability.status === "ready" && (
                        <p className="hint backtest-data-ready">
                          <strong>{backtestDataAvailability.availableBars}</strong> velas para{" "}
                          <strong>
                            {backtestDataAvailability.symbol} / {backtestDataAvailability.timeframe}
                          </strong>
                          .
                        </p>
                      )}
                      {backtestDataAvailability.status === "partial_window" && (
                        <p className="hint backtest-data-partial">
                          Há <strong>{backtestDataAvailability.availableBars}</strong> velas (pediste{" "}
                          {backtestDataAvailability.requestedBars}); o backtest usará só as disponíveis.
                        </p>
                      )}
                      {(backtestDataAvailability.status === "no_instrument" ||
                        backtestDataAvailability.status === "no_bars" ||
                        backtestDataAvailability.status === "insufficient_bars") && (
                        <div className="backtest-data-banner backtest-data-banner-warning">
                          {backtestDataAvailability.status === "no_instrument" && (
                            <p>
                              <strong>{backtestDataAvailability.symbol}</strong> não está na base de dados para{" "}
                              <strong>{backtestDataAvailability.timeframe}</strong>.
                            </p>
                          )}
                          {backtestDataAvailability.status === "no_bars" && (
                            <p>
                              Sem velas para <strong>{backtestDataAvailability.symbol}</strong> /{" "}
                              <strong>{backtestDataAvailability.timeframe}</strong>
                              {periodMode === "date"
                                ? ` no intervalo ${startDate} – ${endDate}.`
                                : "."}
                            </p>
                          )}
                          {backtestDataAvailability.status === "insufficient_bars" && (
                            <p>
                              Só <strong>{backtestDataAvailability.availableBars}</strong> velas; são necessárias
                              pelo menos <strong>{backtestDataAvailability.requiredBars}</strong>.
                            </p>
                          )}
                        </div>
                      )}
                      <div className="backtest-workspace-card-actions">
                        <button
                          type="button"
                          className="tab-button"
                          onClick={() => void handleLoadDemoMarketData()}
                          disabled={demoDataLoading || !selectedSymbol}
                        >
                          {demoDataLoading
                            ? "A importar..."
                            : backtestDataAvailability.status === "ready" ||
                                backtestDataAvailability.status === "partial_window"
                              ? "Atualizar demo (Yahoo)"
                              : "Carregar demo (Yahoo)"}
                        </button>
                      </div>
                    </article>
                  </BacktestWorkspacePane>
                )}

                {backtestWorkspaceTab === "recommendations" && (
                  <BacktestWorkspacePane
                    title="Recomendações"
                    description="Sugestões do motor com base no último run do símbolo. Aplica ao formulário e corre de novo para validar."
                    loading={backtestRecommendationsLoading}
                    loadingMessage="A carregar recomendações..."
                    isEmpty={!backtestRecommendationsLoading && backtestRecommendations.length === 0}
                    emptyMessage={`Ainda sem recomendações para ${selectedSymbol}.`}
                  >
                    {pendingFormChangesSummary.length > 0 && (
                      <div className="backtest-pending-changes-panel">
                        <strong className="stats-label">
                          Alterações aplicadas ao formulário (ainda não simuladas)
                        </strong>
                        <ul className="backtest-pending-changes-list">
                          {pendingFormChangesSummary.map((line) => (
                            <li key={line}>{line}</li>
                          ))}
                        </ul>
                        <p className="hint">
                          {fulfilledRecommendationsCount} alteração(ões) no formulário. Corre a simulação
                          para validar.
                        </p>
                      </div>
                    )}
                    <BacktestRecommendationsPicker
                      recommendations={backtestRecommendations}
                      snapshot={backtestFormSnapshot}
                      appliedRecords={appliedRecommendations}
                      loading={backtestRecommendationsLoading}
                      symbol={selectedSymbol}
                      sourceRunLabel={recommendationSourceRunLabel}
                      barCountsByTimeframe={recommendationBarCounts}
                      latestSymbolRun={latestSymbolBacktestRun}
                      setters={backtestRecommendationSetters}
                      onApplied={handleApplySelectedRecommendations}
                      onError={(message) => setBacktestError(message || null)}
                      onViewRun={(runId) => void handleViewLessonRun(runId)}
                    />
                  </BacktestWorkspacePane>
                )}

                {backtestWorkspaceTab === "presets" && (
                  <BacktestWorkspacePane
                    title="Presets"
                    description="Configurações guardadas localmente no browser. Aplicar repõe parâmetros como no Reutilizar."
                    isEmpty={backtestPresets.length === 0}
                    emptyMessage="Ainda sem presets guardados."
                  >
                    <div className="backtest-workspace-card">
                      <div className="backtest-preset-save-row">
                        <label className="field backtest-preset-name-field">
                          <span>Nome do preset</span>
                          <input
                            value={backtestPresetName}
                            onChange={(event) => setBacktestPresetName(event.target.value)}
                            placeholder="Ex.: Reversão diária conservadora"
                          />
                        </label>
                        <button type="button" className="tab-button" onClick={handleSaveBacktestPreset}>
                          Guardar atual
                        </button>
                      </div>
                      {backtestPresets.length > 0 && (
                        <div className="combination-list">
                          {backtestPresets.map((preset) => (
                            <article key={preset.id} className="combination-row">
                              <div>
                                <strong>{preset.name}</strong>
                                <p>
                                  {normalizeBacktestPreset(preset).strategies
                                    .map((strategy) => STRATEGY_SUMMARY[strategy]?.title ?? strategy)
                                    .join(", ")}
                                </p>
                              </div>
                              <div className="auth-actions">
                                <button
                                  type="button"
                                  className="config-button"
                                  onClick={() => handleApplyBacktestPreset(preset.id)}
                                >
                                  Aplicar
                                </button>
                              </div>
                            </article>
                          ))}
                        </div>
                      )}
                    </div>
                  </BacktestWorkspacePane>
                )}

                {backtestWorkspaceTab === "lessons" && (
                  <BacktestWorkspacePane
                    title="Lições"
                    description={`Memória crítica extraída dos insights (até ${BACKTEST_LESSONS_FETCH_LIMIT} entradas recentes por símbolo — não é arquivo completo de todas as runs).`}
                    toolbar={workspaceDateToolbar}
                    footer={
                      <BacktestWorkspacePagination
                        page={backtestLessonsPage}
                        pageSize={BACKTEST_LESSONS_PAGE_SIZE}
                        totalItems={sortedBacktestLessons.length}
                        onPageChange={setBacktestLessonsPage}
                      />
                    }
                    loading={backtestLessonsLoading}
                    loadingMessage="A carregar lições..."
                    isEmpty={
                      !backtestLessonsLoading &&
                      !workspaceDateFilterInvalid &&
                      sortedBacktestLessons.length === 0
                    }
                    emptyMessage={
                      workspaceDateFilterInvalid
                        ? "Intervalo de datas inválido."
                        : `Ainda sem lições para ${selectedSymbol} neste período.`
                    }
                  >
                    <ul className="backtest-lessons-list">
                      {paginatedBacktestLessons.map((lesson) => {
                        const relevant = isBacktestLessonRelevant(lesson, activeStrategies);
                        const strategyLabel = lesson.strategy_names
                          .map((name) => STRATEGY_SUMMARY[name]?.title ?? name)
                          .join(" · ");
                        return (
                          <li
                            key={`${lesson.run_id}-${lesson.title}`}
                            className={`backtest-lesson-item backtest-lesson-priority-${lesson.priority.toLowerCase()}`}
                          >
                            <div className="backtest-lesson-header">
                              <strong>{lesson.title}</strong>
                              {relevant && <span className="backtest-lesson-badge">Relevante</span>}
                            </div>
                            <p>{lesson.detail}</p>
                            <div className="backtest-lesson-footer">
                              <span className="hint">
                                Run #{lesson.run_id} · {strategyLabel} ·{" "}
                                {formatDateTimeLabel(lesson.created_at)} · {lesson.priority}
                              </span>
                              <button
                                type="button"
                                className="config-button"
                                onClick={() => void handleViewLessonRun(lesson.run_id)}
                              >
                                Ver run
                              </button>
                            </div>
                          </li>
                        );
                      })}
                    </ul>
                  </BacktestWorkspacePane>
                )}

                {backtestWorkspaceTab === "results" && (
                  <BacktestWorkspacePane
                    title="Resultados"
                    description="Histórico de simulações. Selecione até 2 runs para comparar. Use Detalhe para config, gráfico de equity e trades."
                    toolbar={workspaceDateToolbar}
                    footer={
                      <BacktestWorkspacePagination
                        page={backtestRunsPage}
                        pageSize={BACKTEST_RUNS_PAGE_SIZE}
                        totalItems={backtestRuns.length}
                        onPageChange={setBacktestRunsPage}
                      />
                    }
                    loading={backtestLoading}
                    loadingMessage="A carregar histórico..."
                    isEmpty={
                      !backtestLoading && !workspaceDateFilterInvalid && backtestRuns.length === 0
                    }
                    emptyMessage={
                      workspaceDateFilterInvalid
                        ? "Intervalo de datas inválido."
                        : "Ainda sem simulações para este símbolo neste período."
                    }
                  >
                    <div className="backtest-runs-list">
                      {paginatedBacktestRuns.map((run) => {
                      const runTone =
                        run.trades_count === 0
                          ? "neutral"
                          : run.net_pnl > 0
                            ? "positive"
                            : run.net_pnl < 0
                              ? "negative"
                              : "neutral";
                      const isDetailOpen = backtestSelectedRun?.id === run.id;
                      const strategyLabel = run.strategy_names
                        .map((name) => STRATEGY_SUMMARY[name]?.title ?? name)
                        .join(" · ");
                      return (
                        <div key={run.id} className="backtest-run-entry">
                          <article
                            className={`backtest-run-card backtest-run-card-${runTone}${
                              appliedReuseRun?.runId === run.id ? " backtest-run-card-reused" : ""
                            }`}
                          >
                            <div className="backtest-run-main">
                              <div className="backtest-run-line">
                                <strong>{formatBacktestRunLabel(run)}</strong>
                                {appliedReuseRun?.runId === run.id && (
                                  <span className="backtest-run-reused-badge">Aplicado</span>
                                )}
                                <span className="backtest-run-muted">
                                  {formatDateTimeLabel(run.created_at)}
                                </span>
                                <span className="backtest-run-sep">·</span>
                                <span className="backtest-run-muted">{strategyLabel}</span>
                                <span className="backtest-run-sep">·</span>
                                <span className="backtest-run-muted">
                                  {run.bars_processed} barras · {run.trades_count} trades · Win{" "}
                                  {(run.win_rate * 100).toFixed(0)}% · DD{" "}
                                  {(run.max_drawdown_pct * 100).toFixed(1)}%
                                </span>
                              </div>
                              {run.insight_summary && (
                                <p className="hint backtest-run-insight-summary">{run.insight_summary}</p>
                              )}
                            </div>
                            <div className="backtest-run-pnl">
                              <strong
                                className={
                                  run.trades_count === 0
                                    ? "backtest-run-pnl-flat"
                                    : run.net_pnl >= 0
                                      ? "signal-buy"
                                      : "signal-sell"
                                }
                              >
                                {(run.net_pnl_pct * 100).toFixed(2)}%
                              </strong>
                              <span className="backtest-run-pnl-abs">{run.net_pnl.toFixed(2)}</span>
                            </div>
                            <div className="backtest-run-actions">
                              <label className="backtest-compare-toggle">
                                <input
                                  type="checkbox"
                                  checked={backtestCompareRunIds.includes(run.id)}
                                  onChange={() => handleToggleCompareRun(run.id)}
                                />
                                <span>Comparar</span>
                              </label>
                              <button
                                type="button"
                                className={
                                  isDetailOpen
                                    ? "backtest-detail-button backtest-detail-button-active"
                                    : "backtest-detail-button"
                                }
                                onClick={() => void handleToggleBacktestRunDetail(run.id)}
                              >
                                {isDetailOpen ? "Ocultar" : "Detalhe"}
                              </button>
                              <button
                                type="button"
                                className="config-button"
                                onClick={() => handleApplyBacktestRunConfig(run)}
                              >
                                Reutilizar
                              </button>
                              {run.trades_count > 0 && (
                                <button
                                  type="button"
                                  className="config-button"
                                  onClick={() => void handleShowBacktestTradesOnChart(run)}
                                >
                                  Gráfico
                                </button>
                              )}
                              <button
                                type="button"
                                className="config-button backtest-delete-button"
                                onClick={() => void handleDeleteBacktestRun(run.id)}
                              >
                                Apagar
                              </button>
                            </div>
                          </article>
                          {isDetailOpen && backtestSelectedRun && renderBacktestRunDetail(backtestSelectedRun)}
                        </div>
                      );
                    })}
                    </div>

                    {comparedBacktestRuns.length === 2 && (
                      <BacktestRunComparePanel
                        left={comparedBacktestRuns[0]}
                        right={comparedBacktestRuns[1]}
                      />
                    )}
                    {comparedBacktestRuns.length === 1 && (
                      <p className="hint backtest-compare-hint">
                        Selecciona mais um run com <strong>Comparar</strong> para ver diferenças de dados,
                        configuração e resultado.
                      </p>
                    )}
                  </BacktestWorkspacePane>
                )}

              </section>
            </div>
          </div>

        </div>
      </section>
      </div>
      )}
    </main>
  );
}

export default App;
