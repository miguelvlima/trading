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
import {
  STRATEGY_MARKER_COLORS,
  buildSignalMarkers,
  type SignalForChart,
} from "./signalMarkers";
import { apiBarsToQuotes, isoToChartTime, quotesToIndicatorBars, type ApiBar } from "./chartBars";
import { indicatorRailRows } from "./indicatorRail";
import { type PeriodMode, type WindowCode, WINDOW_SECONDS } from "./windowCandle";

type HistoricalMarketViewProps = {
  symbol: string;
  bars: ApiBar[];
  periodMode: PeriodMode;
  chartWindow: WindowCode;
  activeIndicators: ReadonlySet<IndicatorId>;
  tradeMarkers: BacktestTradeForChart[];
  signalMarkers: SignalForChart[];
  signalsOverlayEnabled: boolean;
  selectedChartSignal: SignalForChart | null;
  selectedChartSignalMatches: SignalForChart[];
  strategyLabels: Record<string, string>;
  loading: boolean;
  error: string | null;
  hasDateFilterError: boolean;
  barLimit: number;
  backtestTradesOnChartRunId: number | null;
  backtestTradesCount: number;
  signalsListCount: number;
  onClearBacktestTrades: () => void;
  onClearSignalsOnChart: () => void;
  onShowSignalsOnChart: () => void;
  onChartSignalClick: (timeSec: number) => void;
  onSelectChartSignal: (signal: SignalForChart | null) => void;
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
  signalMarkers,
  signalsOverlayEnabled,
  selectedChartSignal,
  selectedChartSignalMatches,
  strategyLabels,
  loading,
  error,
  hasDateFilterError,
  barLimit,
  backtestTradesOnChartRunId,
  backtestTradesCount,
  signalsListCount,
  onClearBacktestTrades,
  onClearSignalsOnChart,
  onShowSignalsOnChart,
  onChartSignalClick,
  onSelectChartSignal,
}: HistoricalMarketViewProps) {
  const [hoverBar, setHoverBar] = useState<HoverBar | null>(null);

  const quotes = useMemo(() => apiBarsToQuotes(symbol, bars), [symbol, bars]);
  const indicatorBars = useMemo(() => quotesToIndicatorBars(quotes), [quotes]);

  const indicatorRenders: IndicatorRender[] = useMemo(
    () => Array.from(activeIndicators).map((id) => computeIndicator(INDICATOR_BY_ID[id], indicatorBars)),
    [activeIndicators, indicatorBars],
  );

  const markers = useMemo(() => {
    const trade = buildBacktestTradeMarkers(tradeMarkers);
    const signal = buildSignalMarkers(
      signalMarkers,
      selectedChartSignal?.id ?? null,
    );
    return [...trade, ...signal].sort((left, right) => Number(left.time) - Number(right.time));
  }, [tradeMarkers, signalMarkers, selectedChartSignal?.id]);

  const focusTimeSec = selectedChartSignal
    ? Number(isoToChartTime(selectedChartSignal.timestamp))
    : null;

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
  const showSignalsBanner = signalsListCount > 0 || signalMarkers.length > 0;
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

      {showSignalsBanner && (
        <div className="rt-banner rt-banner-signals">
          <p>
            {signalMarkers.length > 0 ? (
              <>
                {signalsOverlayEnabled ? (
                  <>
                    <strong>{signalMarkers.length}</strong> sinais no gráfico (overlay activo
                    {signalMarkers.length >= 100 ? " · máx. 100" : ""}).
                  </>
                ) : (
                  <>
                    <strong>{signalMarkers.length}</strong> sinal(is) seleccionado(s) no gráfico.
                  </>
                )}{" "}
                {selectedChartSignal ? (
                  <>
                    Marcador{" "}
                    <strong className={selectedChartSignal.direction === "BUY" ? "signal-buy" : "signal-sell"}>
                      {selectedChartSignal.direction === "BUY" ? "▲" : "▼"}{" "}
                      {selectedChartSignal.direction}
                    </strong>{" "}
                    na vela de{" "}
                    <strong>
                      {new Date(selectedChartSignal.timestamp).toLocaleDateString("pt-PT")}
                    </strong>{" "}
                    (zoom aplicado — seta por cima da vela).
                  </>
                ) : (
                  <>Cores por estratégia · clique num marcador para ver o rationale.</>
                )}
              </>
            ) : (
              <>
                <strong>{signalsListCount}</strong> sinais disponíveis na lista (ocultos no gráfico).
              </>
            )}
          </p>
          <div className="rt-banner-actions">
            {signalMarkers.length === 0 && (
              <button
                type="button"
                className="rt-banner-btn"
                disabled={signalsListCount === 0}
                onClick={onShowSignalsOnChart}
              >
                Mostrar sinais no gráfico
              </button>
            )}
            {signalMarkers.length > 0 && (
              <button type="button" className="rt-banner-btn" onClick={onClearSignalsOnChart}>
                Ocultar do gráfico
              </button>
            )}
          </div>
        </div>
      )}

      {selectedChartSignal && (
        <div className="chart-signal-detail">
          <div className="chart-signal-detail-header">
            <strong
              className={
                selectedChartSignal.direction === "BUY" ? "signal-buy" : "signal-sell"
              }
            >
              {selectedChartSignal.direction}
            </strong>
            <span>
              {strategyLabels[selectedChartSignal.strategy] ?? selectedChartSignal.strategy}
            </span>
            <span>{new Date(selectedChartSignal.timestamp).toLocaleString("pt-PT")}</span>
            <span>Força {(selectedChartSignal.strength * 100).toFixed(1)}%</span>
            {selectedChartSignal.source && (
              <span className="signal-source-badge">
                {selectedChartSignal.source === "live" ? "Live" : "Hist."}
              </span>
            )}
            <button
              type="button"
              className="rt-banner-btn"
              onClick={() => onSelectChartSignal(null)}
            >
              Fechar
            </button>
          </div>
          <p>{selectedChartSignal.rationale}</p>
          {selectedChartSignalMatches.length > 1 && (
            <div className="chart-signal-detail-alternates">
              <span className="stats-label">Outros sinais nesta vela</span>
              {selectedChartSignalMatches
                .filter((item) => item.id !== selectedChartSignal.id)
                .map((item) => (
                  <button
                    key={item.id}
                    type="button"
                    className="config-button chart-signal-alt-btn"
                    onClick={() => onSelectChartSignal(item)}
                  >
                    <span
                      style={{
                        color: STRATEGY_MARKER_COLORS[item.strategy] ?? "inherit",
                      }}
                    >
                      {strategyLabels[item.strategy] ?? item.strategy}
                    </span>{" "}
                    · {item.direction} · {(item.strength * 100).toFixed(0)}%
                  </button>
                ))}
            </div>
          )}
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
              onChartClick={onChartSignalClick}
              focusTimeSec={focusTimeSec}
              focusBarsVisible={55}
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
