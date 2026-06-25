import { useMemo, useState } from "react";

import { type HoverBar, CandleChart } from "../realtime/CandleChart";
import { fmtCompact, fmtPrice } from "../realtime/format";
import {
  type IndicatorId,
  type IndicatorRender,
  INDICATOR_BY_ID,
  computeIndicator,
} from "../realtime/indicators";
import "../realtime/realtime.css";

import { buildBacktestTradeMarkers, type BacktestTradeForChart } from "./backtestMarkers";
import { apiBarsToQuotes, quotesToIndicatorBars, type ApiBar } from "./chartBars";
import { indicatorRailRows } from "./indicatorRail";
import { type PeriodMode, type WindowCode, WINDOW_SECONDS } from "./windowCandle";

type HistoricalMarketViewProps = {
  symbol: string;
  bars: ApiBar[];
  periodMode: PeriodMode;
  chartWindow: WindowCode;
  activeIndicators: ReadonlySet<IndicatorId>;
  tradeMarkers: BacktestTradeForChart[];
  loading: boolean;
  error: string | null;
  hasDateFilterError: boolean;
  barLimit: number;
  backtestTradesOnChartRunId: number | null;
  backtestTradesCount: number;
  onClearBacktestTrades: () => void;
};

function formatHoverDate(timeSec: number): string {
  return new Date(timeSec * 1000).toLocaleString("pt-PT");
}

export function HistoricalMarketView({
  symbol,
  bars,
  periodMode,
  chartWindow,
  activeIndicators,
  tradeMarkers,
  loading,
  error,
  hasDateFilterError,
  barLimit,
  backtestTradesOnChartRunId,
  backtestTradesCount,
  onClearBacktestTrades,
}: HistoricalMarketViewProps) {
  const [hoverBar, setHoverBar] = useState<HoverBar | null>(null);

  const quotes = useMemo(() => apiBarsToQuotes(symbol, bars), [symbol, bars]);
  const indicatorBars = useMemo(() => quotesToIndicatorBars(quotes), [quotes]);

  const indicatorRenders: IndicatorRender[] = useMemo(
    () => Array.from(activeIndicators).map((id) => computeIndicator(INDICATOR_BY_ID[id], indicatorBars)),
    [activeIndicators, indicatorBars],
  );

  const markers = useMemo(() => buildBacktestTradeMarkers(tradeMarkers), [tradeMarkers]);

  const lastBar = bars.length > 0 ? bars[bars.length - 1] : null;
  const fallbackHead = lastBar
    ? {
        open: Number(lastBar.open),
        high: Number(lastBar.high),
        low: Number(lastBar.low),
        close: Number(lastBar.close),
        volume: Number(lastBar.volume),
        dateLabel: new Date(lastBar.timestamp).toLocaleDateString("pt-PT"),
      }
    : null;

  const headBar = hoverBar
    ? {
        open: hoverBar.open,
        high: hoverBar.high,
        low: hoverBar.low,
        close: hoverBar.close,
        volume: hoverBar.volume,
        dateLabel: formatHoverDate(hoverBar.time),
      }
    : fallbackHead;

  const headDir = headBar ? (headBar.close >= headBar.open ? "up" : "down") : "up";
  const barsSummaryLabel = periodMode === "window" ? "Velas carregadas" : "Velas no período";
  const barsSummaryValue = periodMode === "window" ? `${bars.length} / ${barLimit}` : String(bars.length);
  const windowSeconds = periodMode === "window" ? WINDOW_SECONDS[chartWindow] : null;
  const railRows = useMemo(
    () => indicatorRailRows(activeIndicators, indicatorRenders, bars.length),
    [activeIndicators, indicatorRenders, bars.length],
  );

  return (
    <div className="rt-page">
      {backtestTradesOnChartRunId !== null && backtestTradesCount > 0 && (
        <div className="rt-banner">
          <p>
            Trades da simulação <strong>#{backtestTradesOnChartRunId}</strong> no gráfico (
            {backtestTradesCount} trades · setas verdes/vermelhas = entrada/saída).
          </p>
          <button type="button" className="rt-banner-btn" onClick={onClearBacktestTrades}>
            Ocultar
          </button>
        </div>
      )}

      <div className="rt-main">
        <div className="rt-chart-wrap">
          {headBar && (
            <div className="rt-chart-head">
              <span className={`rt-head-px rt-${headDir}`}>{fmtPrice(headBar.close)}</span>
              <span className="rt-head-ohlc">
                <span>
                  O <b>{fmtPrice(headBar.open)}</b>
                </span>
                <span>
                  H <b>{fmtPrice(headBar.high)}</b>
                </span>
                <span>
                  L <b>{fmtPrice(headBar.low)}</b>
                </span>
                <span>
                  C <b>{fmtPrice(headBar.close)}</b>
                </span>
                <span>
                  Vol <b>{fmtCompact(headBar.volume)}</b>
                </span>
              </span>
            </div>
          )}

          {loading && bars.length === 0 && <p className="hint rt-chart-empty">A carregar velas…</p>}
          {!error && !loading && !hasDateFilterError && bars.length === 0 && (
            <p className="hint rt-chart-empty">
              Sem velas para o símbolo/intervalo selecionado. Importe um CSV ou mude os filtros.
            </p>
          )}

          {bars.length > 0 && (
            <CandleChart
              bars={quotes}
              forming={null}
              indicators={indicatorRenders}
              windowSeconds={windowSeconds}
              markers={markers}
              onHoverBar={setHoverBar}
            />
          )}
        </div>

        <div className="rt-rail">
          <div className="rt-card">
            <div className="rt-card-h">
              <span className="rt-card-t">Resumo</span>
              <span className="rt-badge rt-badge-snap">Histórico</span>
            </div>
            <div className="rt-rows">
              <div className="rt-r">
                <span className="rt-k">{barsSummaryLabel}</span>
                <span className="rt-v">{barsSummaryValue}</span>
              </div>
              {headBar && (
                <>
                  <div className="rt-r">
                    <span className="rt-k">Data</span>
                    <span className="rt-v">{headBar.dateLabel}</span>
                  </div>
                  <div className="rt-r">
                    <span className="rt-k">Último fecho</span>
                    <span className={`rt-v rt-v-big rt-${headDir}`}>{fmtPrice(headBar.close)}</span>
                  </div>
                </>
              )}
            </div>
          </div>

          {railRows.length > 0 && (
            <div className="rt-card">
              <div className="rt-card-h">
                <span className="rt-card-t">Indicadores</span>
              </div>
              <div className="rt-rows">
                {railRows.map((row) => (
                  <div key={row.id} className="rt-r">
                    <span className="rt-k">{row.label}</span>
                    <span className="rt-v">{row.value}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
