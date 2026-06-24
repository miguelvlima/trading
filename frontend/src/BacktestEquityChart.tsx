import { LineSeries, createChart, type LineData, type UTCTimestamp } from "lightweight-charts";
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

export function BacktestEquityChart({
  points,
  initialCapital,
  benchmarkReturnPct = 0,
  benchmarkEnabled = true,
}: BacktestEquityChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  const chartPoints = useMemo(() => {
    const hasStoredBenchmark = points.some((point) => typeof point.benchmark_equity === "number");
    if (hasStoredBenchmark || !benchmarkEnabled) {
      return points;
    }
    return enrichBenchmarkCurve(points, initialCapital, benchmarkReturnPct);
  }, [benchmarkEnabled, benchmarkReturnPct, initialCapital, points]);

  const showBenchmark = benchmarkEnabled && chartPoints.some((point) => typeof point.benchmark_equity === "number");

  useEffect(() => {
    if (!containerRef.current || chartPoints.length === 0) {
      return;
    }

    const container = containerRef.current;
    const chart = createChart(container, {
      layout: { background: { color: "#0f172a" }, textColor: "#d1d5db" },
      grid: { vertLines: { color: "#334155" }, horzLines: { color: "#334155" } },
      width: Math.max(container.clientWidth, 280),
      height: 220,
      rightPriceScale: { borderColor: "#334155" },
      timeScale: { borderColor: "#334155" },
    });

    const equitySeries = chart.addSeries(LineSeries, {
      color: "#38bdf8",
      lineWidth: 2,
      title: "Estratégia",
      priceLineVisible: false,
      lastValueVisible: true,
    });
    equitySeries.setData(
      chartPoints.map((point) => ({
        time: toChartTime(point.timestamp),
        value: point.equity,
      })),
    );

    if (showBenchmark) {
      const benchmarkSeries = chart.addSeries(LineSeries, {
        color: "#f59e0b",
        lineWidth: 2,
        lineStyle: 2,
        title: "Buy & hold",
        priceLineVisible: false,
        lastValueVisible: true,
      });
      benchmarkSeries.setData(
        chartPoints
          .filter((point) => typeof point.benchmark_equity === "number")
          .map((point) => ({
            time: toChartTime(point.timestamp),
            value: point.benchmark_equity as number,
          })),
      );
    }

    chart.timeScale().fitContent();

    const resizeObserver = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (entry) {
        chart.applyOptions({ width: Math.max(entry.contentRect.width, 280) });
      }
    });
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
    };
  }, [chartPoints, showBenchmark]);

  if (chartPoints.length === 0) {
    return null;
  }

  return (
    <div className="backtest-equity-chart-wrap">
      <div ref={containerRef} className="backtest-equity-chart" role="img" aria-label="Curva de equity" />
      <div className="backtest-equity-legend">
        <span className="backtest-equity-legend-item backtest-equity-legend-strategy">Estratégia</span>
        {showBenchmark && (
          <span className="backtest-equity-legend-item backtest-equity-legend-benchmark">Buy &amp; hold</span>
        )}
      </div>
    </div>
  );
}
