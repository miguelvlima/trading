import { INDICATORS, type IndicatorId, indicatorLabel } from "../realtime/indicators";

type IndicatorToggleRowProps = {
  active: ReadonlySet<IndicatorId>;
  onToggle: (id: IndicatorId) => void;
};

export function IndicatorToggleRow({ active, onToggle }: IndicatorToggleRowProps) {
  return (
    <div className="rt-ctrl-row">
      <span className="rt-ctrl-lbl">Indicadores</span>
      <div className="rt-ind-toggles">
        {INDICATORS.map((descriptor) => {
          const on = active.has(descriptor.id);
          return (
            <button
              key={descriptor.id}
              type="button"
              className={on ? "rt-ind rt-ind-on" : "rt-ind"}
              onClick={() => onToggle(descriptor.id)}
            >
              {indicatorLabel(descriptor)}
              {on && <span className="rt-ind-x">×</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}
