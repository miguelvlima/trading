import { useState } from "react";

import type { StreamStatus } from "./useTickStream";
import { fmtTimeUtc } from "./format";
import { useSymbolSearch } from "./useSymbolSearch";

type SymbolBarProps = {
  apiBaseUrl: string;
  authToken: string;
  symbol: string;
  name: string | null;
  followed: string[];
  onSelect: (symbol: string) => void;
  status: StreamStatus;
  lastBarMs: number | null;
  staleAfterMs?: number;
  nowMs: number;
};

function connState(
  status: StreamStatus,
  lastBarMs: number | null,
  staleAfterMs: number,
  nowMs: number,
): { tone: "live" | "stale" | "down"; label: string } {
  if (status !== "open") return { tone: "down", label: "desligado" };
  if (lastBarMs !== null && nowMs - lastBarMs > staleAfterMs) {
    return { tone: "stale", label: "atrasado" };
  }
  return { tone: "live", label: "ligado" };
}

// Top bar: single symbol selector + IBKR search, followed chips, and a
// staleness-based IB Gateway status (age of last bar, not just socket state —
// the Gateway has silent gaps).
export function SymbolBar({
  apiBaseUrl,
  authToken,
  symbol,
  name,
  followed,
  onSelect,
  status,
  lastBarMs,
  staleAfterMs = 60000,
  nowMs,
}: SymbolBarProps) {
  const [query, setQuery] = useState<string>("");
  const [open, setOpen] = useState<boolean>(false);
  const { results, loading } = useSymbolSearch(apiBaseUrl, authToken, query);

  const select = (next: string) => {
    const cleaned = next.trim().toUpperCase();
    if (!cleaned) return;
    onSelect(cleaned);
    setQuery("");
    setOpen(false);
  };

  const conn = connState(status, lastBarMs, staleAfterMs, nowMs);

  return (
    <div className="rt-symbar">
      <div className="rt-symsel">
        <span className="rt-tk">{symbol}</span>
        {name && <span className="rt-nm">{name}</span>}
      </div>

      <div className="rt-search">
        <input
          className="rt-search-input"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => globalThis.setTimeout(() => setOpen(false), 150)}
          onKeyDown={(e) => {
            if (e.key === "Enter") select(query);
          }}
          placeholder="Pesquisar IBKR (AAPL, TSLA, SPY)…"
          autoComplete="off"
        />
        {open && (loading || results.length > 0) && (
          <ul className="rt-search-results">
            {loading && <li className="rt-search-loading">A pesquisar…</li>}
            {results.map((m, i) => (
              <li key={`${m.symbol}-${m.exchange}-${i}`}>
                <button
                  type="button"
                  className="rt-search-item"
                  onMouseDown={(e) => {
                    e.preventDefault();
                    select(m.symbol);
                  }}
                >
                  <span className="rt-search-sym">{m.symbol}</span>
                  <span className="rt-search-desc">
                    {[m.sec_type, m.exchange, m.currency].filter(Boolean).join(" · ")}
                    {m.name ? ` — ${m.name}` : ""}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="rt-followed">
        <span className="rt-followed-lbl">Seguidos</span>
        {followed.map((tk) => (
          <button
            key={tk}
            type="button"
            className={tk === symbol ? "rt-chip rt-chip-active" : "rt-chip"}
            onClick={() => select(tk)}
          >
            {tk}
          </button>
        ))}
      </div>

      <div className={`rt-conn rt-conn-${conn.tone}`}>
        <span className="rt-dot" />
        <span>IB Gateway</span>
        <span className="rt-conn-meta">
          · {conn.label} · última barra {fmtTimeUtc(lastBarMs)}
        </span>
      </div>
    </div>
  );
}
