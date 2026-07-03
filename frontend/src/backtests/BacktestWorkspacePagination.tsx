import { pageRangeLabel, totalPagesFor } from "./backtestWorkspaceList";

type BacktestWorkspacePaginationProps = {
  page: number;
  pageSize: number;
  totalItems: number;
  onPageChange: (page: number) => void;
};

export function BacktestWorkspacePagination({
  page,
  pageSize,
  totalItems,
  onPageChange,
}: BacktestWorkspacePaginationProps) {
  const totalPages = totalPagesFor(totalItems, pageSize);
  if (totalItems <= pageSize) {
    return null;
  }

  return (
    <div className="backtest-workspace-pagination">
      <button
        type="button"
        className="config-button"
        disabled={page <= 1}
        onClick={() => onPageChange(page - 1)}
      >
        Anterior
      </button>
      <span className="hint">{pageRangeLabel(page, pageSize, totalItems)}</span>
      <button
        type="button"
        className="config-button"
        disabled={page >= totalPages}
        onClick={() => onPageChange(page + 1)}
      >
        Seguinte
      </button>
    </div>
  );
}
