import {
  CandlestickSeries,
  LineSeries,
  createChart,
  type CandlestickData,
  type LineData,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import { BacktestEquityChart, type EquityCurvePoint } from "./BacktestEquityChart";

type Instrument = {
  id: number;
  symbol: string;
  name: string | null;
  exchange: string | null;
  currency: string;
};

type ApiBar = {
  timestamp: string;
  open: string;
  high: string;
  low: string;
  close: string;
  volume: string;
};

type OhlcDetails = {
  dateLabel: string;
  open: number;
  high: number;
  low: number;
  close: number;
};

type IndicatorRow = {
  timestamp: string;
  sma_20: number | null;
  ema_20: number | null;
  rsi_14: number | null;
  macd: number | null;
  macd_signal: number | null;
  macd_histogram: number | null;
  bollinger_upper: number | null;
  bollinger_middle: number | null;
  bollinger_lower: number | null;
  atr_14: number | null;
  vwap: number | null;
  relative_volume_20: number | null;
};

type FilterMode = "count" | "date";
type ViewTab = "market" | "signals" | "backtests";
type SignalDirectionFilter = "BOTH" | "BUY" | "SELL";
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
  trades?: BacktestTrade[];
};

type BacktestPreset = {
  id: string;
  name: string;
  strategies: string[];
  initialCapital: number;
  feeBps: number;
  slippageBps: number;
  strategyMinStrengthPct: Record<string, number>;
  consensusStrengthPct: number;
  /** @deprecated legacy single threshold */
  minStrengthPct?: number;
  limit: number;
  positionSizePct: number;
  entryConfirmationBars: number;
  exitMode: "opposite_signal" | "tp_sl_or_opposite" | "tp_sl_only";
  stopLossPct: number | null;
  takeProfitPct: number | null;
  maxBarsInTrade: number | null;
  walkforwardSplitPct: number;
  benchmarkEnabled: boolean;
};

const DEFAULT_BACKTEST_STRENGTH_PCT = 10;
const BACKTEST_MIN_BARS = 200;

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

const getControlsContextLabel = (tab: ViewTab, windowMode: FilterMode): string => {
  if (tab === "market") {
    return "Filtros do gráfico.";
  }
  if (tab === "signals") {
    return "Período de geração dos sinais.";
  }
  if (windowMode === "date") {
    return "Período da simulação: datas definidas acima.";
  }
  return "Período da simulação: Nº velas definido acima.";
};

