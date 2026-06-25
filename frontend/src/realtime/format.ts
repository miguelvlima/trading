// Display formatters shared across the Realtime panels. All numeric inputs may
// be null (IBKR field not yet reported) and render as an em dash.

export function fmtPrice(value: number | null, decimals = 2): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return value.toLocaleString("en-US", {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

export function fmtInt(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return Math.round(value).toLocaleString("en-US");
}

export function fmtCompact(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  if (Math.abs(value) >= 1e6) return (value / 1e6).toFixed(2) + "M";
  if (Math.abs(value) >= 1e3) return (value / 1e3).toFixed(1) + "k";
  return String(Math.round(value));
}

export function fmtPct(value: number | null, decimals = 2): string {
  if (value === null || !Number.isFinite(value)) return "—";
  return (value >= 0 ? "+" : "") + value.toFixed(decimals) + "%";
}

// Always render server/UTC time — never the local clock (it has been observed
// to jump in this environment).
export function fmtTimeUtc(ms: number | null): string {
  if (ms === null) return "—";
  return new Date(ms).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: "UTC",
  });
}

// Wall-clock HH:MM:SS in a given IANA timezone (e.g. "Europe/Lisbon",
// "America/New_York"). Used for the market session clocks in the top bar.
export function fmtClock(ms: number, timeZone: string): string {
  return new Date(ms).toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone,
  });
}

export function fmtSecondsAgo(fromMs: number | null, nowMs: number): string {
  if (fromMs === null) return "—";
  const seconds = Math.max(0, Math.round((nowMs - fromMs) / 1000));
  return `há ${seconds}s`;
}
