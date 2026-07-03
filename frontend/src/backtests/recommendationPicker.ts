import {
  type ApplicableParam,
  type AppliedRecommendationRecord,
  type BacktestFormSnapshot,
  type BacktestRecommendation,
  type RecommendationApplyPlan,
  type RecommendationTargets,
  buildRecommendationApplyPlan,
  getRecommendationKey,
  isRecommendationReadOnly,
  parseParamHints,
} from "./recommendationApply";
import {
  type RecommendationAvailabilityContext,
  isTimeframeViable,
} from "./backtestBarAvailability";

export type RecommendationGuidance = {
  key: string;
  suggestion: string;
  rationale: string;
  runId: number;
};

export type SelectableRecommendationOption = {
  id: string;
  recommendationKey: string;
  param: ApplicableParam;
  label: string;
  preview: string;
  plan: RecommendationApplyPlan;
  runId: number;
  disabled?: boolean;
  disabledReason?: string;
};

const PARAM_SHORT_LABELS: Record<ApplicableParam, string> = {
  strategies: "Trocar estratégia",
  timeframe: "Mudar timeframe",
  risk_reset: "Repor SL/TP base",
  stop_loss_pct: "Aumentar stop-loss",
  take_profit_pct: "Aumentar take-profit",
  min_consensus_strength: "Filtrar entradas (consenso)",
  min_signal_strength: "Filtrar entradas (força por estratégia)",
  entry_confirmation_bars: "Exigir mais confirmação na entrada",
};

export function getLatestRunRecommendations(recommendations: BacktestRecommendation[]): {
  runId: number | null;
  items: BacktestRecommendation[];
} {
  if (recommendations.length === 0) {
    return { runId: null, items: [] };
  }
  const latestRunId = Math.max(...recommendations.map((item) => item.run_id));
  return {
    runId: latestRunId,
    items: recommendations.filter((item) => item.run_id === latestRunId),
  };
}

function buildSingleParamApplyPlan(
  recommendation: BacktestRecommendation,
  snapshot: BacktestFormSnapshot,
  param: ApplicableParam,
): RecommendationApplyPlan | null {
  const fullPlan = buildRecommendationApplyPlan(recommendation, snapshot);
  if (!fullPlan) {
    return null;
  }
  const preview = fullPlan.previews.find((line) => previewMatchesParam(line, param));
  if (!preview) {
    return null;
  }
  const targets: RecommendationTargets = {};
  switch (param) {
    case "strategies":
      if (fullPlan.targets.strategies) {
        targets.strategies = fullPlan.targets.strategies;
      }
      break;
    case "timeframe":
      if (fullPlan.targets.timeframe) {
        targets.timeframe = fullPlan.targets.timeframe;
      }
      break;
    case "risk_reset":
      targets.risk_reset = true;
      if (typeof fullPlan.targets.stop_loss_pct === "number") {
        targets.stop_loss_pct = fullPlan.targets.stop_loss_pct;
      }
      if (typeof fullPlan.targets.take_profit_pct === "number") {
        targets.take_profit_pct = fullPlan.targets.take_profit_pct;
      }
      break;
    case "stop_loss_pct":
      if (typeof fullPlan.targets.stop_loss_pct === "number") {
        targets.stop_loss_pct = fullPlan.targets.stop_loss_pct;
      }
      break;
    case "take_profit_pct":
      if (typeof fullPlan.targets.take_profit_pct === "number") {
        targets.take_profit_pct = fullPlan.targets.take_profit_pct;
      }
      break;
    case "min_consensus_strength":
      if (typeof fullPlan.targets.min_consensus_strength_pct === "number") {
        targets.min_consensus_strength_pct = fullPlan.targets.min_consensus_strength_pct;
      }
      break;
    case "min_signal_strength":
      if (fullPlan.targets.strategy_min_strength_pct) {
        targets.strategy_min_strength_pct = fullPlan.targets.strategy_min_strength_pct;
      }
      break;
    case "entry_confirmation_bars":
      if (typeof fullPlan.targets.entry_confirmation_bars === "number") {
        targets.entry_confirmation_bars = fullPlan.targets.entry_confirmation_bars;
      }
      break;
    default:
      break;
  }
  if (Object.keys(targets).length === 0) {
    return null;
  }
  return {
    key: `${getRecommendationKey(recommendation)}:${param}`,
    previews: [preview],
    targets,
  };
}

function previewMatchesParam(preview: string, param: ApplicableParam): boolean {
  switch (param) {
    case "strategies":
      return preview.startsWith("Estratégia:");
    case "timeframe":
      return preview.startsWith("Timeframe:");
    case "risk_reset":
      return preview.startsWith("Repor risco:");
    case "stop_loss_pct":
      return preview.startsWith("Stop-loss:");
    case "take_profit_pct":
      return preview.startsWith("Take-profit:");
    case "min_consensus_strength":
      return preview.startsWith("Consenso mínimo:");
    case "min_signal_strength":
      return preview.startsWith("Força mínima:");
    case "entry_confirmation_bars":
      return preview.startsWith("Confirmação de entrada:");
    default:
      return false;
  }
}

