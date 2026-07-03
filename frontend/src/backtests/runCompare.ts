export type CompareRunInput = {
  id: number;
  symbol: string;
  symbol_run_number?: number | null;
  timeframe: string;
  strategy_names: string[];
  start_at: string | null;
  end_at: string | null;
  initial_capital: number;
  fee_bps: number;
  slippage_bps: number;
  min_signal_strength: number;
  bars_processed: number;
  trades_count: number;
  net_pnl: number;
  net_pnl_pct: number;
  win_rate: number;
  profit_factor: number;
  max_drawdown_pct: number;
  created_at: string;
  result_summary: Record<string, unknown>;
};

export type CompareRowCategory = "data" | "config" | "result";

export type CompareRow = {
  key: string;
  label: string;
  category: CompareRowCategory;
  left: string;
  right: string;
  differs: boolean;
};

export type CompareSummary = {
  rows: CompareRow[];
  narrative: string;
  configIdentical: boolean;
  dataScopeDiffers: boolean;
  differingConfigKeys: string[];
};

export function formatBacktestRunLabel(run: {
  id: number;
  symbol: string;
  symbol_run_number?: number | null;
  timeframe: string;
}): string {
  const runNumber = run.symbol_run_number ?? run.id;
  return `${run.symbol} · run ${runNumber} · ${run.timeframe}`;
}

function getConfig(run: CompareRunInput): Record<string, unknown> {
  const stored =
    typeof run.result_summary.config === "object" && run.result_summary.config !== null
      ? (run.result_summary.config as Record<string, unknown>)
      : {};
  return {
    ...stored,
    strategies: stored.strategies ?? run.strategy_names,
    fee_bps: stored.fee_bps ?? run.fee_bps,
    slippage_bps: stored.slippage_bps ?? run.slippage_bps,
    initial_capital: stored.initial_capital ?? run.initial_capital,
    min_consensus_strength: stored.min_consensus_strength ?? run.min_signal_strength,
  };
}

function formatDateRange(start: string | null, end: string | null): string {
  if (!start && !end) {
    return "Janela global (sem datas fixas)";
  }
  const format = (value: string | null) => {
    if (!value) {
      return "…";
    }
    return new Date(value).toLocaleDateString("pt-PT");
  };
  return `${format(start)} – ${format(end)}`;
}

function formatPct(value: number, digits = 2): string {
  return `${(value * 100).toFixed(digits)}%`;
}

function formatOptionalPct(value: unknown): string {
  return typeof value === "number" ? `${value.toFixed(1)}%` : "—";
}

function formatExitMode(mode: unknown): string {
  if (mode === "opposite_signal") {
    return "Só sinal oposto";
  }
  if (mode === "tp_sl_or_opposite") {
    return "TP/SL + sinal oposto";
  }
  if (mode === "tp_sl_only") {
    return "Só TP/SL";
  }
  return typeof mode === "string" ? mode : "—";
}

function formatStrategies(names: string[]): string {
  return names.join(" · ");
}

function normalizeCompareValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "";
  }
  if (typeof value === "number") {
    return Number.isInteger(value) ? String(value) : value.toFixed(4);
  }
  if (Array.isArray(value)) {
    return value.join(",");
  }
  if (typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

function buildRow(
  key: string,
  label: string,
  category: CompareRowCategory,
  leftRaw: unknown,
  rightRaw: unknown,
  leftDisplay: string,
  rightDisplay: string,
): CompareRow {
  return {
    key,
    label,
    category,
    left: leftDisplay,
    right: rightDisplay,
    differs: normalizeCompareValue(leftRaw) !== normalizeCompareValue(rightRaw),
  };
}

export function buildBacktestRunComparison(
  left: CompareRunInput,
  right: CompareRunInput,
): CompareSummary {
  const leftConfig = getConfig(left);
  const rightConfig = getConfig(right);

  const rows: CompareRow[] = [
    buildRow(
      "bars_processed",
      "Barras processadas",
      "data",
      left.bars_processed,
      right.bars_processed,
      String(left.bars_processed),
      String(right.bars_processed),
    ),
    buildRow(
      "date_range",
      "Período",
      "data",
      `${left.start_at ?? ""}|${left.end_at ?? ""}`,
      `${right.start_at ?? ""}|${right.end_at ?? ""}`,
      formatDateRange(left.start_at, left.end_at),
      formatDateRange(right.start_at, right.end_at),
    ),
    buildRow(
      "limit",
      "Limite de barras pedido",
      "data",
      leftConfig.limit,
      rightConfig.limit,
      typeof leftConfig.limit === "number" ? String(leftConfig.limit) : "—",
      typeof rightConfig.limit === "number" ? String(rightConfig.limit) : "—",
    ),
    buildRow(
      "symbol_timeframe",
      "Símbolo / vela",
      "data",
      `${left.symbol}/${left.timeframe}`,
      `${right.symbol}/${right.timeframe}`,
      `${left.symbol} / ${left.timeframe}`,
      `${right.symbol} / ${right.timeframe}`,
    ),
    buildRow(
      "strategies",
      "Estratégias",
      "config",
      leftConfig.strategies,
      rightConfig.strategies,
      formatStrategies(left.strategy_names),
      formatStrategies(right.strategy_names),
    ),
    buildRow(
      "exit_mode",
      "Modo de saída",
      "config",
      leftConfig.exit_mode,
      rightConfig.exit_mode,
      formatExitMode(leftConfig.exit_mode),
      formatExitMode(rightConfig.exit_mode),
    ),
    buildRow(
      "stop_loss_pct",
      "Stop-loss",
      "config",
      leftConfig.stop_loss_pct,
      rightConfig.stop_loss_pct,
      formatOptionalPct(leftConfig.stop_loss_pct),
      formatOptionalPct(rightConfig.stop_loss_pct),
    ),
    buildRow(
      "take_profit_pct",
      "Take-profit",
      "config",
      leftConfig.take_profit_pct,
      rightConfig.take_profit_pct,
      formatOptionalPct(leftConfig.take_profit_pct),
      formatOptionalPct(rightConfig.take_profit_pct),
    ),
    buildRow(
      "entry_confirmation_bars",
      "Confirmação entrada",
      "config",
      leftConfig.entry_confirmation_bars,
      rightConfig.entry_confirmation_bars,
      typeof leftConfig.entry_confirmation_bars === "number"
        ? `${leftConfig.entry_confirmation_bars} velas`
        : "—",
      typeof rightConfig.entry_confirmation_bars === "number"
        ? `${rightConfig.entry_confirmation_bars} velas`
        : "—",
    ),
    buildRow(
      "min_strength",
      "Limiar de força",
      "config",
      leftConfig.min_consensus_strength,
      rightConfig.min_consensus_strength,
      formatPct(Number(leftConfig.min_consensus_strength ?? left.min_signal_strength), 0),
      formatPct(Number(rightConfig.min_consensus_strength ?? right.min_signal_strength), 0),
    ),
    buildRow(
      "fees",
      "Fees / slippage",
      "config",
      `${leftConfig.fee_bps}/${leftConfig.slippage_bps}`,
      `${rightConfig.fee_bps}/${rightConfig.slippage_bps}`,
      `${Number(leftConfig.fee_bps).toFixed(1)} / ${Number(leftConfig.slippage_bps).toFixed(1)} bps`,
      `${Number(rightConfig.fee_bps).toFixed(1)} / ${Number(rightConfig.slippage_bps).toFixed(1)} bps`,
    ),
    buildRow(
      "net_pnl_pct",
      "PnL líquido",
      "result",
      left.net_pnl_pct,
      right.net_pnl_pct,
      formatPct(left.net_pnl_pct),
      formatPct(right.net_pnl_pct),
    ),
    buildRow(
      "trades_count",
      "Trades",
      "result",
      left.trades_count,
      right.trades_count,
      String(left.trades_count),
      String(right.trades_count),
    ),
    buildRow(
      "win_rate",
      "Win rate",
      "result",
      left.win_rate,
      right.win_rate,
      formatPct(left.win_rate, 0),
      formatPct(right.win_rate, 0),
    ),
    buildRow(
      "profit_factor",
      "Profit factor",
      "result",
      left.profit_factor,
      right.profit_factor,
      left.profit_factor.toFixed(2),
      right.profit_factor.toFixed(2),
    ),
    buildRow(
      "max_drawdown_pct",
      "Drawdown máx.",
      "result",
      left.max_drawdown_pct,
      right.max_drawdown_pct,
      formatPct(left.max_drawdown_pct, 1),
      formatPct(right.max_drawdown_pct, 1),
    ),
  ];

  const configRows = rows.filter((row) => row.category === "config");
  const dataRows = rows.filter((row) => row.category === "data");
  const configIdentical = configRows.every((row) => !row.differs);
  const dataScopeDiffers = dataRows.some((row) => row.differs);
  const differingConfigKeys = configRows.filter((row) => row.differs).map((row) => row.label);

  let narrative: string;
  if (configIdentical && dataScopeDiffers) {
    const barDelta = Math.abs(left.bars_processed - right.bars_processed);
    narrative =
      `Configuração de estratégia igual, mas o universo de dados foi diferente ` +
      `(ex.: ${left.bars_processed} vs ${right.bars_processed} barras, Δ ${barDelta}). ` +
      `Isto explica resultados distintos — não é falha do motor de simulação.`;
  } else if (!configIdentical && dataScopeDiffers) {
    narrative =
      `Diferenças na configuração (${differingConfigKeys.join(", ")}) e no universo de dados ` +
      `(${left.bars_processed} vs ${right.bars_processed} barras). Ambos afectam o resultado.`;
  } else if (!configIdentical) {
    narrative =
      `Mesmo universo de dados, mas configuração diferente em: ${differingConfigKeys.join(", ")}.`;
  } else {
    narrative =
      `Configuração e universo de dados alinhados. Pequenas diferenças de resultado podem vir de ` +
      `actualização de dados de mercado entre runs.`;
  }

  return {
    rows,
    narrative,
    configIdentical,
    dataScopeDiffers,
    differingConfigKeys,
  };
}
