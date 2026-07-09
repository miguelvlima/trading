// Tipos e lógica pura do diagnóstico de sistema (Configuração → Sistema).
// A parte pura vive aqui para ser testável em vitest sem DOM.

export type SystemCheckStatus = "ok" | "warn" | "fail";

export type SystemCheck = {
  key: string;
  label: string;
  status: SystemCheckStatus;
  detail: string;
  hint: string | null;
  data: Record<string, unknown>;
};

export type SystemStatusReport = {
  generated_at: string;
  overall: SystemCheckStatus;
  checks: SystemCheck[];
};

export const STATUS_SEVERITY: Record<SystemCheckStatus, number> = {
  ok: 0,
  warn: 1,
  fail: 2,
};

export const STATUS_LABELS: Record<SystemCheckStatus, string> = {
  ok: "Operacional",
  warn: "Atenção",
  fail: "Falha",
};

export function worstStatus(checks: readonly SystemCheck[]): SystemCheckStatus {
  let worst: SystemCheckStatus = "ok";
  for (const check of checks) {
    if (STATUS_SEVERITY[check.status] > STATUS_SEVERITY[worst]) {
      worst = check.status;
    }
  }
  return worst;
}

/** Ordena pior-primeiro mantendo a ordem original dentro do mesmo nível. */
export function sortChecksBySeverity(checks: readonly SystemCheck[]): SystemCheck[] {
  return [...checks].sort(
    (left, right) => STATUS_SEVERITY[right.status] - STATUS_SEVERITY[left.status],
  );
}

export function formatCheckedAt(ms: number): string {
  const d = new Date(ms);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function normalizeStatus(value: unknown): SystemCheckStatus {
  return value === "ok" || value === "warn" || value === "fail" ? value : "warn";
}

/** Torna o payload defensivo: um backend antigo/estranho nunca rebenta o painel. */
export function normalizeReport(raw: unknown): SystemStatusReport {
  const obj = (raw ?? {}) as Partial<SystemStatusReport> & { checks?: unknown };
  const checks = Array.isArray(obj.checks)
    ? obj.checks.map((item) => {
        const check = (item ?? {}) as Partial<SystemCheck>;
        return {
          key: String(check.key ?? "?"),
          label: String(check.label ?? check.key ?? "?"),
          status: normalizeStatus(check.status),
          detail: String(check.detail ?? ""),
          hint: check.hint == null ? null : String(check.hint),
          data: (check.data ?? {}) as Record<string, unknown>,
        };
      })
    : [];
  return {
    generated_at: String(obj.generated_at ?? ""),
    overall: obj.overall ? normalizeStatus(obj.overall) : worstStatus(checks),
    checks,
  };
}

export async function fetchSystemStatus(
  baseUrl: string,
  token: string,
): Promise<SystemStatusReport> {
  const response = await fetch(`${baseUrl}/system/status`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) {
    throw new Error(`Diagnóstico indisponível (HTTP ${response.status}).`);
  }
  return normalizeReport(await response.json());
}
