import { type RefObject } from "react";

type BacktestReuseBannerProps = {
  bannerRef: RefObject<HTMLElement>;
  runLabel: string;
  summaryLines: string[];
  canRun: boolean;
  running: boolean;
  onRun: () => void;
  onDismiss: () => void;
};

export function BacktestReuseBanner({
  bannerRef,
  runLabel,
  summaryLines,
  canRun,
  running,
  onRun,
  onDismiss,
}: BacktestReuseBannerProps) {
  return (
    <section ref={bannerRef} className="backtest-reuse-banner" aria-live="polite">
      <div className="backtest-reuse-banner-body">
        <p className="backtest-reuse-banner-kicker">Configuração aplicada</p>
        <p className="backtest-reuse-banner-title">
          Reutilizado de <strong>{runLabel}</strong>
        </p>
        <ul className="backtest-reuse-banner-summary">
          {summaryLines.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
        <p className="hint backtest-reuse-banner-hint">
          Os parâmetros estão no formulário abaixo. Podes ajustar e correr quando quiseres.
        </p>
      </div>
      <div className="backtest-reuse-banner-actions">
        <button type="button" className="tab-button" onClick={onRun} disabled={!canRun}>
          {running ? "A correr..." : "Correr backtest"}
        </button>
        <button type="button" className="config-button" onClick={onDismiss}>
          Fechar
        </button>
      </div>
    </section>
  );
}
