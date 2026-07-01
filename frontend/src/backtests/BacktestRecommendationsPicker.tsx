import { useEffect, useMemo, useState } from "react";
import {
  BACKTEST_MIN_BARS,
  type RecommendationAvailabilityContext,
  validateRecommendationTargets,
} from "./backtestBarAvailability";
import {
  isProtectedWinningRun,
  type RunPerformanceSnapshot,
} from "./backtestRunPolicy";
import {
  type AppliedRecommendationRecord,
  type BacktestFormSetters,
  type BacktestFormSnapshot,
  type BacktestRecommendation,
  applyRecommendationTargets,
} from "./recommendationApply";
import {
  buildAppliedRecordsFromOptions,
  buildRecommendationPickerModel,
  isOptionApplied,
  mergeSelectedOptionPlans,
  type SelectableRecommendationOption,
} from "./recommendationPicker";

type BacktestRecommendationsPickerProps = {
  recommendations: BacktestRecommendation[];
  snapshot: BacktestFormSnapshot;
  appliedRecords: AppliedRecommendationRecord[];
  loading: boolean;
  symbol: string;
  sourceRunLabel?: string | null;
  barCountsByTimeframe: Record<string, number>;
  latestSymbolRun: RunPerformanceSnapshot | null;
  setters: BacktestFormSetters;
  onApplied: (records: AppliedRecommendationRecord[]) => void;
  onError: (message: string | null) => void;
  onViewRun: (runId: number) => void;
};

