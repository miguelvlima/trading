type BacktestWorkspaceDateFilterProps = {
  from: string;
  to: string;
  onFromChange: (value: string) => void;
  onToChange: (value: string) => void;
  onClear: () => void;
};

export function BacktestWorkspaceDateFilter({
  from,
  to,
  onFromChange,
  onToChange,
  onClear,
}: BacktestWorkspaceDateFilterProps) {
  const hasFilter = Boolean(from || to);
  const isInvalid = Boolean(from && to && from > to);

  return (
    <div className="backtest-workspace-date-filter">
      <span className="backtest-workspace-date-filter-label">Data do run</span>
      <label className="mkt-date-field">
        <span>De</span>
        <input type="date" value={from} onChange={(event) => onFromChange(event.target.value)} />
      </label>
      <label className="mkt-date-field">
        <span>Até</span>
        <input type="date" value={to} onChange={(event) => onToChange(event.target.value)} />
      </label>
      {hasFilter && (
        <button type="button" className="config-button" onClick={onClear}>
          Limpar
        </button>
      )}
      {isInvalid && <span className="backtest-workspace-date-filter-error">Data fim anterior ao início.</span>}
    </div>
  );
}
