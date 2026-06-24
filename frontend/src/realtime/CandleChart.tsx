import { useEffect, useRef } from "react";
import {
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type UTCTimestamp,
  CandlestickSeries,
  ColorType,
  createChart,
  HistogramSeries,
  LineSeries,
  LineStyle,
} from "lightweight-charts";

import type { Quote } from "./api";
import type { IndicatorRender, LinePoint } from "./indicators";

export type FormingBar = {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

export type HoverBar = {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

type CandleChartProps = {
  bars: Quote[];
  forming: FormingBar | null;
  indicators: IndicatorRender[];
  onHoverBar?: (bar: HoverBar | null) => void;
};

// Some endpoints serialize without a timezone designator; normalize the bare
// form to UTC so Date.parse never reinterprets it through the local timezone.
function isoToUtc(iso: string): UTCTimestamp {
  const hasTz = /[zZ]$|[+-]\d\d:?\d\d$/.test(iso);
  return (Date.parse(hasTz ? iso : `${iso}Z`) / 1000) as UTCTimestamp;
}

function toLineData(points: LinePoint[]): LineData[] {
  return points
    .filter((p) => Number.isFinite(p.value))
    .map((p) => ({ time: p.time as UTCTimestamp, value: p.value }));
}

export function CandleChart({ bars, forming, indicators, onHoverBar }: CandleChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const indicatorSeriesRef = useRef<ISeriesApi<"Line">[]>([]);
  const onHoverRef = useRef<CandleChartProps["onHoverBar"]>(onHoverBar);
  onHoverRef.current = onHoverBar;

  // Create the chart once.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const chart = createChart(container, {
      width: container.clientWidth,
      height: 440,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "#8492ad",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "#161d2c" },
        horzLines: { color: "#161d2c" },
      },
      timeScale: { timeVisible: true, secondsVisible: false, borderColor: "#1e2738" },
      rightPriceScale: { borderColor: "#1e2738" },
    });
    const candle = chart.addSeries(CandlestickSeries, {
      upColor: "#22c55e",
      downColor: "#ef4444",
      borderVisible: false,
      wickUpColor: "#22c55e",
      wickDownColor: "#ef4444",
    });
    const volume = chart.addSeries(HistogramSeries, {
      priceScaleId: "vol",
      priceFormat: { type: "volume" },
    });
    volume.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });

    chartRef.current = chart;
    candleRef.current = candle;
    volumeRef.current = volume;

    chart.subscribeCrosshairMove((param) => {
      const cb = onHoverRef.current;
      if (!cb) return;
      const data = param.seriesData.get(candle) as CandlestickData | undefined;
      if (!data) {
        cb(null);
        return;
      }
      const vol = param.seriesData.get(volume) as HistogramData | undefined;
      cb({
        time: Number(data.time),
        open: data.open,
        high: data.high,
        low: data.low,
        close: data.close,
        volume: vol ? vol.value : 0,
      });
    });

    const resize = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width;
      if (width) chart.applyOptions({ width: Math.floor(width) });
    });
    resize.observe(container);

    return () => {
      resize.disconnect();
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      volumeRef.current = null;
      indicatorSeriesRef.current = [];
    };
  }, []);

  // Full reload of candles + volume when the historical bars change.
  useEffect(() => {
    const candle = candleRef.current;
    const volume = volumeRef.current;
    if (!candle || !volume) return;
    try {
      const candles: CandlestickData[] = bars
        .map((b) => ({
          time: isoToUtc(b.timestamp),
          open: Number(b.open),
          high: Number(b.high),
          low: Number(b.low),
          close: Number(b.close),
        }))
        .filter(
          (c) =>
            Number.isFinite(c.open) &&
            Number.isFinite(c.high) &&
            Number.isFinite(c.low) &&
            Number.isFinite(c.close),
        )
        .sort((a, b) => Number(a.time) - Number(b.time));

      const deduped: CandlestickData[] = [];
      for (const c of candles) {
        const last = deduped[deduped.length - 1];
        if (last && Number(last.time) === Number(c.time)) deduped[deduped.length - 1] = c;
        else deduped.push(c);
      }
      candle.setData(deduped);

      const vols: HistogramData[] = bars
        .map((b) => ({
          time: isoToUtc(b.timestamp),
          value: Number(b.volume),
          color: Number(b.close) >= Number(b.open) ? "rgba(34,197,94,.4)" : "rgba(239,68,68,.4)",
        }))
        .filter((v) => Number.isFinite(v.value))
        .sort((a, b) => Number(a.time) - Number(b.time));
      const dedupVol: HistogramData[] = [];
      for (const v of vols) {
        const last = dedupVol[dedupVol.length - 1];
        if (last && Number(last.time) === Number(v.time)) dedupVol[dedupVol.length - 1] = v;
        else dedupVol.push(v);
      }
      volume.setData(dedupVol);
      chartRef.current?.timeScale().fitContent();
    } catch (err) {
      console.error("[Realtime] chart setData failed", err);
    }
  }, [bars]);

  // Rebuild indicator series whenever the indicator set (or its data) changes.
  // Parent memoizes `indicators`, so this does not run on every live tick.
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;

    for (const series of indicatorSeriesRef.current) {
      try {
        chart.removeSeries(series);
      } catch {
        /* already gone */
      }
    }
    indicatorSeriesRef.current = [];

    let nextPane = 1;
    for (const render of indicators) {
      const paneIndex = render.kind === "overlay" ? 0 : nextPane++;
      while (chart.panes().length <= paneIndex) chart.addPane();
      for (const line of render.lines) {
        const series = chart.addSeries(
          LineSeries,
          {
            color: line.color,
            lineWidth: 1,
            lineStyle: line.dashed ? LineStyle.Dashed : LineStyle.Solid,
            priceLineVisible: false,
            lastValueVisible: render.kind === "oscillator",
            ...(render.range
              ? {
                  autoscaleInfoProvider: () => ({
                    priceRange: { minValue: render.range!.min, maxValue: render.range!.max },
                  }),
                }
              : {}),
          },
          paneIndex,
        );
        series.setData(toLineData(line.points));
        indicatorSeriesRef.current.push(series);
      }
    }
  }, [indicators]);

  // Patch only the most recent candle with the forming bar (no full redraw).
  useEffect(() => {
    const candle = candleRef.current;
    const volume = volumeRef.current;
    if (!candle || !volume || !forming) return;
    try {
      const time = forming.time as UTCTimestamp;
      const lastBar = bars[bars.length - 1];
      if (lastBar && Number(time) < Number(isoToUtc(lastBar.timestamp))) return;
      candle.update({
        time,
        open: forming.open,
        high: forming.high,
        low: forming.low,
        close: forming.close,
      });
      volume.update({
        time,
        value: forming.volume,
        color:
          forming.close >= forming.open ? "rgba(34,197,94,.4)" : "rgba(239,68,68,.4)",
      });
    } catch (err) {
      console.error("[Realtime] forming update failed", err);
    }
  }, [forming, bars]);

  return <div className="rt-chart" ref={containerRef} />;
}