export function BacktestRecommendationsPicker({
  recommendations,
  snapshot,
  appliedRecords,
  loading,
  symbol,
  sourceRunLabel,
  barCountsByTimeframe,
  latestSymbolRun,
  setters,
  onApplied,
  onError,
  onViewRun,
}: BacktestRecommendationsPickerProps) {
  const availability = useMemo(
    (): RecommendationAvailabilityContext => ({
      minBars: BACKTEST_MIN_BARS,
      barCountsByTimeframe,
    }),
    [barCountsByTimeframe],
  );

  const model = useMemo(
    () => buildRecommendationPickerModel(recommendations, snapshot, availability),
    [recommendations, snapshot, availability],
  );
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  useEffect(() => {
    setSelectedIds([]);
  }, [model.runId, symbol]);

  const selectedOptions = model.options.filter((option) => selectedIds.includes(option.id));
  const mergedPreview = mergeSelectedOptionPlans(selectedOptions);
  const pendingOptions = model.options.filter(
    (option) => !isOptionApplied(option, appliedRecords) && !option.disabled,
  );
  const allPendingSelected =
    pendingOptions.length > 0 && pendingOptions.every((option) => selectedIds.includes(option.id));

  const toggleOption = (optionId: string) => {
    setSelectedIds((previous) =>
      previous.includes(optionId)
        ? previous.filter((id) => id !== optionId)
        : [...previous, optionId],
    );
  };

  const toggleSelectAllPending = () => {
    if (allPendingSelected) {
      setSelectedIds([]);
      return;
    }
    setSelectedIds(pendingOptions.map((option) => option.id));
  };

  const handleApplySelected = () => {
    if (!mergedPreview || selectedOptions.length === 0) {
      onError("Selecciona pelo menos uma alteração para aplicar.");
      return;
    }
    if (selectedOptions.some((option) => option.disabled)) {
      onError("Uma das alterações seleccionadas não é aplicável com os dados actuais.");
      return;
    }
    const validationError = validateRecommendationTargets(mergedPreview.targets, availability);
    if (validationError) {
      onError(validationError);
      return;
    }
    const applied = applyRecommendationTargets(mergedPreview.targets, snapshot, setters);
    if (!applied) {
      onError("Não foi possível aplicar as alterações seleccionadas.");
      return;
    }
    const newRecords = buildAppliedRecordsFromOptions(selectedOptions);
    onApplied(newRecords);
    setSelectedIds([]);
    onError(null);
  };

  if (loading) {
    return <p className="hint">A carregar sugestões...</p>;
  }

  if (latestSymbolRun && isProtectedWinningRun(latestSymbolRun)) {
    return (
      <p className="hint backtest-rec-protected-win">
        Último run positivo ({(latestSymbolRun.net_pnl_pct * 100).toFixed(1)}%, PF{" "}
        {latestSymbolRun.profit_factor.toFixed(2)}) — o motor não sugere alterações. Podes
        mudar o formulário manualmente quando quiseres.
      </p>
    );
  }

  if (recommendations.length === 0) {
    return <p className="hint">Ainda sem sugestões para {symbol}. Corre uma simulação primeiro.</p>;
  }

  if (model.options.length === 0 && model.guidance.length === 0) {
    return (
      <p className="hint">
        O último run não tem ajustes automáticos — a configuração actual já reflecte as sugestões ou só há
        orientação estratégica.
      </p>
    );
  }

  return (
    <div className="backtest-rec-picker">
      <p className="hint backtest-rec-picker-intro">
        {sourceRunLabel
          ? `Com base em ${sourceRunLabel}. Escolhe o que queres testar no próximo run.`
          : model.runId !== null
            ? `Com base no último run de ${symbol}. Escolhe o que queres testar no próximo run.`
            : `Sugestões para ${symbol}. Escolhe o que queres testar no próximo run.`}
      </p>

      {model.guidance.length > 0 && (
        <section className="backtest-rec-guidance">
          <strong className="stats-label">Orientação (não altera o formulário)</strong>
          <ul className="backtest-rec-guidance-list">
            {model.guidance.map((item) => (
              <li key={item.key}>
                <span>{item.suggestion}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {model.options.length > 0 && (
        <section className="backtest-rec-actions">
          <div className="backtest-rec-actions-header">
            <strong className="stats-label">Alterações sugeridas</strong>
            {pendingOptions.length > 1 && (
              <button type="button" className="config-button" onClick={toggleSelectAllPending}>
                {allPendingSelected ? "Limpar selecção" : "Seleccionar todas"}
              </button>
            )}
          </div>
          <ul className="backtest-rec-option-list">
            {model.options.map((option) => (
              <RecommendationOptionRow
                key={option.id}
                option={option}
                checked={selectedIds.includes(option.id)}
                applied={isOptionApplied(option, appliedRecords)}
                onToggle={() => toggleOption(option.id)}
              />
            ))}
          </ul>
        </section>
      )}

      {mergedPreview && selectedOptions.length > 0 && (
        <div className="backtest-rec-preview">
          <strong className="stats-label">Resumo do que será aplicado</strong>
          <ul>
            {mergedPreview.previews.map((line) => (
              <li key={line}>{line}</li>
            ))}
          </ul>
        </div>
      )}

      <div className="backtest-rec-footer">
        {model.runId !== null && (
          <button type="button" className="config-button" onClick={() => onViewRun(model.runId!)}>
            Ver run de origem
          </button>
        )}
        {model.options.length > 0 && (
          <button
            type="button"
            className="tab-button"
            disabled={selectedOptions.length === 0}
            onClick={handleApplySelected}
          >
            Aplicar selecionadas ({selectedOptions.length})
          </button>
        )}
      </div>
    </div>
  );
}

function RecommendationOptionRow({
  option,
  checked,
  applied,
  onToggle,
}: {
  option: SelectableRecommendationOption;
  checked: boolean;
  applied: boolean;
  onToggle: () => void;
}) {
  return (
    <li className={applied ? "backtest-rec-option backtest-rec-option-applied" : "backtest-rec-option"}>
      <label className="backtest-rec-option-label">
        <input
          type="checkbox"
          checked={checked}
          disabled={applied || option.disabled}
          onChange={onToggle}
        />
        <span className="backtest-rec-option-text">
          <strong>{option.label}</strong>
          <span className="hint">{option.disabledReason ?? option.preview}</span>
        </span>
      </label>
      {applied && <span className="backtest-lesson-badge backtest-lesson-badge-applied">Já aplicada</span>}
      {!applied && option.disabled && (
        <span className="backtest-lesson-badge">Indisponível</span>
      )}
    </li>
  );
}
