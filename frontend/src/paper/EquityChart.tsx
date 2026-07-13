import { useEffect, useRef } from "react";
import {
  BaselineSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";

import { toEquitySeries } from "./monitor";

type EquityChartProps = {
  points: Array<{ at: string; equity: number }>;
  baseline: number | null; // day-start equity: green above, red below
  height?: number;
};

const UP = "#22c55e";
const DOWN = "#ef4444";

export function EquityChart({ points, baseline, height = 220 }: EquityChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Baseline"> | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    const styles = getComputedStyle(container);
    const textColor = styles.getPropertyValue("--rt-dim").trim() || "#8b93a7";
    const borderColor = styles.getPropertyValue("--rt-border").trim() || "#1c2536";

    const chart = createChart(container, {
      height,
      autoSize: true,
      layout: {
        background: { color: "transparent" },
        textColor,
        fontSize: 11,
        attributionLogo: false,
      },
      grid: {
        vertLines: { visible: false },
        horzLines: { color: borderColor },
      },
      rightPriceScale: { borderColor },
      timeScale: { borderColor, timeVisible: true, secondsVisible: false },
      crosshair: { horzLine: { visible: true }, vertLine: { visible: true } },
      handleScroll: false,
      handleScale: false,
    });
    const series = chart.addSeries(BaselineSeries, {
      baseValue: { type: "price", price: baseline ?? 0 },
      topLineColor: UP,
      topFillColor1: "rgba(34, 197, 94, 0.28)",
      topFillColor2: "rgba(34, 197, 94, 0.02)",
      bottomLineColor: DOWN,
      bottomFillColor1: "rgba(239, 68, 68, 0.02)",
      bottomFillColor2: "rgba(239, 68, 68, 0.28)",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
    });
    chartRef.current = chart;
    seriesRef.current = series;

    return () => {
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
    // The chart shell is built once; data/baseline flow through the effects below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [height]);

  useEffect(() => {
    const series = seriesRef.current;
    if (!series) return;
    series.setData(
      toEquitySeries(points).map((point) => ({
        time: point.time as UTCTimestamp,
        value: point.value,
      })),
    );
    chartRef.current?.timeScale().fitContent();
  }, [points]);

  useEffect(() => {
    if (baseline !== null) {
      seriesRef.current?.applyOptions({ baseValue: { type: "price", price: baseline } });
    }
  }, [baseline]);

  return <div ref={containerRef} className="pp-equity-chart" style={{ height }} />;
}
