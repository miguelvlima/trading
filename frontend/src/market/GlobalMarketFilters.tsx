import "../realtime/realtime.css";
import "./market-filters.css";

import { IndicatorToggleRow } from "./IndicatorToggleRow";
import { StrategyToggleRow } from "./StrategyToggleRow";
import { SymbolBar } from "../realtime/SymbolBar";
import { type IndicatorId } from "../realtime/indicators";
import type { StreamStatus } from "../realtime/useTickStream";
import {
  type CandleCode,
  type PeriodMode,
  type WindowCode,
  CANDLES,
  IBKR_DURATION,
  SUGGESTED_CANDLE,
  WINDOWS,
  fetchLimitFor,
} from "./windowCandle";

type InstrumentOption = {
  id: number;
  symbol: string;
  name?: string | null;
};

type MarketTab = "market" | "signals" | "backtests";
type ChartMode = "historico" | "aovivo";
type SignalsSourceMode = "historical" | "live";

type GlobalMarketFiltersProps = {
  activeTab: MarketTab;
  chartMode: ChartMode;
  signalsSourceMode?: SignalsSourceMode;
  apiBaseUrl: string;
  authToken: string;
  instruments: InstrumentOption[];
  symbol: string;
  followed: string[];
  isFollowing: boolean;
  onFollowChange?: () => void;
  candle: CandleCode;
  window: WindowCode;
  manualCandle: boolean;
  periodMode: PeriodMode;
  startDate: string;
  endDate: string;
  streamStatus?: StreamStatus;
  lastBarMs?: number | null;
  nowMs: number;
  onSymbol: (symbol: string) => void;
  onCandle: (candle: CandleCode) => void;
  onWindow: (window: WindowCode) => void;
  onPeriodMode: (mode: PeriodMode) => void;
  onStartDate: (value: string) => void;
  onEndDate: (value: string) => void;
  availableStrategies: string[];
  strategyLabels: Record<string, string>;
  activeStrategies: string[];
  onToggleStrategy: (strategy: string) => void;
  activeIndicators: ReadonlySet<IndicatorId>;
  onToggleIndicator: (id: IndicatorId) => void;
};

export function GlobalMarketFilters({
  activeTab,
  chartMode,
  signalsSourceMode = "historical",
  apiBaseUrl,
  authToken,
  instruments,
  symbol,
  followed,
  isFollowing,
  onFollowChange,
  candle,
  window,
  manualCandle,
  periodMode,
  startDate,
  endDate,
  streamStatus = "closed",
  lastBarMs = null,
  nowMs,
  onSymbol,
  onCandle,
  onWindow,
  onPeriodMode,
  onStartDate,
  onEndDate,
  availableStrategies,
  strategyLabels,
  activeStrategies,
  onToggleStrategy,
  activeIndicators,
  onToggleIndicator,
}: GlobalMarketFiltersProps) {
  const suggested = SUGGESTED_CANDLE[window];
  const derivedLimit = fetchLimitFor(window, candle);
  const symbolName = instruments.find((item) => item.symbol === symbol)?.name ?? null;

  const showPeriodDates =
    activeTab === "signals" || activeTab === "backtests" || chartMode === "historico";
  const showStrategies = activeTab === "signals" || activeTab === "backtests";
  const showIndicators = activeTab === "market";
  const showStreamStatus =
    (activeTab === "market" && chartMode === "aovivo") ||
    (activeTab === "signals" && signalsSourceMode === "live");

  return (
    <div className="rt-page mkt-global-filters">
      <SymbolBar
        apiBaseUrl={apiBaseUrl}
        authToken={authToken}
        symbol={symbol}
        name={symbolName}
        followed={followed}
        isFollowing={isFollowing}
        onFollowChange={onFollowChange}
        onSelect={onSymbol}
        status={streamStatus}
        lastBarMs={lastBarMs}
        nowMs={nowMs}
        showConnection={showStreamStatus}
      />

      <div className="rt-controls">
        {showPeriodDates && (
          <div className="rt-ctrl-row">
            <span className="rt-ctrl-lbl">Período</span>
            <div className="rt-seg">
              <button
                type="button"
                className={periodMode === "window" ? "rt-seg-active" : ""}
                onClick={() => onPeriodMode("window")}
              >
                Janela
              </button>
              <button
                type="button"
                className={periodMode === "date" ? "rt-seg-active" : ""}
                onClick={() => onPeriodMode("date")}
              >
                Datas
              </button>
            </div>
            {periodMode === "window" && (
              <span className="rt-hint">≈ {derivedLimit} velas pedidas à API</span>
            )}
          </div>
        )}

        {(!showPeriodDates || periodMode === "window") && (
          <>
            <div className="rt-ctrl-row">
              <span className="rt-ctrl-lbl">Vela</span>
              <div className="rt-seg">
                {CANDLES.map((code) => {
                  const isActive = code === candle;
                  const isSuggested = code === suggested;
                  const cls = [isActive ? "rt-seg-active" : "", isSuggested ? "rt-seg-suggested" : ""]
                    .filter(Boolean)
                    .join(" ");
                  return (
                    <button key={code} type="button" className={cls} onClick={() => onCandle(code)}>
                      {code}
                    </button>
                  );
                })}
              </div>
              <span className="rt-hint">
                {manualCandle ? "override manual" : `sugerida (${suggested})`}
              </span>
            </div>

            <div className="rt-ctrl-row">
              <span className="rt-ctrl-lbl">Janela</span>
              <div className="rt-seg">
                {WINDOWS.map((option) => (
                  <button
                    key={option.code}
                    type="button"
                    className={option.code === window ? "rt-seg-active" : ""}
                    onClick={() => onWindow(option.code)}
                  >
                    {option.label}
                  </button>
                ))}
              </div>
              <span className="rt-hint">
                ≈ {IBKR_DURATION[window]} · vela sugerida {suggested}
              </span>
            </div>
          </>
        )}

        {showPeriodDates && periodMode === "date" && (
          <div className="rt-ctrl-row mkt-date-row">
            <span className="rt-ctrl-lbl">Datas</span>
            <label className="mkt-date-field">
              <span>Início</span>
              <input type="date" value={startDate} onChange={(event) => onStartDate(event.target.value)} />
            </label>
            <label className="mkt-date-field">
              <span>Fim</span>
              <input type="date" value={endDate} onChange={(event) => onEndDate(event.target.value)} />
            </label>
          </div>
        )}

        {showStrategies && (
          <StrategyToggleRow
            strategies={availableStrategies}
            strategyLabels={strategyLabels}
            active={activeStrategies}
            onToggle={onToggleStrategy}
          />
        )}
        {showIndicators && (
          <IndicatorToggleRow active={activeIndicators} onToggle={onToggleIndicator} />
        )}
      </div>
    </div>
  );
}
