export type BacktestWorkspaceTab = "results" | "data" | "recommendations" | "presets" | "lessons";

export type BacktestWorkspaceTabItem = {
  id: BacktestWorkspaceTab;
  label: string;
  badge?: number;
  emphasis?: boolean;
};

type BacktestWorkspaceTabBarProps = {
  active: BacktestWorkspaceTab;
  items: BacktestWorkspaceTabItem[];
  onChange: (tab: BacktestWorkspaceTab) => void;
};

export function BacktestWorkspaceTabBar({ active, items, onChange }: BacktestWorkspaceTabBarProps) {
  return (
    <nav className="backtest-workspace-tabs" aria-label="Ferramentas e resultados">
      <div className="rt-seg backtest-workspace-seg">
        {items.map((item) => {
          const isActive = active === item.id;
          const className = [
            isActive ? "rt-seg-active" : "",
            item.emphasis && !isActive ? "backtest-workspace-tab-emphasis" : "",
          ]
            .filter(Boolean)
            .join(" ");
          return (
            <button
              key={item.id}
              type="button"
              className={className}
              aria-current={isActive ? "page" : undefined}
              onClick={() => onChange(item.id)}
            >
              <span>{item.label}</span>
              {item.badge !== undefined && item.badge > 0 && (
                <span className="backtest-workspace-tab-badge">{item.badge}</span>
              )}
            </button>
          );
        })}
      </div>
    </nav>
  );
}
