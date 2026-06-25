import {
  type CandleCode,
  type WindowCode,
  CANDLES,
  IBKR_DURATION,
  SUGGESTED_CANDLE,
  WINDOWS,
} from "./windowCandle";
import {
  type IndicatorId,
  INDICATORS,
  indicatorLabel,
} from "./indicators";

type ChartControlsProps = {
  window: WindowCode;
  candle: CandleCode;
  manualCandle: boolean;
  active: ReadonlySet<IndicatorId>;
  onWindow: (w: WindowCode) => void;
  onCandle: (c: CandleCode) => void;
  onToggleIndicator: (id: IndicatorId) => void;
};

// Two control rows (candle, window) kept separate from the data panels, plus
// indicator toggles. Window selection drives a suggested candle; the user can
// override it, which the UI labels as "manual".
export function ChartControls({
  window,
  candle,
  manualCandle,
  active,
  onWindow,
  onCandle,
  onToggleIndicator,
}: ChartControlsProps) {
  const suggested = SUGGESTED_CANDLE[window];

  return (
    <div className="rt-controls">
      <div className="rt-ctrl-row">
        <span className="rt-ctrl-lbl">Vela</span>
        <div className="rt-seg">
          {CANDLES.map((c) => {
            const isActive = c === candle;
            const isSuggested = c === suggested;
            const cls = [
              isActive ? "rt-seg-active" : "",
              isSuggested ? "rt-seg-suggested" : "",
            ]
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

      <div className="rt-ctrl-row">
        <span className="rt-ctrl-lbl">Indicadores</span>
        <div className="rt-ind-toggles">
          {INDICATORS.map((d) => {
            const on = active.has(d.id);
            return (
              <button
                key={d.id}
                type="button"
                className={on ? "rt-ind rt-ind-on" : "rt-ind"}
                onClick={() => onToggleIndicator(d.id)}
              >
                {indicatorLabel(d)}
                {on && <span className="rt-ind-x">×</span>}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
