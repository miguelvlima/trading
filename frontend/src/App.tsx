import {
  CandlestickSeries,
  LineSeries,
  createChart,
  type CandlestickData,
  type LineData,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";

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
type ViewTab = "market" | "signals";
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

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const AUTH_TOKEN_STORAGE_KEY = "trading_auth_token";
const CONSENSUS_THRESHOLD_STORAGE_KEY = "trading_consensus_threshold_pct";
const SIGNALS_FETCH_LIMIT_STORAGE_KEY = "trading_signals_fetch_limit";

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
  }, [isAuthenticated, authToken]);

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
        }
      } catch {
        setAvailableStrategies([]);
        setSelectedStrategies([]);
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
  }, [selectedSymbol, selectedTimeframe, barLimit, filterMode, startDate, endDate, hasDateFilterError, authToken]);

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

  const handleResetSignalListFilters = () => {
    setSignalDirectionFilter("BOTH");
    setSignalMinStrengthPct(0);
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
                    <h4>Execução</h4>
                    <p>Parâmetros para ordens, risco e simulação.</p>
                  </div>
                  <div className="config-placeholder">
                    Em breve: tamanho por ordem, slippage, comissões, risco máximo por trade e limites diários.
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
          <div
            className={`controls-grid ${
              filterMode === "date" ? "controls-grid-date" : "controls-grid-count"
            }`}
          >
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

        </div>
      </section>
      )}
    </main>
  );
}

export default App;
