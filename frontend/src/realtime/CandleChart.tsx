import { useEffect, useRef } from "react";
import {
  type CandlestickData,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
  CandlestickSeries,
  ColorType,
  createChart,
} from "lightweight-charts";

import type { Bar, Quote } from "./api";

type CandleChartProps = {
  bars: Bar[];
  liveQuote: Quote | null;
};

// The backend stores bar times in UTC. lightweight-charts wants `time` as epoch
// *seconds*. Some endpoints serialize without a timezone designator (e.g.
// "2026-06-09T04:00:00") while others include "Z"; we normalize the bare form to
// UTC by appending "Z" so Date.parse never reinterprets it through the browser's
// local timezone. Everything stays consistently in UTC.
function isoToUtcTimestamp(iso: string): UTCTimestamp {
  const hasTz = /[zZ]$|[+-]\d\d:?\d\d$/.test(iso);
  return (Date.parse(hasTz ? iso : `${iso}Z`) / 1000) as UTCTimestamp;
}

function toCandle(bar: Bar): CandlestickData {
  return {
    time: isoToUtcTimestamp(bar.timestamp),
    open: Number(bar.open),
    high: Number(bar.high),
    low: Number(bar.low),
    close: Number(bar.close),
  };
}

export function CandleChart({ bars, liveQuote }: CandleChartProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  // Create the chart once, on mount. Resize is handled by a ResizeObserver and
  // everything is torn down on unmount to avoid leaks.
  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }

    const chart = createChart(container, {
      width: container.clientWidth,
      height: 420,
      layout: {
        background: { type: ColorType.Solid, color: "#0f1420" },
        textColor: "#c7d0e0",
      },
      grid: {
        vertLines: { color: "#1c2433" },
        horzLines: { color: "#1c2433" },
      },
      timeScale: { timeVisible: true, secondsVisible: false },
      rightPriceScale: { borderColor: "#1c2433" },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#16a34a",
      downColor: "#dc2626",
      borderUpColor: "#16a34a",
      borderDownColor: "#dc2626",
      wickUpColor: "#16a34a",
      wickDownColor: "#dc2626",
    });

    chartRef.current = chart;
    seriesRef.current = series;

    const resizeObserver = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width;
      if (width) {
        chart.applyOptions({ width: Math.floor(width) });
      }
    });
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
      chartRef.current = null;
      seriesRef.current = null;
    };
  }, []);

  // Replace the full data set whenever the historical bars change. lightweight-
  // charts requires points sorted strictly ascending by time with no duplicates;
  // we sort + dedupe + drop non-finite values defensively so a bad payload can
  // never throw and blank the tab (it is logged instead).
  useEffect(() => {
    const series = seriesRef.current;
    if (!series) {
      return;
    }
    try {
      const candles = bars
        .map(toCandle)
        .filter(
          (c) =>
            Number.isFinite(c.open) &&
            Number.isFinite(c.high) &&
            Number.isFinite(c.low) &&
            Number.isFinite(c.close),
        )
        .sort((a, b) => Number(a.time) - Number(b.time));

      const deduped: CandlestickData[] = [];
      for (const candle of candles) {
        const last = deduped[deduped.length - 1];
        if (last && Number(last.time) === Number(candle.time)) {
          deduped[deduped.length - 1] = candle; // keep the latest for that time
        } else {
          deduped.push(candle);
        }
      }

      series.setData(deduped);
      chartRef.current?.timeScale().fitContent();
    } catch (err) {
      console.error("[Realtime] setData failed", { count: bars.length, err });
    }
  }, [bars]);

  // Patch only the most recent point with the live quote (no full redraw). We
  // skip a live quote that predates the last historical bar to keep `time`
  // strictly non-decreasing, which the series requires.
  useEffect(() => {
    const series = seriesRef.current;
    if (!series || !liveQuote) {
      return;
    }
    try {
      const liveTime = isoToUtcTimestamp(liveQuote.timestamp);
      const lastBar = bars[bars.length - 1];
      if (lastBar && Number(liveTime) < Number(isoToUtcTimestamp(lastBar.timestamp))) {
        return;
      }
      series.update({ ...toCandle(liveQuote), time: liveTime });
    } catch (err) {
      console.error("[Realtime] live update failed", err);
    }
  }, [liveQuote, bars]);

  return <div className="realtime-chart" ref={containerRef} />;
}
