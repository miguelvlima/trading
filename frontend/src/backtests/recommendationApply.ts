export type SuggestedValues = {
  stop_loss_pct?: number;
  take_profit_pct?: number;
  min_consensus_strength_pct?: number;
  entry_confirmation_bars?: number;
  strategy_min_strength_pct?: Record<string, number>;
};

export type BacktestRecommendation = {
  area: string;
  suggestion: string;
  rationale: string;
  param_hint: string | null;
  suggested_values?: SuggestedValues | null;
  symbol: string;
  strategy_names: string[];
  run_id: number;
  created_at: string;
};

export type ApplicableParam =
  | "stop_loss_pct"
  | "take_profit_pct"
  | "min_consensus_strength"
  | "min_signal_strength"
  | "entry_confirmation_bars";

export type BacktestExitMode = "opposite_signal" | "tp_sl_or_opposite" | "tp_sl_only";

export type BacktestFormSnapshot = {
  exitMode: BacktestExitMode;
  stopLossPct: number;
  takeProfitPct: number;
  consensusStrengthPct: number;
  entryConfirmationBars: number;
  activeStrategies: string[];
  strategyMinStrengthPct: Record<string, number>;
};

export type BacktestFormSetters = {
  setExitMode: (mode: BacktestExitMode) => void;
  setStopLossPct: (value: number) => void;
  setTakeProfitPct: (value: number) => void;
  setConsensusStrengthPct: (value: number) => void;
  setEntryConfirmationBars: (value: number) => void;
  setStrategyMinStrengthPct: (
    updater: (previous: Record<string, number>) => Record<string, number>,
  ) => void;
};

export function parseParamHints(paramHint: string | null | undefined): ApplicableParam[] {
  if (!paramHint) {
    return [];
  }
  const normalized = paramHint.toLowerCase();
  const params: ApplicableParam[] = [];
  if (normalized.includes("stop_loss_pct")) {
    params.push("stop_loss_pct");
  }
  if (normalized.includes("take_profit_pct")) {
    params.push("take_profit_pct");
  }
  if (normalized.includes("min_consensus_strength")) {
    params.push("min_consensus_strength");
  }
  if (normalized.includes("min_signal_strength")) {
    params.push("min_signal_strength");
  }
  if (normalized.includes("entry_confirmation_bars")) {
    params.push("entry_confirmation_bars");
  }
  return params;
}

function round1(value: number): number {
  return Math.round(value * 10) / 10;
}

function resolveSuggestedValues(
  recommendation?: Pick<BacktestRecommendation, "suggested_values">,
): SuggestedValues | undefined {
  const values = recommendation?.suggested_values;
  if (!values || typeof values !== "object") {
    return undefined;
  }
  return values;
}

export function buildParamApplyPreview(
  param: ApplicableParam,
  snapshot: BacktestFormSnapshot,
  suggestedValues?: SuggestedValues,
): string | null {
  switch (param) {
    case "stop_loss_pct": {
      const target =
        typeof suggestedValues?.stop_loss_pct === "number"
          ? round1(suggestedValues.stop_loss_pct)
          : round1(Math.min(15, snapshot.stopLossPct + 0.5));
      if (target <= snapshot.stopLossPct) {
        return null;
      }
      return `Stop-loss: ${snapshot.stopLossPct}% → ${target}%`;
    }
    case "take_profit_pct": {
      const target =
        typeof suggestedValues?.take_profit_pct === "number"
          ? round1(suggestedValues.take_profit_pct)
          : round1(Math.min(30, snapshot.takeProfitPct + 1));
      if (target <= snapshot.takeProfitPct) {
        return null;
      }
      return `Take-profit: ${snapshot.takeProfitPct}% → ${target}%`;
    }
    case "min_consensus_strength": {
      if (snapshot.activeStrategies.length <= 1) {
        return null;
      }
      const target =
        typeof suggestedValues?.min_consensus_strength_pct === "number"
          ? Math.min(100, Math.round(suggestedValues.min_consensus_strength_pct))
          : Math.min(100, snapshot.consensusStrengthPct + 10);
      if (target <= snapshot.consensusStrengthPct) {
        return null;
      }
      return `Consenso mínimo: ${snapshot.consensusStrengthPct}% → ${target}%`;
    }
    case "min_signal_strength": {
      const perStrategy = suggestedValues?.strategy_min_strength_pct;
      const nextEntries = Object.fromEntries(
        snapshot.activeStrategies.map((strategy) => {
          const current = snapshot.strategyMinStrengthPct[strategy] ?? 10;
          const target =
            typeof perStrategy?.[strategy] === "number"
              ? Math.min(100, Math.round(perStrategy[strategy]))
              : Math.min(100, current + 10);
          return [strategy, target];
        }),
      );
      const changed = snapshot.activeStrategies.some((strategy) => {
        const current = snapshot.strategyMinStrengthPct[strategy] ?? 10;
        return nextEntries[strategy] > current;
      });
      if (!changed) {
        return null;
      }
      if (perStrategy) {
        const preview = snapshot.activeStrategies
          .map((strategy) => {
            const current = snapshot.strategyMinStrengthPct[strategy] ?? 10;
            const target = nextEntries[strategy];
            return target > current ? `${strategy} ${current}%→${target}%` : null;
          })
          .filter((item): item is string => item !== null);
        return preview.length > 0 ? `Força mínima: ${preview.join(", ")}` : null;
      }
      return `Força mínima por estratégia: +10 p.p. (${snapshot.activeStrategies.length} estratégias)`;
    }
    case "entry_confirmation_bars": {
      const target =
        typeof suggestedValues?.entry_confirmation_bars === "number"
          ? Math.min(5, Math.round(suggestedValues.entry_confirmation_bars))
          : Math.min(5, snapshot.entryConfirmationBars + 1);
      if (target <= snapshot.entryConfirmationBars) {
        return null;
      }
      return `Confirmação de entrada: ${snapshot.entryConfirmationBars} → ${target} velas`;
    }
    default:
      return null;
  }
}

