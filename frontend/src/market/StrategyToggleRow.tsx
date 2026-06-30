type StrategyToggleRowProps = {
  strategies: string[];
  strategyLabels: Record<string, string>;
  active: string[];
  onToggle: (strategy: string) => void;
};

export function StrategyToggleRow({
  strategies,
  strategyLabels,
  active,
  onToggle,
}: StrategyToggleRowProps) {
  return (
    <div className="rt-ctrl-row">
      <span className="rt-ctrl-lbl">Estratégias</span>
      <div className="rt-ind-toggles">
        {strategies.map((strategy) => {
          const on = active.includes(strategy);
          return (
            <button
              key={strategy}
              type="button"
              className={on ? "rt-ind rt-ind-on" : "rt-ind"}
              onClick={() => onToggle(strategy)}
            >
              {strategyLabels[strategy] ?? strategy}
              {on && <span className="rt-ind-x">×</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}
