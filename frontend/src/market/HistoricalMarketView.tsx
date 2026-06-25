import type { Ref } from "react";

import { fmtCompact, fmtPrice } from "../realtime/format";
import "../realtime/realtime.css";

type OhlcHead = {
  dateLabel: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

type IndicatorSnapshot = {
  rsi_14: number | null;
  macd: number | null;
  macd_signal: number | null;
  macd_histogram: number | null;
  atr_14: number | null;
  relative_volume_20: number | null;
};

type HistoricalMarketViewProps = {
  chartContainerRef: Ref<HTMLDivElement>;
  loading: boolean;
  error: string | null;
  hasDateFilterError: boolean;
  barsCount: number;
  barsSummaryLabel: string;
  barsSummaryValue: string;
  headBar: OhlcHead | null;
  lastIndicatorRow: IndicatorSnapshot | null;
  formatIndicatorValue: (value: number | null, barCount: number, minBars: number) => string;
  backtestTradesOnChartRunId: number | null;
  backtestTradesCount: number;
  onClearBacktestTrades: () => void;
};

export function HistoricalMarketView({
  chartContainerRef,
  loading,
  error,
  hasDateFilterError,
  barsCount,
  barsSummaryLabel,
  barsSummaryValue,
  headBar,
  lastIndicatorRow,
  formatIndicatorValue,
  backtestTradesOnChartRunId,
  backtestTradesCount,
  onClearBacktestTrades,
}: HistoricalMarketViewProps) {
  const headDir = headBar ? (headBar.close >= headBar.open ? "up" : "down") : "up";

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
                <span>O <b>{fmtPrice(headBar.open)}</b></span>
                <span>H <b>{fmtPrice(headBar.high)}</b></span>
                <span>L <b>{fmtPrice(headBar.low)}</b></span>
                <span>C <b>{fmtPrice(headBar.close)}</b></span>
                <span>Vol <b>{fmtCompact(headBar.volume)}</b></span>
              </span>
            </div>
          )}

          {loading && barsCount === 0 && <p className="hint rt-chart-empty">A carregar velas…</p>}
          {!error && !loading && !hasDateFilterError && barsCount === 0 && (
            <p className="hint rt-chart-empty">
              Sem velas para o símbolo/intervalo selecionado. Importe um CSV ou mude os filtros.
            </p>
          )}

          <div ref={chartContainerRef} className="rt-chart" />
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

          {lastIndicatorRow && (
            <div className="rt-card">
              <div className="rt-card-h">
                <span className="rt-card-t">Indicadores</span>
              </div>
              <div className="rt-rows">
                <div className="rt-r">
                  <span className="rt-k">RSI (14)</span>
                  <span className="rt-v">
                    {formatIndicatorValue(lastIndicatorRow.rsi_14, barsCount, 14)}
                  </span>
                </div>
                <div className="rt-r">
                  <span className="rt-k">MACD</span>
                  <span className="rt-v">
                    {formatIndicatorValue(lastIndicatorRow.macd, barsCount, 26)}
                  </span>
                </div>
                <div className="rt-r">
                  <span className="rt-k">MACD Signal</span>
                  <span className="rt-v">
                    {formatIndicatorValue(lastIndicatorRow.macd_signal, barsCount, 34)}
                  </span>
                </div>
                <div className="rt-r">
                  <span className="rt-k">MACD Hist.</span>
                  <span className="rt-v">
                    {formatIndicatorValue(lastIndicatorRow.macd_histogram, barsCount, 34)}
                  </span>
                </div>
                <div className="rt-r">
                  <span className="rt-k">ATR (14)</span>
                  <span className="rt-v">
                    {formatIndicatorValue(lastIndicatorRow.atr_14, barsCount, 14)}
                  </span>
                </div>
                <div className="rt-r">
                  <span className="rt-k">Vol. relativo (20)</span>
                  <span className="rt-v">
                    {formatIndicatorValue(lastIndicatorRow.relative_volume_20, barsCount, 20)}
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