export function applyParamChange(
  param: ApplicableParam,
  snapshot: BacktestFormSnapshot,
  setters: BacktestFormSetters,
  suggestedValues?: SuggestedValues,
): boolean {
  switch (param) {
    case "stop_loss_pct": {
      const next =
        typeof suggestedValues?.stop_loss_pct === "number"
          ? round1(suggestedValues.stop_loss_pct)
          : round1(Math.min(15, snapshot.stopLossPct + 0.5));
      if (next <= snapshot.stopLossPct) {
        return false;
      }
      if (snapshot.exitMode === "opposite_signal") {
        setters.setExitMode("tp_sl_or_opposite");
      }
      setters.setStopLossPct(next);
      return true;
    }
    case "take_profit_pct": {
      const next =
        typeof suggestedValues?.take_profit_pct === "number"
          ? round1(suggestedValues.take_profit_pct)
          : round1(Math.min(30, snapshot.takeProfitPct + 1));
      if (next <= snapshot.takeProfitPct) {
        return false;
      }
      if (snapshot.exitMode === "opposite_signal") {
        setters.setExitMode("tp_sl_or_opposite");
      }
      setters.setTakeProfitPct(next);
      return true;
    }
    case "min_consensus_strength": {
      if (snapshot.activeStrategies.length <= 1) {
        return false;
      }
      const next =
        typeof suggestedValues?.min_consensus_strength_pct === "number"
          ? Math.min(100, Math.round(suggestedValues.min_consensus_strength_pct))
          : Math.min(100, snapshot.consensusStrengthPct + 10);
      if (next <= snapshot.consensusStrengthPct) {
        return false;
      }
      setters.setConsensusStrengthPct(next);
      return true;
    }
    case "min_signal_strength": {
      const perStrategy = suggestedValues?.strategy_min_strength_pct;
      let applied = false;
      setters.setStrategyMinStrengthPct((previous) => {
        const next = { ...previous };
        for (const strategy of snapshot.activeStrategies) {
          const current = next[strategy] ?? 10;
          const bumped =
            typeof perStrategy?.[strategy] === "number"
              ? Math.min(100, Math.round(perStrategy[strategy]))
              : Math.min(100, current + 10);
          if (bumped > current) {
            next[strategy] = bumped;
            applied = true;
          }
        }
        return next;
      });
      return applied;
    }
    case "entry_confirmation_bars": {
      const next =
        typeof suggestedValues?.entry_confirmation_bars === "number"
          ? Math.min(5, Math.round(suggestedValues.entry_confirmation_bars))
          : Math.min(5, snapshot.entryConfirmationBars + 1);
      if (next <= snapshot.entryConfirmationBars) {
        return false;
      }
      setters.setEntryConfirmationBars(next);
      return true;
    }
    default:
      return false;
  }
}

export function buildRecommendationApplyPreview(
  recommendation: BacktestRecommendation,
  snapshot: BacktestFormSnapshot,
): string[] {
  const suggestedValues = resolveSuggestedValues(recommendation);
  const params = parseParamHints(recommendation.param_hint);
  const lines: string[] = [];
  for (const param of params) {
    const preview = buildParamApplyPreview(param, snapshot, suggestedValues);
    if (preview) {
      lines.push(preview);
    }
  }
  return lines;
}

export function applyRecommendation(
  recommendation: BacktestRecommendation,
  snapshot: BacktestFormSnapshot,
  setters: BacktestFormSetters,
): boolean {
  const suggestedValues = resolveSuggestedValues(recommendation);
  const params = parseParamHints(recommendation.param_hint);
  let applied = false;
  for (const param of params) {
    if (applyParamChange(param, snapshot, setters, suggestedValues)) {
      applied = true;
    }
  }
  return applied;
}

export function isRecommendationReadOnly(recommendation: BacktestRecommendation): boolean {
  return parseParamHints(recommendation.param_hint).length === 0;
}