function targetStrength(targets: RecommendationTargets, param: ApplicableParam): number {
  switch (param) {
    case "strategies":
    case "timeframe":
    case "risk_reset":
      return 1;
    case "stop_loss_pct":
      return targets.stop_loss_pct ?? 0;
    case "take_profit_pct":
      return targets.take_profit_pct ?? 0;
    case "min_consensus_strength":
      return targets.min_consensus_strength_pct ?? 0;
    case "entry_confirmation_bars":
      return targets.entry_confirmation_bars ?? 0;
    case "min_signal_strength": {
      const values = Object.values(targets.strategy_min_strength_pct ?? {});
      return values.length > 0 ? Math.max(...values) : 0;
    }
    default:
      return 0;
  }
}

export function buildRecommendationPickerModel(
  recommendations: BacktestRecommendation[],
  snapshot: BacktestFormSnapshot,
  availability?: RecommendationAvailabilityContext,
): {
  runId: number | null;
  guidance: RecommendationGuidance[];
  options: SelectableRecommendationOption[];
} {
  const { runId, items } = getLatestRunRecommendations(recommendations);
  const guidance: RecommendationGuidance[] = [];
  const optionByParam = new Map<ApplicableParam, SelectableRecommendationOption>();

  for (const recommendation of items) {
    if (isRecommendationReadOnly(recommendation)) {
      guidance.push({
        key: getRecommendationKey(recommendation),
        suggestion: recommendation.suggestion,
        rationale: recommendation.rationale,
        runId: recommendation.run_id,
      });
      continue;
    }

    for (const param of parseParamHints(recommendation.param_hint)) {
      const plan = buildSingleParamApplyPlan(recommendation, snapshot, param);
      if (!plan) {
        continue;
      }
      let disabled = false;
      let disabledReason: string | undefined;
      if (param === "timeframe" && plan.targets.timeframe && availability) {
        if (!isTimeframeViable(plan.targets.timeframe, availability)) {
          const available = availability.barCountsByTimeframe[plan.targets.timeframe] ?? 0;
          disabled = true;
          disabledReason = `Só ${available} velas em ${plan.targets.timeframe} (mín. ${availability.minBars})`;
        }
      }
      const existing = optionByParam.get(param);
      if (!existing || targetStrength(plan.targets, param) > targetStrength(existing.plan.targets, param)) {
        optionByParam.set(param, {
          id: plan.key,
          recommendationKey: getRecommendationKey(recommendation),
          param,
          label: PARAM_SHORT_LABELS[param],
          preview: plan.previews[0],
          plan,
          runId: recommendation.run_id,
          disabled,
          disabledReason,
        });
      }
    }
  }

  return {
    runId,
    guidance,
    options: Array.from(optionByParam.values()),
  };
}

export function mergeSelectedOptionPlans(
  options: SelectableRecommendationOption[],
): { targets: RecommendationTargets; previews: string[] } | null {
  if (options.length === 0) {
    return null;
  }
  const merged: RecommendationTargets = {};
  const previews: string[] = [];

  for (const option of options) {
    previews.push(option.preview);
    const targets = option.plan.targets;
    if (targets.strategies) {
      merged.strategies = targets.strategies;
    }
    if (targets.timeframe) {
      merged.timeframe = targets.timeframe;
    }
    if (targets.risk_reset) {
      merged.risk_reset = true;
    }
    if (typeof targets.stop_loss_pct === "number") {
      if (merged.risk_reset) {
        merged.stop_loss_pct = targets.stop_loss_pct;
      } else {
        merged.stop_loss_pct = Math.max(merged.stop_loss_pct ?? 0, targets.stop_loss_pct);
      }
    }
    if (typeof targets.take_profit_pct === "number") {
      if (merged.risk_reset) {
        merged.take_profit_pct = targets.take_profit_pct;
      } else {
        merged.take_profit_pct = Math.max(merged.take_profit_pct ?? 0, targets.take_profit_pct);
      }
    }
    if (typeof targets.min_consensus_strength_pct === "number") {
      merged.min_consensus_strength_pct = Math.max(
        merged.min_consensus_strength_pct ?? 0,
        targets.min_consensus_strength_pct,
      );
    }
    if (typeof targets.entry_confirmation_bars === "number") {
      merged.entry_confirmation_bars = Math.max(
        merged.entry_confirmation_bars ?? 0,
        targets.entry_confirmation_bars,
      );
    }
    if (targets.strategy_min_strength_pct) {
      merged.strategy_min_strength_pct = { ...(merged.strategy_min_strength_pct ?? {}) };
      for (const [strategy, value] of Object.entries(targets.strategy_min_strength_pct)) {
        const current = merged.strategy_min_strength_pct[strategy] ?? 0;
        merged.strategy_min_strength_pct[strategy] = Math.max(current, value);
      }
    }
  }

  return { targets: merged, previews };
}

export function buildAppliedRecordsFromOptions(
  options: SelectableRecommendationOption[],
): AppliedRecommendationRecord[] {
  const appliedAt = new Date().toISOString();
  return options.map((option) => ({
    key: option.plan.key,
    runId: option.runId,
    suggestion: option.label,
    previews: option.plan.previews,
    appliedAt,
  }));
}

export function isOptionApplied(
  option: SelectableRecommendationOption,
  appliedRecords: AppliedRecommendationRecord[],
): boolean {
  return appliedRecords.some((record) => record.key === option.plan.key);
}
