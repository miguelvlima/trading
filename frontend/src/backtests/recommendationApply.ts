export type SuggestedValues = {
  stop_loss_pct?: number;
  take_profit_pct?: number;
  min_consensus_strength_pct?: number;
  entry_confirmation_bars?: number;
  strategy_min_strength_pct?: Record<string, number>;
  strategies?: string[];
  timeframe?: string;
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
  | "strategies"
  | "timeframe"
  | "risk_reset"
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
  timeframe: string;
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
  setActiveStrategies: (strategies: string[]) => void;
  setTimeframe: (timeframe: string) => void;
};

export type RecommendationTargets = {
  strategies?: string[];
  timeframe?: string;
  stop_loss_pct?: number;
  take_profit_pct?: number;
  min_consensus_strength_pct?: number;
  entry_confirmation_bars?: number;
  strategy_min_strength_pct?: Record<string, number>;
  risk_reset?: boolean;
};

export type RecommendationApplyPlan = {
  key: string;
  previews: string[];
  targets: RecommendationTargets;
};

export type AppliedRecommendationRecord = {
  key: string;
  runId: number;
  suggestion: string;
  previews: string[];
  appliedAt: string;
};

export function getRecommendationKey(recommendation: BacktestRecommendation): string {
  return `${recommendation.run_id}:${recommendation.area}:${recommendation.suggestion}`;
}

export function parseParamHints(paramHint: string | null | undefined): ApplicableParam[] {
  if (!paramHint) {
    return [];
  }
  const normalized = paramHint.toLowerCase().trim();
  const params: ApplicableParam[] = [];
  if (normalized === "strategies" || normalized.includes("strategies")) {
    params.push("strategies");
  }
  if (normalized === "timeframe" || normalized.includes("timeframe")) {
    params.push("timeframe");
  }
  if (normalized === "risk_reset") {
    params.push("risk_reset");
  }
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
  if (normalized === "loosen_min_signal_strength" || normalized.includes("loosen_min_signal_strength")) {
    params.push("min_consensus_strength");
    params.push("min_signal_strength");
  }
  return params;
}

