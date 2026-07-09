import { useCallback, useEffect, useState } from "react";

import {
  type SystemStatusReport,
  STATUS_LABELS,
  fetchSystemStatus,
  formatCheckedAt,
  sortChecksBySeverity,
} from "./systemStatus";

const REFRESH_MS = 30_000;

type SystemStatusPanelProps = {
  apiBaseUrl: string;
  authToken: string;
};

/** Diagnóstico dos pontos fundamentais (BD, Gateway, feed, frescura, engine). */
export function SystemStatusPanel({ apiBaseUrl, authToken }: SystemStatusPanelProps) {
  const [report, setReport] = useState<SystemStatusReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [checkedAtMs, setCheckedAtMs] = useState<number | null>(null);

  const load = useCallback(async () => {
    if (!authToken) {
      return;
    }
    setLoading(true);
    try {
      const next = await fetchSystemStatus(apiBaseUrl, authToken);
      setReport(next);
      setError(null);
      setCheckedAtMs(Date.now());
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Erro ao obter o diagnóstico.");
    } finally {
      setLoading(false);
    }
  }, [apiBaseUrl, authToken]);

  // Carrega ao abrir e refresca enquanto o painel está montado (tab aberta).
  useEffect(() => {
    void load();
    const timer = globalThis.setInterval(() => void load(), REFRESH_MS);
    return () => globalThis.clearInterval(timer);
  }, [load]);

  if (!authToken) {
    return <p className="hint">Inicie sessão para ver o diagnóstico do sistema.</p>;
  }

  return (
    <div className="sys-status">
      <div className="sys-status-toolbar">
        {report && (
          <span className={`sys-status-badge sys-status-${report.overall}`}>
            {STATUS_LABELS[report.overall]}
          </span>
        )}
        <span className="hint">
          {checkedAtMs !== null
            ? `Última verificação às ${formatCheckedAt(checkedAtMs)}`
            : "Sem verificação ainda."}
        </span>
        <button type="button" onClick={() => void load()} disabled={loading}>
          {loading ? "A verificar…" : "Verificar agora"}
        </button>
      </div>

      {error && <p className="error">{error}</p>}
      {!report && !error && <p className="hint">A correr o diagnóstico…</p>}

      {report && (
        <ul className="sys-status-list">
          {sortChecksBySeverity(report.checks).map((check) => (
            <li key={check.key} className="sys-status-row">
              <span
                className={`sys-status-dot sys-status-${check.status}`}
                aria-label={STATUS_LABELS[check.status]}
                title={STATUS_LABELS[check.status]}
              />
              <div className="sys-status-body">
                <span className="sys-status-label">{check.label}</span>
                <span className="sys-status-detail">{check.detail}</span>
                {check.hint && <span className="sys-status-hint">→ {check.hint}</span>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
