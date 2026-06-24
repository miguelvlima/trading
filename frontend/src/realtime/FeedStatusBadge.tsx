import type { FeedHealth, FeedStatus } from "./api";

type FeedStatusBadgeProps = {
  health: FeedHealth | null;
  loading: boolean;
};

const STATUS_LABEL: Record<FeedStatus, string> = {
  running: "A correr",
  stale: "Atrasado",
  error: "Erro",
  empty: "Sem dados",
};

function formatAge(lagSeconds: number | null): string {
  if (lagSeconds === null) {
    return "—";
  }
  const seconds = Math.max(0, Math.floor(lagSeconds));
  if (seconds < 60) {
    return `${seconds}s`;
  }
  if (seconds < 3600) {
    return `${Math.floor(seconds / 60)}m`;
  }
  if (seconds < 86400) {
    return `${Math.floor(seconds / 3600)}h`;
  }
  return `${Math.floor(seconds / 86400)}d`;
}

function formatLastUpdate(iso: string | null): string {
  if (!iso) {
    return "nunca";
  }
  // Show in UTC so it matches the chart and the backend's time-source.
  return `${new Date(iso).toISOString().replace("T", " ").slice(0, 19)} UTC`;
}

export function FeedStatusBadge({ health, loading }: FeedStatusBadgeProps) {
  if (!health) {
    return (
      <div className="realtime-badge realtime-badge-unknown">
        <span className="realtime-badge-dot" />
        {loading ? "A verificar feed…" : "Estado do feed indisponível"}
      </div>
    );
  }

  return (
    <div className={`realtime-badge realtime-badge-${health.status}`}>
      <span className="realtime-badge-dot" />
      <span className="realtime-badge-status">
        {STATUS_LABEL[health.status]} · {health.provider}
      </span>
      <span className="realtime-badge-meta">
        última barra: {formatLastUpdate(health.last_update)} (há {formatAge(health.lag_seconds)})
      </span>
    </div>
  );
}
