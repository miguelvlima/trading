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

const API_BASE_URL = "http://localhost:8000";

const formatPrice = (value: number): string =>
  value.toLocaleString("pt-PT", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 8,
  });

const formatDateLabel = (dateText: string): string =>
  new Date(dateText).toLocaleDateString("pt-PT");

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
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<string>("");
  const [selectedTimeframe, setSelectedTimeframe] = useState<string>("1d");
  const [filterMode, setFilterMode] = useState<FilterMode>("count");
  const [barLimit, setBarLimit] = useState<number>(500);
  const [startDate, setStartDate] = useState<string>(
    toInputDate(new Date(Date.now() - 365 * 24 * 60 * 60 * 1000)),
  );
  const [endDate, setEndDate] = useState<string>(toInputDate(new Date()));
  const [bars, setBars] = useState<ApiBar[]>([]);
  const [indicatorRows, setIndicatorRows] = useState<IndicatorRow[]>([]);
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
    const loadInstruments = async () => {
      setLoading(true);
      setError(null);
      try {
        const response = await fetch(`${API_BASE_URL}/market-data/instruments`);
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
  }, []);

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
        const response = await fetch(`${API_BASE_URL}/market-data/bars?${query.toString()}`);
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
  }, [selectedSymbol, selectedTimeframe, barLimit, filterMode, startDate, endDate, hasDateFilterError]);

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
        const response = await fetch(`${API_BASE_URL}/market-data/indicators?${query.toString()}`);
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
  }, [selectedSymbol, selectedTimeframe, barLimit, filterMode, startDate, endDate, hasDateFilterError]);

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
        <span className="badge">PAPER</span>
      </header>

      <section className="panel">
        <div className="panel-header">
          <div
            className={`controls-grid ${
              filterMode === "date" ? "controls-grid-date" : "controls-grid-count"
            }`}
          >
            <label className="field">
              <span>Filtro</span>
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
                  type="number"
                  min={10}
                  max={5000}
                  step={10}
                  value={barLimit}
                  onChange={(event) => {
                    const parsed = Number(event.target.value);
                    if (Number.isNaN(parsed)) {
                      return;
                    }
                    const normalized = Math.max(10, Math.min(5000, parsed));
                    setBarLimit(normalized);
                  }}
                  disabled={loading}
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

        {error && <p className="error">{error}</p>}
        {!error && isDateFilterIncomplete && <p className="hint">Defina data início e data fim.</p>}
        {!error && isDateRangeInvalid && <p className="hint">A data fim tem de ser igual ou posterior à data início.</p>}
        {!error && loading && <p className="hint">A carregar dados...</p>}
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
      </section>
    </main>
  );
}

export default App;
