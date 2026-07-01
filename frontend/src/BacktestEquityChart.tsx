import { LineSeries, createChart, type IChartApi, type ISeriesApi, type LineData, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useMemo, useRef } from "react";

export type EquityCurvePoint = {
  timestamp: string;
  equity: number;
  benchmark_equity?: number;
};

type BacktestEquityChartProps = {
  points: EquityCurvePoint[];
  initialCapital: number;
  benchmarkReturnPct?: number;
  benchmarkEnabled?: boolean;
  tradesCount?: number;
  netPnlPct?: number;
};

const toChartTime = (timestamp: string): UTCTimestamp =>
  Math.floor(new Date(timestamp).getTime() / 1000) as UTCTimestamp;

const enrichBenchmarkCurve = (
  points: EquityCurvePoint[],
  initialCapital: number,
  benchmarkReturnPct: number,
): EquityCurvePoint[] => {
  if (points.length < 2 || initialCapital <= 0) {
    return points;
  }
  const lastIndex = points.length - 1;
  return points.map((point, index) => ({
    ...point,
    benchmark_equity: initialCapital * (1 + benchmarkReturnPct * (index / lastIndex)),
  }));
};

function resolveStrategyColor(tradesCount: number, netPnlPct: number): string {
  if (tradesCount === 0) {
    return "#94a3b8";
  }
  if (netPnlPct > 0) {
    return "#22c55e";
  }
  if (netPnlPct < 0) {
    return "#ef4444";
  }
  return "#94a3b8";
}

function resolveLegendClass(tradesCount: number, netPnlPct: number): string {
  if (tradesCount === 0) {
    return "backtest-equity-legend-strategy-flat";
  }
  if (netPnlPct > 0) {
    return "backtest-equity-legend-strategy-positive";
  }
  if (netPnlPct < 0) {
    return "backtest-equity-legend-strategy-negative";
  }
  return "backtest-equity-legend-strategy-flat";
}

export function BacktestEquityChart({
  points,
  initialCapital,
  benchmarkReturnPct = 0,
  benchmarkEnabled = true,
  tradesCount = 0,
  netPnlPct = 0,
}: BacktestEquityChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const equitySeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  const benchmarkSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  const chartPoints = useMemo(() => {
    const hasStoredBenchmark = points.some((point) => typeof point.benchmark_equity === "number");
    if (hasStoredBenchmark || !benchmarkEnabled) {
      return points;
    }
    return enrichBenchmarkCurve(points, initialCapital, benchmarkReturnPct);
  }, [benchmarkEnabled, benchmarkReturnPct, initialCapital, points]);

  const showBenchmark = benchmarkEnabled && chartPoints.some((point) => typeof point.benchmark_equity === "number");
  const strategyColor = resolveStrategyColor(tradesCount, netPnlPct);
  const legendClass = resolveLegendClass(tradesCount, netPnlPct);

  const equityLineData = useMemo(
    (): LineData[] =>
      chartPoints.map((point) => ({
        time: toChartTime(point.timestamp),
        value: point.equity,
      })),
    [chartPoints],
  );

  const benchmarkLineData = useMemo(
    (): LineData[] =>
      chartPoints
        .filter((point) => typeof point.benchmark_equity === "number")
        .map((point) => ({
          time: toChartTime(point.timestamp),
          value: point.benchmark_equity as number,
        })),
    [chartPoints],
  );

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }

    container.replaceChildren();
    const chart = createChart(container, {
      layout: { background: { color: "#0f172a" }, textColor: "#d1d5db" },
      grid: { vertLines: { color: "#334155" }, horzLines: { color: "#334155" } },
      width: Math.max(container.clientWidth, 280),
      height: 220,
      rightPriceScale: { borderColor: "#334155" },
      timeScale: { borderColor: "#334155" },
    });

    chartRef.current = chart;
    equitySeriesRef.current = chart.addSeries(LineSeries, {
      color: strategyColor,
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
    });

    if (showBenchmark) {
      benchmarkSeriesRef.current = chart.addSeries(LineSeries, {
        color: "#f59e0b",
        lineWidth: 2,
        lineStyle: 2,
        priceLineVisible: false,
        lastValueVisible: true,
      });
    } else {
      benchmarkSeriesRef.current = null;
    }

    const resizeObserver = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry && chartRef.current) {
        chartRef.current.applyOptions({ width: Math.max(entry.contentRect.width, 280) });
      }
    });
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      equitySeriesRef.current = null;
      benchmarkSeriesRef.current = null;
      container.replaceChildren();
    };
  }, [showBenchmark, strategyColor]);

  useEffect(() => {
    if (!equitySeriesRef.current || equityLineData.length === 0) {
      return;
    }
    equitySeriesRef.current.applyOptions({ color: strategyColor });
    equitySeriesRef.current.setData(equityLineData);
    chartRef.current?.timeScale().fitContent();
  }, [equityLineData, strategyColor]);

  useEffect(() => {
    if (!showBenchmark || !benchmarkSeriesRef.current) {
      return;
    }
    benchmarkSeriesRef.current.setData(benchmarkLineData);
    chartRef.current?.timeScale().fitContent();
  }, [benchmarkLineData, showBenchmark]);

  if (chartPoints.length === 0) {
    return null;
  }

  return (
    <div className="backtest-equity-chart-wrap">
      <div ref={containerRef} className="backtest-equity-chart" role="img" aria-label="Curva de equity" />
      <div className="backtest-equity-legend">
        <span className={`backtest-equity-legend-item ${legendClass}`}>Estratégia</span>
        {showBenchmark && (
          <span className="backtest-equity-legend-item backtest-equity-legend-benchmark">Buy &amp; hold</span>
        )}
      </div>
      {tradesCount === 0 && (
        <p className="hint backtest-equity-flat-note">Sem trades — a linha da estratégia mantém-se plana no capital inicial.</p>
      )}
    </div>
  );
}
