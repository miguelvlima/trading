import { IndicatorToggleRow } from "../market/IndicatorToggleRow";
import {
  type CandleCode,
  type WindowCode,
  CANDLES,
  IBKR_DURATION,
  SUGGESTED_CANDLE,
  WINDOWS,
} from "./windowCandle";
import { type IndicatorId } from "./indicators";

type ChartControlsProps = {
  window: WindowCode;
  candle: CandleCode;
  manualCandle: boolean;
  active: ReadonlySet<IndicatorId>;
  onWindow: (w: WindowCode) => void;
  onCandle: (c: CandleCode) => void;
  onToggleIndicator: (id: IndicatorId) => void;
  hideTimeframeRows?: boolean;
  hideIndicatorRows?: boolean;
};

export function ChartControls({
  window,
  candle,
  manualCandle,
  active,
  onWindow,
  onCandle,
  onToggleIndicator,
  hideTimeframeRows = false,
  hideIndicatorRows = false,
}: ChartControlsProps) {
  const suggested = SUGGESTED_CANDLE[window];

  if (hideTimeframeRows && hideIndicatorRows) {
    return null;
  }

  return (
    <div className="rt-controls">
      {!hideTimeframeRows && (
        <>
          <div className="rt-ctrl-row">
            <span className="rt-ctrl-lbl">Vela</span>
            <div className="rt-seg">
              {CANDLES.map((c) => {
                const isActive = c === candle;
                const isSuggested = c === suggested;
                const cls = [isActive ? "rt-seg-active" : "", isSuggested ? "rt-seg-suggested" : ""]
                  .filter(Boolean)
                  .join(" ");
                return (
                  <button key={c} type="button" className={cls} onClick={() => onCandle(c)}>
                    {c}
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
              {WINDOWS.map((w) => (
                <button
                  key={w.code}
                  type="button"
                  className={w.code === window ? "rt-seg-active" : ""}
                  onClick={() => onWindow(w.code)}
                >
                  {w.label}
                </button>
              ))}
            </div>
            <span className="rt-hint">
              ≈ {IBKR_DURATION[window]} do IBKR · vela sugerida {suggested}
            </span>
          </div>
        </>
      )}

      {!hideIndicatorRows && <IndicatorToggleRow active={active} onToggle={onToggleIndicator} />}
    </div>
  );
}
