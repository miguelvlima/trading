import { CandlestickSeries, createChart, type CandlestickData } from "lightweight-charts";
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

const API_BASE_URL = "http://localhost:8000";

const formatPrice = (value: number): string =>
  value.toLocaleString("pt-PT", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 8,
  });

const formatDateLabel = (dateText: string): string =>
  new Date(dateText).toLocaleDateString("pt-PT");

function App() {
  const chartContainerRef = useRef<HTMLDivElement | null>(null);
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState<string>("");
  const [bars, setBars] = useState<ApiBar[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hoveredOhlc, setHoveredOhlc] = useState<OhlcDetails | null>(null);

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

    const loadBars = async () => {
      setLoading(true);
      setError(null);
      try {
        const query = new URLSearchParams({
          symbol: selectedSymbol,
          timeframe: "1d",
          limit: "500",
        });
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
  }, [selectedSymbol]);

  const chartData = useMemo<CandlestickData[]>(() => {
    return bars.map((bar) => ({
      time: new Date(bar.timestamp).toISOString().slice(0, 10),
      open: Number(bar.open),
      high: Number(bar.high),
      low: Number(bar.low),
      close: Number(bar.close),
    }));
  }, [bars]);

  const lastBar = bars.length > 0 ? bars[bars.length - 1] : null;
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
    const series = chart.addSeries(CandlestickSeries);
    series.setData(chartData);
    chart.timeScale().fitContent();

    chart.subscribeCrosshairMove((param) => {
      if (param.time === undefined || !param.seriesData.size) {
        setHoveredOhlc(null);
        return;
      }

      const rawData = param.seriesData.get(series);
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
  }, [chartData]);

  return (
    <main className="layout">
      <header className="topbar">
        <h1>Painel de Mercado</h1>
        <span className="badge">PAPER</span>
      </header>

      <section className="panel">
        <div className="panel-header">
          <h2>Dados de Mercado</h2>
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
        </div>

        {error && <p className="error">{error}</p>}
        {!error && loading && <p className="hint">A carregar dados...</p>}
        {!error && !loading && bars.length === 0 && (
          <p className="hint">Sem velas para o símbolo selecionado. Importe um CSV primeiro.</p>
        )}

        {!error && !loading && bars.length > 0 && (
          <div className="stats">
            <div>
              <span className="stats-label">Velas carregadas</span>
              <strong>{bars.length}</strong>
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
