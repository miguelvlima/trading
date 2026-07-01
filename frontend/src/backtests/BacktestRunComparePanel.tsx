import {
  buildBacktestRunComparison,
  formatBacktestRunLabel,
  type CompareRowCategory,
  type CompareRunInput,
} from "./runCompare";

type BacktestRunComparePanelProps = {
  left: CompareRunInput;
  right: CompareRunInput;
};

const CATEGORY_LABELS: Record<CompareRowCategory, string> = {
  data: "Dados e período",
  config: "Configuração",
  result: "Resultado",
};

const CATEGORY_ORDER: CompareRowCategory[] = ["data", "config", "result"];

export function BacktestRunComparePanel({ left, right }: BacktestRunComparePanelProps) {
  const comparison = buildBacktestRunComparison(left, right);

  return (
    <div className="backtest-compare-panel">
      <div className="backtest-compare-header">
        <h4>
          Comparação · {formatBacktestRunLabel(left)} vs {formatBacktestRunLabel(right)}
        </h4>
        <p className="hint backtest-compare-narrative">{comparison.narrative}</p>
      </div>

      {comparison.configIdentical && comparison.dataScopeDiffers && (
        <div className="backtest-compare-alert" role="status">
          Mesma configuração, <strong>dados diferentes</strong> — o resultado não tem de coincidir.
        </div>
      )}

      <div className="backtest-compare-run-labels">
        <span />
        <span>{formatBacktestRunLabel(left)}</span>
        <span>{formatBacktestRunLabel(right)}</span>
      </div>

      {CATEGORY_ORDER.map((category) => {
        const categoryRows = comparison.rows.filter((row) => row.category === category);
        if (categoryRows.length === 0) {
          return null;
        }
        return (
          <section key={category} className="backtest-compare-section">
            <h5 className="backtest-compare-section-title">{CATEGORY_LABELS[category]}</h5>
            <div className="backtest-compare-table">
              {categoryRows.map((row) => (
                <div
                  key={row.key}
                  className={row.differs ? "backtest-compare-row backtest-compare-row-diff" : "backtest-compare-row"}
                >
                  <span className="backtest-compare-label">{row.label}</span>
                  <span className="backtest-compare-value">{row.left}</span>
                  <span className="backtest-compare-value">{row.right}</span>
                </div>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
