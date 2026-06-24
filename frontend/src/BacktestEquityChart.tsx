import { LineSeries, createChart, type LineData, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";

export type EquityCurvePoint = {
  timestamp: string;
  equity: number;
  benchmark_equity?: number;
};

type BacktestEquityChartProps = {
  points: EquityCurvePoint[];
};

const toChartTime = (timestamp: string): UTCTimestamp =>
  Math.floor(new Date(timestamp).getTime() / 1000) as UTCTimestamp;

export function BacktestEquityChart({ points }: BacktestEquityChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current || points.length === 0) {
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
    });
    const equityData: LineData[] = points.map((point) => ({
      time: toChartTime(point.timestamp),
      value: point.equity,
    }));
    equitySeries.setData(equityData);

    const hasBenchmark = points.some((point) => typeof point.benchmark_equity === "number");
    if (hasBenchmark) {
      const benchmarkSeries = chart.addSeries(LineSeries, {
        color: "#94a3b8",
        lineWidth: 1,
        lineStyle: 2,
        title: "Buy & hold",
      });
      benchmarkSeries.setData(
        points
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
  }, [points]);

  if (points.length === 0) {
    return null;
  }

  return <div ref={containerRef} className="backtest-equity-chart" role="img" aria-label="Curva de equity" />;
}
