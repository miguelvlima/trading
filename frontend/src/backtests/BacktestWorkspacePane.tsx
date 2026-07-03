import type { ReactNode } from "react";

type BacktestWorkspacePaneProps = {
  title: string;
  description?: string;
  toolbar?: ReactNode;
  footer?: ReactNode;
  loading?: boolean;
  loadingMessage?: string;
  isEmpty?: boolean;
  emptyMessage?: string;
  children: ReactNode;
};

export function BacktestWorkspacePane({
  title,
  description,
  toolbar,
  footer,
  loading = false,
  loadingMessage = "A carregar...",
  isEmpty = false,
  emptyMessage = "Sem resultados.",
  children,
}: BacktestWorkspacePaneProps) {
  return (
    <div className="backtest-workspace-pane">
      <header className="backtest-workspace-pane-head">
        <h4 className="backtest-workspace-pane-title">{title}</h4>
        {description && <p className="hint backtest-workspace-pane-desc">{description}</p>}
      </header>
      {toolbar && <div className="backtest-workspace-pane-toolbar">{toolbar}</div>}
      <div className="backtest-workspace-pane-body">
        {loading ? (
          <p className="hint backtest-workspace-pane-empty">{loadingMessage}</p>
        ) : isEmpty ? (
          <p className="hint backtest-workspace-pane-empty">{emptyMessage}</p>
        ) : (
          children
        )}
      </div>
      {footer && <div className="backtest-workspace-pane-footer">{footer}</div>}
    </div>
  );
}