const normalizeBacktestPreset = (item: BacktestPreset): BacktestPreset => {
  const legacyStrength = item.minStrengthPct ?? item.consensusStrengthPct ?? DEFAULT_BACKTEST_STRENGTH_PCT;
  const consensusStrengthPct = item.consensusStrengthPct ?? legacyStrength;
  const strategyMinStrengthPct = { ...(item.strategyMinStrengthPct ?? {}) };
  for (const strategy of item.strategies) {
    if (strategyMinStrengthPct[strategy] === undefined) {
      strategyMinStrengthPct[strategy] = legacyStrength;
    }
  }
  return {
    ...item,
    consensusStrengthPct,
    strategyMinStrengthPct,
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

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const AUTH_TOKEN_STORAGE_KEY = "trading_auth_token";
const CONSENSUS_THRESHOLD_STORAGE_KEY = "trading_consensus_threshold_pct";
const SIGNALS_FETCH_LIMIT_STORAGE_KEY = "trading_signals_fetch_limit";
const BACKTEST_PRESETS_STORAGE_KEY = "trading_backtest_presets";

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

const buildStrategyStrengthPctFromRun = (run: BacktestRun, config: Record<string, unknown>) => {
  const fallbackPct = Math.round(run.min_signal_strength * 100);
  const rawStrengths = config.strategy_min_strengths;
  if (!rawStrengths || typeof rawStrengths !== "object") {
    return Object.fromEntries(run.strategy_names.map((strategy) => [strategy, fallbackPct]));
  }
  return Object.fromEntries(
    run.strategy_names.map((strategy) => {
      const value = (rawStrengths as Record<string, unknown>)[strategy];
      return [strategy, typeof value === "number" ? Math.round(value * 100) : fallbackPct];
    }),
  );
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

const toChartDate = (dateText: string): string =>
  new Date(dateText).toISOString().slice(0, 10);

const toInputDate = (date: Date): string => date.toISOString().slice(0, 10);

const toLineData = (rows: IndicatorRow[], field: keyof IndicatorRow): LineData[] =>
  rows.flatMap((row) =>
    row[field] === null ? [] : [{ time: toChartDate(row.timestamp), value: Number(row[field]) }],
  );

const formatIndicatorValue = (
  value: number | null,
  loadedBars: number,
  minimumBars: number,
): string => {
  if (value !== null) {
    return formatPrice(value);
  }
  if (loadedBars < minimumBars) {
    return "Poucos dados";
  }
  return "-";
};

function App() {
  const chartContainerRef = useRef<HTMLDivElement | null>(null);
  const [authToken, setAuthToken] = useState<string>(() => localStorage.getItem(AUTH_TOKEN_STORAGE_KEY) ?? "");
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null);
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [showAuthPanel, setShowAuthPanel] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [authLoading, setAuthLoading] = useState(false);
  const [authChecking, setAuthChecking] = useState(false);

  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<string>("");
  const [selectedTimeframe, setSelectedTimeframe] = useState<string>("1d");
  const [activeTab, setActiveTab] = useState<ViewTab>("market");
  const [showConfigPanel, setShowConfigPanel] = useState(false);
  const [activeConfigTab, setActiveConfigTab] = useState<ConfigTab>("signals");
  const [filterMode, setFilterMode] = useState<FilterMode>("count");
  const [barLimit, setBarLimit] = useState<number>(500);
  const [barLimitInput, setBarLimitInput] = useState<string>("500");
  const [startDate, setStartDate] = useState<string>(
    toInputDate(new Date(Date.now() - 365 * 24 * 60 * 60 * 1000)),
  );
  const [endDate, setEndDate] = useState<string>(toInputDate(new Date()));
  const [bars, setBars] = useState<ApiBar[]>([]);
  const [indicatorRows, setIndicatorRows] = useState<IndicatorRow[]>([]);
  const [availableStrategies, setAvailableStrategies] = useState<string[]>([]);
  const [selectedStrategies, setSelectedStrategies] = useState<string[]>([]);
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
  const [signalsRefreshToken, setSignalsRefreshToken] = useState(0);
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
  const [backtestStrategies, setBacktestStrategies] = useState<string[]>([]);
  const [backtestInitialCapital, setBacktestInitialCapital] = useState<number>(10000);
  const [backtestFeeBps, setBacktestFeeBps] = useState<number>(5);
  const [backtestSlippageBps, setBacktestSlippageBps] = useState<number>(2);
  const [backtestStrategyMinStrengthPct, setBacktestStrategyMinStrengthPct] = useState<
    Record<string, number>
  >({});
  const [backtestConsensusStrengthPct, setBacktestConsensusStrengthPct] = useState<number>(
    DEFAULT_BACKTEST_STRENGTH_PCT,
  );
  const [backtestLimit, setBacktestLimit] = useState<number>(2000);
  const [backtestPositionSizePct, setBacktestPositionSizePct] = useState<number>(100);
  const [backtestEntryConfirmationBars, setBacktestEntryConfirmationBars] = useState<number>(1);
  const [backtestExitMode, setBacktestExitMode] = useState<
    "opposite_signal" | "tp_sl_or_opposite" | "tp_sl_only"
  >("tp_sl_or_opposite");
  const [backtestStopLossPct, setBacktestStopLossPct] = useState<number>(2);
  const [backtestTakeProfitPct, setBacktestTakeProfitPct] = useState<number>(4);
  const [backtestMaxBarsInTrade, setBacktestMaxBarsInTrade] = useState<number>(40);
  const [backtestWalkforwardSplitPct, setBacktestWalkforwardSplitPct] = useState<number>(0);
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
  const [marketDataRefreshToken, setMarketDataRefreshToken] = useState(0);
  const [demoDataLoading, setDemoDataLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hoveredOhlc, setHoveredOhlc] = useState<OhlcDetails | null>(null);
  const [overlayVisibility, setOverlayVisibility] = useState({
    sma20: true,
    ema20: true,
    bollinger: true,
    vwap: true,
  });

  const isDateFilterIncomplete = filterMode === "date" && (!startDate || !endDate);
  const isDateRangeInvalid = filterMode === "date" && !isDateFilterIncomplete && startDate > endDate;
  const hasDateFilterError = isDateFilterIncomplete || isDateRangeInvalid;

  const buildMarketQueryParams = (): URLSearchParams => {
    const query = new URLSearchParams({
      symbol: selectedSymbol,
      timeframe: selectedTimeframe,
    });

    if (filterMode === "count") {
      query.set("limit", String(barLimit));
    } else {
      query.set("start", `${startDate}T00:00:00Z`);
      query.set("end", `${endDate}T23:59:59Z`);
    }
    return query;
  };

  useEffect(() => {
    setBarLimitInput(String(barLimit));
  }, [barLimit]);

  useEffect(() => {
    localStorage.setItem(CONSENSUS_THRESHOLD_STORAGE_KEY, String(consensusThresholdPct));
  }, [consensusThresholdPct]);

  useEffect(() => {
    localStorage.setItem(SIGNALS_FETCH_LIMIT_STORAGE_KEY, String(signalsFetchLimit));
  }, [signalsFetchLimit]);

  useEffect(() => {
    localStorage.setItem(BACKTEST_PRESETS_STORAGE_KEY, JSON.stringify(backtestPresets));
  }, [backtestPresets]);

  const buildSignalGeneratePayload = (strategy: string): Record<string, string | number> => {
    const payload: Record<string, string | number> = {
      symbol: selectedSymbol,
      timeframe: selectedTimeframe,
      strategy,
    };
    if (filterMode === "count") {
      payload.limit = barLimit;
    } else {
      payload.start = `${startDate}T00:00:00Z`;
      payload.end = `${endDate}T23:59:59Z`;
      payload.limit = 5000;
    }
    return payload;
  };

  const isAuthenticated = Boolean(authToken && currentUser);

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
        if (payload.length > 0) {
          setSelectedSymbol(payload[0].symbol);
        }
      } catch (loadError) {
        const message =
          loadError instanceof Error ? loadError.message : "Erro inesperado ao carregar instrumentos.";
        setError(message);
      } finally {
        setLoading(false);
      }
    };

    loadInstruments();
  }, [isAuthenticated, authToken, marketDataRefreshToken]);

  useEffect(() => {
    if (!isAuthenticated) {
      setAvailableStrategies([]);
      setSelectedStrategies([]);
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
        if (payload.length > 0) {
          setSelectedStrategies([payload[0]]);
          setBacktestStrategies([payload[0]]);
        }
      } catch {
        setAvailableStrategies([]);
        setSelectedStrategies([]);
        setBacktestStrategies([]);
      }
    };

    loadStrategies();
  }, [isAuthenticated, authToken]);

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
        const query = new URLSearchParams({ limit: "30" });
        if (selectedSymbol) {
          query.set("symbol", selectedSymbol);
          query.set("timeframe", selectedTimeframe);
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
  }, [authToken, isAuthenticated, backtestRefreshToken, selectedSymbol, selectedTimeframe]);

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
        const message = loadError instanceof Error ? loadError.message : "Erro inesperado ao carregar velas.";
        setError(message);
      } finally {
        setLoading(false);
      }
    };

    loadBars();
  }, [
    selectedSymbol,
    selectedTimeframe,
    barLimit,
    filterMode,
    startDate,
    endDate,
    hasDateFilterError,
    authToken,
    marketDataRefreshToken,
  ]);

  useEffect(() => {
    if (!selectedSymbol) {
      setIndicatorRows([]);
      return;
    }
    if (hasDateFilterError) {
      setIndicatorRows([]);
      return;
    }

    const loadIndicators = async () => {
      try {
        const query = buildMarketQueryParams();
        const response = await fetch(`${API_BASE_URL}/market-data/indicators?${query.toString()}`, {
          headers: { Authorization: `Bearer ${authToken}` },
        });
        if (!response.ok) {
          throw new Error("Falha ao carregar indicadores.");
        }
        const payload = (await response.json()) as { rows: IndicatorRow[] };
        setIndicatorRows(payload.rows);
      } catch {
        setIndicatorRows([]);
      }
    };

    loadIndicators();
  }, [selectedSymbol, selectedTimeframe, barLimit, filterMode, startDate, endDate, hasDateFilterError, authToken]);

  useEffect(() => {
    if (!isAuthenticated || !selectedSymbol || selectedStrategies.length === 0) {
      setSignals([]);
      setSignalsGenerating(false);
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
          selectedStrategies.map((strategy) =>
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
    selectedStrategies,
    filterMode,
    barLimit,
    startDate,
    endDate,
    hasDateFilterError,
  ]);

  useEffect(() => {
    if (!isAuthenticated || !selectedSymbol || selectedStrategies.length === 0) {
      setSignals([]);
      setConsensusSignals([]);
      return;
    }
    if (signalsGenerating) {
      return;
    }

    const loadConsensusSignals = async () => {
      try {
        const responses = await Promise.all(
          selectedStrategies.map(async (strategy) => {
            const query = new URLSearchParams({
              symbol: selectedSymbol,
              timeframe: selectedTimeframe,
              strategy,
              limit: "1",
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
    selectedStrategies,
    signalsRefreshToken,
    signalsGenerating,
  ]);

  useEffect(() => {
    if (!isAuthenticated || !selectedSymbol || selectedStrategies.length === 0) {
      setSignals([]);
      return;
    }
    if (signalsGenerating) {
      return;
    }

    const loadSignals = async () => {
      setSignalsLoading(true);
      try {
        const responses = await Promise.all(
          selectedStrategies.map(async (strategy) => {
            const query = new URLSearchParams({
              symbol: selectedSymbol,
              timeframe: selectedTimeframe,
              strategy,
              limit: String(signalsFetchLimit),
              min_strength: String(signalMinStrengthPct / 100),
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
    selectedStrategies,
    signalDirectionFilter,
    signalMinStrengthPct,
    signalsFetchLimit,
    signalsRefreshToken,
    signalsGenerating,
  ]);

  const chartData = useMemo<CandlestickData[]>(() => {
    return bars.map((bar) => ({
      time: toChartDate(bar.timestamp),
      open: Number(bar.open),
      high: Number(bar.high),
      low: Number(bar.low),
      close: Number(bar.close),
    }));
  }, [bars]);

  const sma20Data = useMemo(() => toLineData(indicatorRows, "sma_20"), [indicatorRows]);
  const ema20Data = useMemo(() => toLineData(indicatorRows, "ema_20"), [indicatorRows]);
  const vwapData = useMemo(() => toLineData(indicatorRows, "vwap"), [indicatorRows]);
  const bollingerUpperData = useMemo(() => toLineData(indicatorRows, "bollinger_upper"), [indicatorRows]);
  const bollingerMiddleData = useMemo(() => toLineData(indicatorRows, "bollinger_middle"), [indicatorRows]);
  const bollingerLowerData = useMemo(() => toLineData(indicatorRows, "bollinger_lower"), [indicatorRows]);

  const lastBar = bars.length > 0 ? bars[bars.length - 1] : null;
  const lastIndicatorRow = indicatorRows.length > 0 ? indicatorRows[indicatorRows.length - 1] : null;
  const fallbackOhlc = lastBar
    ? {
        dateLabel: formatDateLabel(lastBar.timestamp),
        open: Number(lastBar.open),
        high: Number(lastBar.high),
        low: Number(lastBar.low),
        close: Number(lastBar.close),
      }
    : null;

  const visibleOhlc = hoveredOhlc ?? fallbackOhlc;
  const barsSummaryLabel = filterMode === "count" ? "Velas carregadas" : "Velas no período";
  const barsSummaryValue = filterMode === "count" ? `${bars.length} / ${barLimit}` : String(bars.length);
  const strategyContributions = useMemo<StrategyContribution[]>(() => {
    return selectedStrategies.map((strategy) => {
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
  }, [selectedStrategies, consensusSignals]);

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

  const simulationBarLimit = filterMode === "count" ? barLimit : backtestLimit;

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
    backtestStrategies.length > 0 &&
    !backtestRunning &&
    (backtestDataAvailability.status === "ready" || backtestDataAvailability.status === "partial_window");

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
    if (!authToken || selectedStrategies.length === 0 || !newCombinationName.trim()) {
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
          strategies: selectedStrategies,
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
    if (!authToken || !selectedSymbol || backtestStrategies.length === 0) {
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
    setBacktestError(null);
    setBacktestSelectedRun(null);
    try {
      const strategyMinStrengths = Object.fromEntries(
        backtestStrategies.map((strategy) => [
          strategy,
          (backtestStrategyMinStrengthPct[strategy] ?? DEFAULT_BACKTEST_STRENGTH_PCT) / 100,
        ]),
      );
      const singleStrategyOnly = backtestStrategies.length === 1;
      const fallbackMinStrength = singleStrategyOnly
        ? strategyMinStrengths[backtestStrategies[0]]
        : backtestConsensusStrengthPct / 100;

      const payload: Record<string, string | number | boolean | string[] | Record<string, number> | null> = {
        symbol: selectedSymbol,
        timeframe: selectedTimeframe,
        strategies: backtestStrategies,
        initial_capital: backtestInitialCapital,
        fee_bps: backtestFeeBps,
        slippage_bps: backtestSlippageBps,
        min_signal_strength: fallbackMinStrength,
        strategy_min_strengths: strategyMinStrengths,
        min_consensus_strength: singleStrategyOnly ? null : backtestConsensusStrengthPct / 100,
        limit: simulationBarLimit,
        position_size_pct: backtestPositionSizePct,
        entry_confirmation_bars: backtestEntryConfirmationBars,
        exit_mode: backtestExitMode,
        stop_loss_pct: backtestExitMode === "opposite_signal" ? null : backtestStopLossPct,
        take_profit_pct: backtestExitMode === "opposite_signal" ? null : backtestTakeProfitPct,
        max_bars_in_trade: backtestMaxBarsInTrade > 0 ? backtestMaxBarsInTrade : null,
        walkforward_split_pct: backtestWalkforwardSplitPct,
        benchmark_enabled: backtestBenchmarkEnabled,
      };

      if (filterMode === "date") {
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

      await response.json();
      setBacktestRefreshToken((previous) => previous + 1);
    } catch (runError) {
      setBacktestError(toUserFetchError(runError, "Erro inesperado ao correr backtest."));
    } finally {
      setBacktestRunning(false);
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
    const benchmarkReturnPct = getSummaryNumber(run.result_summary, "benchmark_return_pct");
    const runConfig = getRunConfigSnapshot(run);
    const benchmarkEnabled = runConfig.benchmark_enabled !== false;

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
                {Number(runConfig.fee_bps ?? run.fee_bps).toFixed(1)} bps /{" "}
                {Number(runConfig.slippage_bps ?? run.slippage_bps).toFixed(1)} bps
              </strong>
            </div>
            {typeof runConfig.position_size_pct === "number" && (
              <div>
                <span className="stats-label">Capital por trade</span>
                <strong>{runConfig.position_size_pct.toFixed(0)}%</strong>
              </div>
            )}
            {typeof runConfig.entry_confirmation_bars === "number" && (
              <div>
                <span className="stats-label">Confirmação entrada</span>
                <strong>{runConfig.entry_confirmation_bars} vela(s)</strong>
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
                <span className="stats-label">Walk-forward holdout</span>
                <strong>{Number(runConfig.walkforward_split_pct).toFixed(0)}%</strong>
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

        {walkforwardInSample && walkforwardOutSample && walkforwardBlock && (
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

        {equityCurve.length > 0 && (
          <div className="equity-curve-list">
            <span className="stats-label">Curva de equity</span>
            <BacktestEquityChart
              points={equityCurve}
              initialCapital={run.initial_capital}
              benchmarkReturnPct={benchmarkReturnPct}
              benchmarkEnabled={benchmarkEnabled}
            />
          </div>
        )}

        {run.trades && run.trades.length > 0 ? (
          <div className="signals-list">
            {run.trades.slice(0, 50).map((trade) => (
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
                    | Retorno: {(trade.return_pct * 100).toFixed(2)}% | Entry {trade.entry_price.toFixed(2)} {"->"}{" "}
                    Exit {trade.exit_price.toFixed(2)}
                  </p>
                  <p className="backtest-trade-reason">
                    <span>Entrada: {trade.entry_reason}</span>
                    <span>Saída: {trade.exit_reason}</span>
                  </p>
                </div>
              </article>
            ))}
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
    const preset: BacktestPreset = normalizeBacktestPreset({
      id: `${Date.now()}`,
      name,
      strategies: backtestStrategies,
      initialCapital: backtestInitialCapital,
      feeBps: backtestFeeBps,
      slippageBps: backtestSlippageBps,
      strategyMinStrengthPct: Object.fromEntries(
        backtestStrategies.map((strategy) => [
          strategy,
          backtestStrategyMinStrengthPct[strategy] ?? DEFAULT_BACKTEST_STRENGTH_PCT,
        ]),
      ),
      consensusStrengthPct: backtestConsensusStrengthPct,
      limit: filterMode === "count" ? barLimit : backtestLimit,
      positionSizePct: backtestPositionSizePct,
      entryConfirmationBars: backtestEntryConfirmationBars,
      exitMode: backtestExitMode,
      stopLossPct: backtestStopLossPct,
      takeProfitPct: backtestTakeProfitPct,
      maxBarsInTrade: backtestMaxBarsInTrade,
      walkforwardSplitPct: backtestWalkforwardSplitPct,
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
    const normalized = normalizeBacktestPreset(preset);
    setBacktestStrategies(normalized.strategies);
    setBacktestInitialCapital(normalized.initialCapital);
    setBacktestFeeBps(normalized.feeBps);
    setBacktestSlippageBps(normalized.slippageBps);
    setBacktestStrategyMinStrengthPct(normalized.strategyMinStrengthPct);
    setBacktestConsensusStrengthPct(normalized.consensusStrengthPct);
    if (filterMode === "count") {
      setBarLimit(normalized.limit);
      setBarLimitInput(String(normalized.limit));
    } else {
      setBacktestLimit(normalized.limit);
    }
    setBacktestPositionSizePct(normalized.positionSizePct);
    setBacktestEntryConfirmationBars(normalized.entryConfirmationBars);
    setBacktestExitMode(normalized.exitMode);
    setBacktestStopLossPct(normalized.stopLossPct ?? 2);
    setBacktestTakeProfitPct(normalized.takeProfitPct ?? 4);
    setBacktestMaxBarsInTrade(normalized.maxBarsInTrade ?? 40);
    setBacktestWalkforwardSplitPct(normalized.walkforwardSplitPct);
    setBacktestBenchmarkEnabled(normalized.benchmarkEnabled);
    setBacktestError(null);
  };

  const applyBacktestConfigFromRun = (run: BacktestRun) => {
    const config = getRunConfigSnapshot(run);
    const strategyStrengthPct = buildStrategyStrengthPctFromRun(run, config);
    const consensusPct =
      typeof config.min_consensus_strength === "number"
        ? Math.round(config.min_consensus_strength * 100)
        : Math.round(run.min_signal_strength * 100);
    const runLimit = typeof config.limit === "number" ? config.limit : run.bars_processed || 2000;

    if (instruments.some((item) => item.symbol === run.symbol)) {
      setSelectedSymbol(run.symbol);
    }
    setSelectedTimeframe(run.timeframe);
    setBacktestStrategies([...run.strategy_names]);
    setBacktestInitialCapital(Number(config.initial_capital ?? run.initial_capital));
    setBacktestFeeBps(Number(config.fee_bps ?? run.fee_bps));
    setBacktestSlippageBps(Number(config.slippage_bps ?? run.slippage_bps));
    setBacktestStrategyMinStrengthPct(strategyStrengthPct);
    setBacktestConsensusStrengthPct(consensusPct);

    if (run.start_at && run.end_at) {
      setFilterMode("date");
      setStartDate(toInputDate(new Date(run.start_at)));
      setEndDate(toInputDate(new Date(run.end_at)));
      setBacktestLimit(runLimit);
    } else {
      setFilterMode("count");
      setBarLimit(runLimit);
      setBarLimitInput(String(runLimit));
    }

    if (typeof config.position_size_pct === "number") {
      setBacktestPositionSizePct(config.position_size_pct);
    }
    if (typeof config.entry_confirmation_bars === "number") {
      setBacktestEntryConfirmationBars(config.entry_confirmation_bars);
    }
    if (config.exit_mode === "opposite_signal" || config.exit_mode === "tp_sl_or_opposite" || config.exit_mode === "tp_sl_only") {
      setBacktestExitMode(config.exit_mode);
    }
    if (typeof config.stop_loss_pct === "number") {
      setBacktestStopLossPct(config.stop_loss_pct);
    }
    if (typeof config.take_profit_pct === "number") {
      setBacktestTakeProfitPct(config.take_profit_pct);
    }
    if (typeof config.max_bars_in_trade === "number") {
      setBacktestMaxBarsInTrade(config.max_bars_in_trade);
    }
    if (typeof config.walkforward_split_pct === "number") {
      setBacktestWalkforwardSplitPct(config.walkforward_split_pct);
    }
    if (typeof config.benchmark_enabled === "boolean") {
      setBacktestBenchmarkEnabled(config.benchmark_enabled);
    }

    setBacktestError(null);
  };

  const handleApplyBacktestRunConfig = (run: BacktestRun) => {
    applyBacktestConfigFromRun(run);
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
      setBacktestCompareRunIds((previous) => previous.filter((id) => id !== runId));
      setBacktestRefreshToken((previous) => previous + 1);
    } catch (deleteError) {
      setBacktestError(toUserFetchError(deleteError, "Erro inesperado ao apagar simulação."));
    }
  };

  const handleToggleBacktestStrategy = (strategy: string, checked: boolean) => {
    setBacktestStrategies((previous) => {
      if (checked) {
        if (previous.includes(strategy)) {
          return previous;
        }
        setBacktestStrategyMinStrengthPct((strengths) => ({
          ...strengths,
          [strategy]: strengths[strategy] ?? DEFAULT_BACKTEST_STRENGTH_PCT,
        }));
        return [...previous, strategy];
      }
      return previous.filter((value) => value !== strategy);
    });
  };

  const handleBacktestStrategyStrengthChange = (strategy: string, pct: number) => {
    const normalized = Math.max(0, Math.min(100, pct));
    setBacktestStrategyMinStrengthPct((previous) => ({
      ...previous,
      [strategy]: normalized,
    }));
  };

  useEffect(() => {
    setHoveredOhlc(null);
  }, [selectedSymbol]);

  useEffect(() => {
    if (!chartContainerRef.current) {
      return;
    }

    const container = chartContainerRef.current;
    const chart = createChart(chartContainerRef.current, {
      layout: { background: { color: "#0f172a" }, textColor: "#d1d5db" },
      grid: { vertLines: { color: "#334155" }, horzLines: { color: "#334155" } },
      width: Math.max(container.clientWidth, 320),
      height: 420,
    });
    const candleSeries = chart.addSeries(CandlestickSeries);
    candleSeries.setData(chartData);

    if (overlayVisibility.sma20 && sma20Data.length > 0) {
      const series = chart.addSeries(LineSeries, { color: "#f59e0b", lineWidth: 2, title: "SMA 20" });
      series.setData(sma20Data);
    }

    if (overlayVisibility.ema20 && ema20Data.length > 0) {
      const series = chart.addSeries(LineSeries, { color: "#8b5cf6", lineWidth: 2, title: "EMA 20" });
      series.setData(ema20Data);
    }

    if (overlayVisibility.vwap && vwapData.length > 0) {
      const series = chart.addSeries(LineSeries, { color: "#22c55e", lineWidth: 2, title: "VWAP" });
      series.setData(vwapData);
    }

    if (overlayVisibility.bollinger) {
      if (bollingerUpperData.length > 0) {
        const series = chart.addSeries(LineSeries, {
          color: "#38bdf8",
          lineWidth: 1,
          lineStyle: 2,
          title: "BB Upper",
        });
        series.setData(bollingerUpperData);
      }
      if (bollingerMiddleData.length > 0) {
        const series = chart.addSeries(LineSeries, { color: "#0ea5e9", lineWidth: 1, title: "BB Mid" });
        series.setData(bollingerMiddleData);
      }
      if (bollingerLowerData.length > 0) {
        const series = chart.addSeries(LineSeries, {
          color: "#38bdf8",
          lineWidth: 1,
          lineStyle: 2,
          title: "BB Lower",
        });
        series.setData(bollingerLowerData);
      }
    }

    chart.timeScale().fitContent();

    chart.subscribeCrosshairMove((param) => {
      if (param.time === undefined || !param.seriesData.size) {
        setHoveredOhlc(null);
        return;
      }

      const rawData = param.seriesData.get(candleSeries);
      if (
        !rawData ||
        typeof rawData !== "object" ||
        !("open" in rawData) ||
        !("high" in rawData) ||
        !("low" in rawData) ||
        !("close" in rawData)
      ) {
        setHoveredOhlc(null);
        return;
      }

      let dateLabel: string;
      if (typeof param.time === "string") {
        dateLabel = formatDateLabel(param.time);
      } else if (typeof param.time === "number") {
        dateLabel = new Date(param.time * 1000).toLocaleDateString("pt-PT");
      } else {
        dateLabel = `${param.time.day.toString().padStart(2, "0")}/${param.time.month
          .toString()
          .padStart(2, "0")}/${param.time.year}`;
      }

      setHoveredOhlc({
        dateLabel,
        open: Number(rawData.open),
        high: Number(rawData.high),
        low: Number(rawData.low),
        close: Number(rawData.close),
      });
    });

    const resizeObserver = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) {
        return;
      }
      chart.applyOptions({ width: Math.max(entry.contentRect.width, 320) });
    });
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
    };
  }, [
    chartData,
    sma20Data,
    ema20Data,
    vwapData,
    bollingerUpperData,
    bollingerMiddleData,
    bollingerLowerData,
    overlayVisibility,
  ]);

  return (
    <main className="layout">
      <header className="topbar">
        <h1>Painel de Mercado</h1>
        <div className="topbar-actions">
          {currentUser ? (
            <>
              <span className="hint">Utilizador: {currentUser.display_name ?? currentUser.email}</span>
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
          <span className="badge">PAPER</span>
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
            <div className="config-tabs">
              <button
                type="button"
                className={
                  activeConfigTab === "data" ? "config-tab-button config-tab-button-active" : "config-tab-button"
                }
                onClick={() => setActiveConfigTab("data")}
              >
                Dados
              </button>
              <button
                type="button"
                className={
                  activeConfigTab === "signals"
                    ? "config-tab-button config-tab-button-active"
                    : "config-tab-button"
                }
                onClick={() => setActiveConfigTab("signals")}
              >
                Sinais
              </button>
              <button
                type="button"
                className={
                  activeConfigTab === "execution"
                    ? "config-tab-button config-tab-button-active"
                    : "config-tab-button"
                }
                onClick={() => setActiveConfigTab("execution")}
              >
                Execução
              </button>
              <button
                type="button"
                className={
                  activeConfigTab === "alerts"
                    ? "config-tab-button config-tab-button-active"
                    : "config-tab-button"
                }
                onClick={() => setActiveConfigTab("alerts")}
              >
                Alertas
              </button>
            </div>
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
      <section className="panel">
        <div className="panel-header">
          <p className="controls-context-label">{getControlsContextLabel(activeTab, filterMode)}</p>
          <div
            className={`controls-grid ${
              filterMode === "date" ? "controls-grid-date" : "controls-grid-count"
            }`}
          >
            <label className="field">
              <span>Símbolo</span>
              <select
                value={selectedSymbol}
                onChange={(event) => setSelectedSymbol(event.target.value)}
                disabled={instruments.length === 0 || loading}
              >
                {instruments.map((instrument) => (
                  <option key={instrument.id} value={instrument.symbol}>
                    {instrument.symbol}
                  </option>
                ))}
              </select>
            </label>

            <label className="field">
              <span>Intervalo</span>
              <select
                value={selectedTimeframe}
                onChange={(event) => setSelectedTimeframe(event.target.value)}
                disabled={loading}
              >
                <option value="1m">1m</option>
                <option value="5m">5m</option>
                <option value="15m">15m</option>
                <option value="1h">1h</option>
                <option value="4h">4h</option>
                <option value="1d">1d</option>
                <option value="1w">1w</option>
              </select>
            </label>

            <label className="field">
              <span>Janela</span>
              <select
                value={filterMode}
                onChange={(event) => setFilterMode(event.target.value as FilterMode)}
                disabled={loading}
              >
                <option value="count">Últimas N velas</option>
                <option value="date">Intervalo de datas</option>
              </select>
            </label>

            {filterMode === "count" ? (
              <label className="field">
                <span>Nº velas</span>
                <input
                  type="text"
                  inputMode="numeric"
                  pattern="\d*"
                  value={barLimitInput}
                  onChange={(event) => {
                    const { value } = event.target;
                    if (!/^\d*$/.test(value)) {
                      return;
                    }
                    setBarLimitInput(value);
                  }}
                  onBlur={() => {
                    const parsed = Number(barLimitInput);
                    if (Number.isNaN(parsed) || barLimitInput.trim() === "") {
                      setBarLimitInput(String(barLimit));
                      return;
                    }
                    const normalized = Math.max(1, Math.min(5000, Math.trunc(parsed)));
                    setBarLimit(normalized);
                    setBarLimitInput(String(normalized));
                  }}
                  onKeyDown={(event) => {
                    if (event.key !== "Enter") {
                      return;
                    }
                    const parsed = Number(barLimitInput);
                    if (Number.isNaN(parsed) || barLimitInput.trim() === "") {
                      setBarLimitInput(String(barLimit));
                      return;
                    }
                    const normalized = Math.max(1, Math.min(5000, Math.trunc(parsed)));
                    setBarLimit(normalized);
                    setBarLimitInput(String(normalized));
                    (event.target as HTMLInputElement).blur();
                  }}
                />
              </label>
            ) : (
              <>
                <label className="field">
                  <span>Data início</span>
                  <input
                    type="date"
                    value={startDate}
                    onChange={(event) => setStartDate(event.target.value)}
                    disabled={loading}
                  />
                </label>
                <label className="field">
                  <span>Data fim</span>
                  <input
                    type="date"
                    value={endDate}
                    onChange={(event) => setEndDate(event.target.value)}
                    disabled={loading}
                  />
                </label>
              </>
            )}
          </div>
        </div>

        {!error && isDateFilterIncomplete && <p className="hint">Defina data início e data fim.</p>}
        {!error && isDateRangeInvalid && <p className="hint">A data fim tem de ser igual ou posterior à data início.</p>}
        {!error && loading && <p className="hint">A carregar dados...</p>}

        <div className="tabs">
          <button
            type="button"
            className={activeTab === "market" ? "tab-button tab-button-active" : "tab-button"}
            onClick={() => setActiveTab("market")}
          >
            Mercado
          </button>
          <button
            type="button"
            className={activeTab === "signals" ? "tab-button tab-button-active" : "tab-button"}
            onClick={() => setActiveTab("signals")}
          >
            Sinais
          </button>
          <button
            type="button"
            className={activeTab === "backtests" ? "tab-button tab-button-active" : "tab-button"}
            onClick={() => setActiveTab("backtests")}
          >
            Simulação
          </button>
        </div>

        {error && <p className="error">{error}</p>}

        <div className="tab-content">
          <div
            className={activeTab === "market" ? "tab-pane tab-pane-active" : "tab-pane"}
          >
            {!error && !loading && !hasDateFilterError && bars.length === 0 && (
              <p className="hint">
                Sem velas para o símbolo/intervalo selecionado. Importe um CSV primeiro ou mude os filtros.
              </p>
            )}

            {!error && !loading && bars.length > 0 && (
              <div className="stats">
                <div>
                  <span className="stats-label">{barsSummaryLabel}</span>
                  <strong>{barsSummaryValue}</strong>
                </div>
                <div>
                  <span className="stats-label">Último fecho</span>
                  <strong>{lastBar?.close}</strong>
                </div>
                <div>
                  <span className="stats-label">Última data</span>
                  <strong>{lastBar ? new Date(lastBar.timestamp).toLocaleDateString("pt-PT") : "-"}</strong>
                </div>
              </div>
            )}

            <div className="overlay-controls">
              <span className="stats-label">Overlays no gráfico</span>
              <label>
                <input
                  type="checkbox"
                  checked={overlayVisibility.sma20}
                  onChange={(event) =>
                    setOverlayVisibility((previous) => ({ ...previous, sma20: event.target.checked }))
                  }
                />
                SMA 20
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={overlayVisibility.ema20}
                  onChange={(event) =>
                    setOverlayVisibility((previous) => ({ ...previous, ema20: event.target.checked }))
                  }
                />
                EMA 20
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={overlayVisibility.bollinger}
                  onChange={(event) =>
                    setOverlayVisibility((previous) => ({ ...previous, bollinger: event.target.checked }))
                  }
                />
                Bollinger Bands
              </label>
              <label>
                <input
                  type="checkbox"
                  checked={overlayVisibility.vwap}
                  onChange={(event) =>
                    setOverlayVisibility((previous) => ({ ...previous, vwap: event.target.checked }))
                  }
                />
                VWAP
              </label>
            </div>

            {lastIndicatorRow && (
              <div className="stats indicator-stats">
                <div>
                  <span className="stats-label">RSI (14)</span>
                  <strong>{formatIndicatorValue(lastIndicatorRow.rsi_14, bars.length, 14)}</strong>
                </div>
                <div>
                  <span className="stats-label">MACD</span>
                  <strong>{formatIndicatorValue(lastIndicatorRow.macd, bars.length, 26)}</strong>
                </div>
                <div>
                  <span className="stats-label">MACD Signal</span>
                  <strong>{formatIndicatorValue(lastIndicatorRow.macd_signal, bars.length, 34)}</strong>
                </div>
                <div>
                  <span className="stats-label">MACD Hist.</span>
                  <strong>{formatIndicatorValue(lastIndicatorRow.macd_histogram, bars.length, 34)}</strong>
                </div>
                <div>
                  <span className="stats-label">ATR (14)</span>
                  <strong>{formatIndicatorValue(lastIndicatorRow.atr_14, bars.length, 14)}</strong>
                </div>
                <div>
                  <span className="stats-label">Volume Relativo (20)</span>
                  <strong>{formatIndicatorValue(lastIndicatorRow.relative_volume_20, bars.length, 20)}</strong>
                </div>
              </div>
            )}

            {!error && !loading && visibleOhlc && (
              <div className="ohlc-panel">
                <h3>Vela sob o cursor</h3>
                <p className="hint">Passe o rato no gráfico para atualizar os valores.</p>
                <div className="stats ohlc-stats">
                  <div>
                    <span className="stats-label">Data</span>
                    <strong>{visibleOhlc.dateLabel}</strong>
                  </div>
                  <div>
                    <span className="stats-label">Abertura</span>
                    <strong>{formatPrice(visibleOhlc.open)}</strong>
                  </div>
                  <div>
                    <span className="stats-label">Máximo</span>
                    <strong>{formatPrice(visibleOhlc.high)}</strong>
                  </div>
                  <div>
                    <span className="stats-label">Mínimo</span>
                    <strong>{formatPrice(visibleOhlc.low)}</strong>
                  </div>
                  <div>
                    <span className="stats-label">Fecho</span>
                    <strong>{formatPrice(visibleOhlc.close)}</strong>
                  </div>
                </div>
              </div>
            )}
            <div ref={chartContainerRef} className="chart" />
          </div>

          <div
            className={activeTab === "signals" ? "tab-pane tab-pane-active" : "tab-pane"}
          >
            <div className="signals-panel">
              <div className="signals-header">
                <h3>Sinais da estratégia</h3>
              </div>

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
                              onClick={() => setSelectedStrategies(item.strategies)}
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
                  O sinal combinado é calculado a partir das estratégias ativas selecionadas abaixo.
                </p>
                <div className="strategy-picker">
                  <span className="stats-label">Estratégias ativas (consenso)</span>
                  <div className="strategy-chip-list">
                    {availableStrategies.map((strategy) => {
                      const checked = selectedStrategies.includes(strategy);
                      const info = STRATEGY_SUMMARY[strategy];
                      return (
                        <label
                          key={strategy}
                          className={checked ? "strategy-chip strategy-chip-active" : "strategy-chip"}
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={(event) => {
                              setSelectedStrategies((previous) => {
                                if (event.target.checked) {
                                  if (previous.includes(strategy)) {
                                    return previous;
                                  }
                                  return [...previous, strategy];
                                }
                                return previous.filter((value) => value !== strategy);
                              });
                            }}
                            disabled={loading}
                          />
                          <span>{info?.title ?? strategy}</span>
                        </label>
                      );
                    })}
                  </div>
                </div>

                {selectedStrategies.length > 0 ? (
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
              </div>

              <p className="hint signals-order-note">Mais recente {"->"} mais antigo.</p>
              {(signalsGenerating || signalsLoading) && <p className="hint">A atualizar sinais...</p>}
              {signalsError && <p className="error">{signalsError}</p>}
              {!signalsGenerating && !signalsLoading && signals.length === 0 && (
                <p className="hint">Sem sinais para os filtros atuais.</p>
              )}
              {signals.length > 0 && (
                <div className="signals-list">
                  {signals.map((signal) => (
                    <article key={signal.id} className="signal-row">
                      <div className="signal-main">
                        <div className="signal-top">
                          <strong className={signal.direction === "BUY" ? "signal-buy" : "signal-sell"}>
                            {signal.direction}
                          </strong>
                          <span>{STRATEGY_SUMMARY[signal.strategy]?.title ?? signal.strategy}</span>
                          <span>{formatDateTimeLabel(signal.timestamp)}</span>
                          <span>Força: {(signal.strength * 100).toFixed(1)}%</span>
                        </div>
                        <p>{signal.rationale}</p>
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className={activeTab === "backtests" ? "tab-pane tab-pane-active" : "tab-pane"}>
            <div className="backtests-panel">
              <div className="signals-header">
                <h3>Backtesting (simulação histórica)</h3>
              </div>
              <p className="hint">Configura o run, executa e compara resultados entre simulações.</p>

              <section className="backtest-data-section">
                <h4 className="backtest-section-title">Dados de mercado</h4>
                {backtestDataAvailability.status === "loading" && (
                  <p className="hint">A verificar velas disponíveis...</p>
                )}
                {backtestDataAvailability.status === "ready" && (
                  <p className="hint backtest-data-ready">
                    Dados OK: <strong>{backtestDataAvailability.availableBars}</strong> velas para{" "}
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
                        {filterMode === "date"
                          ? ` no intervalo ${startDate} – ${endDate}.`
                          : "."}
                      </p>
                    )}
                    {backtestDataAvailability.status === "insufficient_bars" && (
                      <p>
                        Só <strong>{backtestDataAvailability.availableBars}</strong> velas; são necessárias pelo
                        menos <strong>{backtestDataAvailability.requiredBars}</strong>.
                      </p>
                    )}
                  </div>
                )}
                <div className="backtest-data-banner-actions">
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
                        ? "Atualizar dados demo (Yahoo, 2 anos)"
                        : "Carregar dados demo (Yahoo, 2 anos)"}
                  </button>
                </div>
              </section>

              <details className="strategy-library-expand">
                <summary>Presets de simulação</summary>
                <div className="strategy-library">
                  <div className="auth-grid">
                    <label className="field">
                      <span>Nome do preset</span>
                      <input
                        value={backtestPresetName}
                        onChange={(event) => setBacktestPresetName(event.target.value)}
                        placeholder="Ex.: Reversão diária conservadora"
                      />
                    </label>
                  </div>
                  <div className="auth-actions">
                    <button type="button" className="tab-button" onClick={handleSaveBacktestPreset}>
                      Guardar configuração atual
                    </button>
                  </div>
                  {backtestPresets.length === 0 && (
                    <p className="hint">Ainda sem presets guardados.</p>
                  )}
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
              </details>

              <section className="strategy-consensus-card">
                <p className="strategy-consensus-caption">
                  {backtestStrategies.length > 1
                    ? "Cada estratégia tem o seu limiar de força mínima (0–100%). O consenso final exige acordo mínimo entre as estratégias activas — quanto maior a %, menos entradas."
                    : "Defina o limiar de força mínima (0–100%) da estratégia activa. Com uma só estratégia não há consenso combinado."}
                </p>
                <div className="strategy-picker">
                  <span className="stats-label">Estratégias ativas (backtest)</span>
                  <div className="strategy-chip-list">
                    {availableStrategies.map((strategy) => {
                      const checked = backtestStrategies.includes(strategy);
                      const info = STRATEGY_SUMMARY[strategy];
                      return (
                        <label
                          key={`backtest-${strategy}`}
                          className={checked ? "strategy-chip strategy-chip-active" : "strategy-chip"}
                        >
                          <input
                            type="checkbox"
                            checked={checked}
                            onChange={(event) =>
                              handleToggleBacktestStrategy(strategy, event.target.checked)
                            }
                          />
                          <span>{info?.title ?? strategy}</span>
                        </label>
                      );
                    })}
                  </div>
                </div>

                {backtestStrategies.length > 0 ? (
                  <>
                    <div className="backtest-strength-section">
                      <span className="stats-label">
                        {backtestStrategies.length > 1 ? "Limiar por estratégia" : "Limiar de força"}
                      </span>
                      <div className="backtest-strength-list">
                        {backtestStrategies.map((strategy) => {
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

                    {backtestStrategies.length > 1 && (
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
                  <label className="field">
                    <span>Fee (bps)</span>
                    <input
                      type="number"
                      min={0}
                      max={500}
                      step={0.5}
                      value={backtestFeeBps}
                      onChange={(event) => setBacktestFeeBps(Number(event.target.value))}
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
                  {filterMode === "date" && (
                    <label className="field">
                      <span>Limite máx. de velas</span>
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
                    <span>Walk-forward holdout (%)</span>
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

                <div className="auth-actions">
                  <button
                    type="button"
                    className="tab-button"
                    onClick={handleRunBacktest}
                    disabled={!canRunBacktest}
                  >
                    {backtestRunning ? "A correr..." : "Correr backtest"}
                  </button>
                </div>
              </section>

              {backtestError && <p className="error">{backtestError}</p>}

              <div className="backtests-results-zone">
                <div className="backtests-results-header">
                  <h3>Resultados</h3>
                  <p className="hint">
                    Histórico de simulações. Selecione até 2 runs para comparar. Use{" "}
                    <strong>Ver detalhe</strong> para config, gráfico de equity e trades.
                  </p>
                </div>

                {backtestLoading && <p className="hint">A carregar histórico...</p>}

                {!backtestLoading && backtestRuns.length === 0 && (
                  <p className="hint backtests-results-empty">Ainda sem simulações para este símbolo.</p>
                )}

                {backtestRuns.length > 0 && (
                  <div className="backtest-runs-list">
                    {backtestRuns.map((run) => {
                      const pnlPositive = run.net_pnl >= 0;
                      const isDetailOpen = backtestSelectedRun?.id === run.id;
                      return (
                        <div key={run.id} className="backtest-run-entry">
                          <article
                            className={
                              pnlPositive
                                ? "backtest-run-card backtest-run-card-positive"
                                : "backtest-run-card backtest-run-card-negative"
                            }
                          >
                            <div className="backtest-run-main">
                              <div className="backtest-run-title">
                                <strong>
                                  #{run.id} · {run.symbol} / {run.timeframe}
                                </strong>
                                <span>{formatDateTimeLabel(run.created_at)}</span>
                              </div>
                              <p className="backtest-run-strategies">
                                {run.strategy_names
                                  .map((name) => STRATEGY_SUMMARY[name]?.title ?? name)
                                  .join(" · ")}
                              </p>
                              <div className="backtest-run-meta">
                                <span>{run.trades_count} trades</span>
                                <span>Win {(run.win_rate * 100).toFixed(0)}%</span>
                                <span>DD {(run.max_drawdown_pct * 100).toFixed(1)}%</span>
                              </div>
                            </div>
                            <div className="backtest-run-pnl">
                              <span className="stats-label">PnL</span>
                              <strong className={pnlPositive ? "signal-buy" : "signal-sell"}>
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
                                {isDetailOpen ? "Ocultar detalhe" : "Ver detalhe"}
                              </button>
                              <button
                                type="button"
                                className="config-button"
                                onClick={() => handleApplyBacktestRunConfig(run)}
                              >
                                Reutilizar config
                              </button>
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
                )}

                {comparedBacktestRuns.length === 2 && (
                  <div className="backtest-compare-panel">
                    <h4>Comparação</h4>
                    <div className="backtest-compare-grid">
                      {comparedBacktestRuns.map((run) => (
                        <article key={`compare-${run.id}`} className="backtest-compare-card">
                          <strong>Run #{run.id}</strong>
                          <p>
                            {(run.net_pnl_pct * 100).toFixed(2)}% · {run.trades_count} trades
                          </p>
                          <p>
                            Win {(run.win_rate * 100).toFixed(0)}% · PF {run.profit_factor.toFixed(2)} · DD{" "}
                            {(run.max_drawdown_pct * 100).toFixed(1)}%
                          </p>
                        </article>
                      ))}
                    </div>
                  </div>
                )}

              </div>
            </div>
          </div>

        </div>
      </section>
      )}
    </main>
  );
}

export default App;