function hasExplicitSuggestedValue(
  param: ApplicableParam,
  suggestedValues?: SuggestedValues,
): boolean {
  if (!suggestedValues) {
    return false;
  }
  switch (param) {
    case "strategies":
      return Array.isArray(suggestedValues.strategies) && suggestedValues.strategies.length > 0;
    case "timeframe":
      return typeof suggestedValues.timeframe === "string" && suggestedValues.timeframe.trim().length > 0;
    case "risk_reset":
      return (
        typeof suggestedValues.stop_loss_pct === "number" ||
        typeof suggestedValues.take_profit_pct === "number"
      );
    case "stop_loss_pct":
      return typeof suggestedValues.stop_loss_pct === "number";
    case "take_profit_pct":
      return typeof suggestedValues.take_profit_pct === "number";
    case "min_consensus_strength":
      return typeof suggestedValues.min_consensus_strength_pct === "number";
    case "min_signal_strength":
      return (
        typeof suggestedValues.strategy_min_strength_pct === "object" &&
        suggestedValues.strategy_min_strength_pct !== null &&
        Object.keys(suggestedValues.strategy_min_strength_pct).length > 0
      );
    case "entry_confirmation_bars":
      return typeof suggestedValues.entry_confirmation_bars === "number";
    default:
      return false;
  }
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

function resolveAbsoluteTarget(
  param: ApplicableParam,
  snapshot: BacktestFormSnapshot,
  suggestedValues?: SuggestedValues,
): number | Record<string, number> | string[] | string | null {
  switch (param) {
    case "strategies": {
      const strategies = suggestedValues?.strategies?.filter((item) => item.trim().length > 0);
      if (!strategies || strategies.length === 0) {
        return null;
      }
      const same =
        strategies.length === snapshot.activeStrategies.length &&
        strategies.every((item, index) => item === snapshot.activeStrategies[index]);
      return same ? null : strategies;
    }
    case "timeframe": {
      const next = suggestedValues?.timeframe?.trim();
      if (!next || next === snapshot.timeframe) {
        return null;
      }
      return next;
    }
    case "risk_reset": {
      const stopLoss = suggestedValues?.stop_loss_pct;
      const takeProfit = suggestedValues?.take_profit_pct;
      if (typeof stopLoss !== "number" && typeof takeProfit !== "number") {
        return null;
      }
      const slMatches = typeof stopLoss !== "number" || stopLoss === snapshot.stopLossPct;
      const tpMatches = typeof takeProfit !== "number" || takeProfit === snapshot.takeProfitPct;
      return slMatches && tpMatches ? null : 1;
    }
    case "stop_loss_pct": {
      if (typeof suggestedValues?.stop_loss_pct === "number") {
        return round1(suggestedValues.stop_loss_pct);
      }
      return round1(Math.min(15, snapshot.stopLossPct + 0.5));
    }
    case "take_profit_pct": {
      if (typeof suggestedValues?.take_profit_pct === "number") {
        return round1(suggestedValues.take_profit_pct);
      }
      return round1(Math.min(30, snapshot.takeProfitPct + 1));
    }
    case "min_consensus_strength": {
      if (snapshot.activeStrategies.length <= 1) {
        return null;
      }
      if (typeof suggestedValues?.min_consensus_strength_pct === "number") {
        return Math.min(100, Math.round(suggestedValues.min_consensus_strength_pct));
      }
      return Math.min(100, snapshot.consensusStrengthPct + 10);
    }
    case "min_signal_strength": {
      const perStrategy = suggestedValues?.strategy_min_strength_pct;
      const nextEntries: Record<string, number> = {};
      for (const strategy of snapshot.activeStrategies) {
        const current = snapshot.strategyMinStrengthPct[strategy] ?? 10;
        nextEntries[strategy] =
          typeof perStrategy?.[strategy] === "number"
            ? Math.min(100, Math.round(perStrategy[strategy]))
            : Math.min(100, current + 10);
      }
      return nextEntries;
    }
    case "entry_confirmation_bars": {
      if (typeof suggestedValues?.entry_confirmation_bars === "number") {
        return Math.min(5, Math.round(suggestedValues.entry_confirmation_bars));
      }
      return Math.min(5, snapshot.entryConfirmationBars + 1);
    }
    default:
      return null;
  }
}

function buildPreviewLine(
  param: ApplicableParam,
  snapshot: BacktestFormSnapshot,
  target: number | Record<string, number> | string[] | string,
  suggestedValues?: SuggestedValues,
): string | null {
  const explicit = hasExplicitSuggestedValue(param, suggestedValues);
  switch (param) {
    case "strategies": {
      const next = target as string[];
      return `Estratégia: ${snapshot.activeStrategies.join(", ")} → ${next.join(", ")}`;
    }
    case "timeframe": {
      const next = target as string;
      return `Timeframe: ${snapshot.timeframe} → ${next}`;
    }
    case "risk_reset": {
      const nextSl = suggestedValues?.stop_loss_pct ?? snapshot.stopLossPct;
      const nextTp = suggestedValues?.take_profit_pct ?? snapshot.takeProfitPct;
      return `Repor risco: SL ${snapshot.stopLossPct}%→${nextSl}%, TP ${snapshot.takeProfitPct}%→${nextTp}%`;
    }
    case "stop_loss_pct": {
      const next = target as number;
      if (!explicit && next <= snapshot.stopLossPct) {
        return null;
      }
      if (next === snapshot.stopLossPct) {
        return null;
      }
      return `Stop-loss: ${snapshot.stopLossPct}% → ${next}%`;
    }
    case "take_profit_pct": {
      const next = target as number;
      if (!explicit && next <= snapshot.takeProfitPct) {
        return null;
      }
      if (next === snapshot.takeProfitPct) {
        return null;
      }
      return `Take-profit: ${snapshot.takeProfitPct}% → ${next}%`;
    }
    case "min_consensus_strength": {
      const next = target as number;
      if (!explicit && next <= snapshot.consensusStrengthPct) {
        return null;
      }
      if (next === snapshot.consensusStrengthPct) {
        return null;
      }
      return `Consenso mínimo: ${snapshot.consensusStrengthPct}% → ${next}%`;
    }
    case "min_signal_strength": {
      const nextEntries = target as Record<string, number>;
      const preview = snapshot.activeStrategies
        .map((strategy) => {
          const current = snapshot.strategyMinStrengthPct[strategy] ?? 10;
          const next = nextEntries[strategy];
          if (next === undefined || next === current) {
            return null;
          }
          if (!explicit && next <= current) {
            return null;
          }
          return `${strategy} ${current}%→${next}%`;
        })
        .filter((item): item is string => item !== null);
      return preview.length > 0 ? `Força mínima: ${preview.join(", ")}` : null;
    }
    case "entry_confirmation_bars": {
      const next = target as number;
      if (!explicit && next <= snapshot.entryConfirmationBars) {
        return null;
      }
      if (next === snapshot.entryConfirmationBars) {
        return null;
      }
      return `Confirmação de entrada: ${snapshot.entryConfirmationBars} → ${next} velas`;
    }
    default:
      return null;
  }
}

export function buildRecommendationApplyPlan(
  recommendation: BacktestRecommendation,
  snapshot: BacktestFormSnapshot,
): RecommendationApplyPlan | null {
  const suggestedValues = resolveSuggestedValues(recommendation);
  let params = parseParamHints(recommendation.param_hint);
  if (recommendation.param_hint?.toLowerCase().includes("loosen_min_signal_strength")) {
    params =
      snapshot.activeStrategies.length > 1
        ? ["min_consensus_strength"]
        : ["min_signal_strength"];
  }
  const targets: RecommendationTargets = {};
  const previews: string[] = [];

  for (const param of params) {
    const target = resolveAbsoluteTarget(param, snapshot, suggestedValues);
    if (target === null) {
      continue;
    }
    const preview = buildPreviewLine(param, snapshot, target, suggestedValues);
    if (!preview) {
      continue;
    }
    previews.push(preview);
    switch (param) {
      case "strategies":
        targets.strategies = target as string[];
        break;
      case "timeframe":
        targets.timeframe = target as string;
        break;
      case "risk_reset":
        targets.risk_reset = true;
        if (typeof suggestedValues?.stop_loss_pct === "number") {
          targets.stop_loss_pct = round1(suggestedValues.stop_loss_pct);
        }
        if (typeof suggestedValues?.take_profit_pct === "number") {
          targets.take_profit_pct = round1(suggestedValues.take_profit_pct);
        }
        break;
      case "stop_loss_pct":
        targets.stop_loss_pct = target as number;
        break;
      case "take_profit_pct":
        targets.take_profit_pct = target as number;
        break;
      case "min_consensus_strength":
        targets.min_consensus_strength_pct = target as number;
        break;
      case "min_signal_strength":
        targets.strategy_min_strength_pct = target as Record<string, number>;
        break;
      case "entry_confirmation_bars":
        targets.entry_confirmation_bars = target as number;
        break;
      default:
        break;
    }
  }

  if (previews.length === 0) {
    return null;
  }

  return {
    key: getRecommendationKey(recommendation),
    previews,
    targets,
  };
}

export function applyRecommendationTargets(
  targets: RecommendationTargets,
  snapshot: BacktestFormSnapshot,
  setters: BacktestFormSetters,
): boolean {
  let applied = false;

  if (targets.strategies && targets.strategies.length > 0) {
    const same =
      targets.strategies.length === snapshot.activeStrategies.length &&
      targets.strategies.every((item, index) => item === snapshot.activeStrategies[index]);
    if (!same) {
      setters.setActiveStrategies(targets.strategies);
      applied = true;
    }
  }

  if (targets.timeframe && targets.timeframe !== snapshot.timeframe) {
    setters.setTimeframe(targets.timeframe);
    applied = true;
  }

  const allowRiskReset = targets.risk_reset === true;

  if (typeof targets.stop_loss_pct === "number") {
    const shouldApply = allowRiskReset
      ? targets.stop_loss_pct !== snapshot.stopLossPct
      : targets.stop_loss_pct > snapshot.stopLossPct;
    if (shouldApply) {
      if (snapshot.exitMode === "opposite_signal") {
        setters.setExitMode("tp_sl_or_opposite");
      }
      setters.setStopLossPct(targets.stop_loss_pct);
      applied = true;
    }
  }

  if (typeof targets.take_profit_pct === "number") {
    const shouldApply = allowRiskReset
      ? targets.take_profit_pct !== snapshot.takeProfitPct
      : targets.take_profit_pct > snapshot.takeProfitPct;
    if (shouldApply) {
      if (snapshot.exitMode === "opposite_signal") {
        setters.setExitMode("tp_sl_or_opposite");
      }
      setters.setTakeProfitPct(targets.take_profit_pct);
      applied = true;
    }
  }

  if (
    typeof targets.min_consensus_strength_pct === "number" &&
    targets.min_consensus_strength_pct !== snapshot.consensusStrengthPct
  ) {
    setters.setConsensusStrengthPct(targets.min_consensus_strength_pct);
    applied = true;
  }

  if (targets.strategy_min_strength_pct) {
    let strategyApplied = false;
    setters.setStrategyMinStrengthPct((previous) => {
      const next = { ...previous };
      for (const [strategy, value] of Object.entries(targets.strategy_min_strength_pct ?? {})) {
        const current = next[strategy] ?? 10;
        if (value !== current) {
          next[strategy] = value;
          strategyApplied = true;
        }
      }
      return next;
    });
    applied = applied || strategyApplied;
  }

  if (
    typeof targets.entry_confirmation_bars === "number" &&
    targets.entry_confirmation_bars !== snapshot.entryConfirmationBars
  ) {
    setters.setEntryConfirmationBars(targets.entry_confirmation_bars);
    applied = true;
  }

  return applied;
}

/** @deprecated Use buildRecommendationApplyPlan */
export function buildRecommendationApplyPreview(
  recommendation: BacktestRecommendation,
  snapshot: BacktestFormSnapshot,
): string[] {
  return buildRecommendationApplyPlan(recommendation, snapshot)?.previews ?? [];
}

/** @deprecated Use applyRecommendationTargets via buildRecommendationApplyPlan */
export function applyRecommendation(
  recommendation: BacktestRecommendation,
  snapshot: BacktestFormSnapshot,
  setters: BacktestFormSetters,
): boolean {
  const plan = buildRecommendationApplyPlan(recommendation, snapshot);
  if (!plan) {
    return false;
  }
  return applyRecommendationTargets(plan.targets, snapshot, setters);
}

export function isRecommendationReadOnly(recommendation: BacktestRecommendation): boolean {
  return parseParamHints(recommendation.param_hint).length === 0;
}

export function isRecommendationApplied(
  recommendation: BacktestRecommendation,
  appliedRecords: AppliedRecommendationRecord[],
): AppliedRecommendationRecord | undefined {
  const key = getRecommendationKey(recommendation);
  return appliedRecords.find((record) => record.key === key);
}

export function isRecommendationFulfilled(
  recommendation: BacktestRecommendation,
  snapshot: BacktestFormSnapshot,
  appliedRecords: AppliedRecommendationRecord[],
): boolean {
  const appliedRecord = isRecommendationApplied(recommendation, appliedRecords);
  if (!appliedRecord) {
    return false;
  }
  return buildRecommendationApplyPlan(recommendation, snapshot) === null;
}

export function buildPendingFormChangesSummary(
  recommendations: BacktestRecommendation[],
  appliedRecords: AppliedRecommendationRecord[],
  snapshot: BacktestFormSnapshot,
): string[] {
  const lines = new Set<string>();
  for (const record of appliedRecords) {
    const recommendation = recommendations.find((item) => getRecommendationKey(item) === record.key);
    if (!recommendation) {
      for (const preview of record.previews) {
        lines.add(preview);
      }
      continue;
    }
    if (!isRecommendationFulfilled(recommendation, snapshot, appliedRecords)) {
      continue;
    }
    for (const preview of record.previews) {
      lines.add(preview);
    }
  }
  return Array.from(lines);
}

export function countFulfilledRecommendations(
  recommendations: BacktestRecommendation[],
  appliedRecords: AppliedRecommendationRecord[],
  snapshot: BacktestFormSnapshot,
): number {
  return recommendations.filter((recommendation) =>
    isRecommendationFulfilled(recommendation, snapshot, appliedRecords),
  ).length;
}
