export type RunPerformanceSnapshot = {
  trades_count: number;
  net_pnl_pct: number;
  profit_factor: number;
};

export function isProtectedWinningRun(run: RunPerformanceSnapshot): boolean {
  return run.trades_count > 0 && run.net_pnl_pct > 0 && run.profit_factor >= 1;
}
