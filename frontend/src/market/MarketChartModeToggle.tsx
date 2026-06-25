import "./market-filters.css";

export type ChartMode = "historico" | "aovivo";

type MarketChartModeToggleProps = {
  mode: ChartMode;
  onChange: (mode: ChartMode) => void;
};

export function MarketChartModeToggle({ mode, onChange }: MarketChartModeToggleProps) {
  return (
    <div className="mkt-chart-mode-bar" role="group" aria-label="Modo do gráfico">
      <div className="rt-seg mkt-chart-mode-seg">
        <button
          type="button"
          className={mode === "historico" ? "rt-seg-active" : ""}
          onClick={() => onChange("historico")}
        >
          Histórico
        </button>
        <button
          type="button"
          className={mode === "aovivo" ? "rt-seg-active" : ""}
          onClick={() => onChange("aovivo")}
        >
          Ao vivo
        </button>
      </div>
    </div>
  );
}
