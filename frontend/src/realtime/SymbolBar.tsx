import { Fragment, useMemo, useState } from "react";

import { type OnlineGroup, followInstrument, unfollowInstrument } from "./api";
import type { StreamStatus } from "./useTickStream";
import { fmtClock, fmtTimeUtc } from "./format";
import { useOnlineSymbols } from "./useOnlineSymbols";
import { useSymbolSearch } from "./useSymbolSearch";

type SymbolBarProps = {
  apiBaseUrl: string;
  authToken: string;
  symbol: string;
  name: string | null;
  followed: string[];
  /** Whether the current symbol is followed (a persisted, followed instrument). */
  isFollowing: boolean;
  /** Called after a successful follow/unfollow so the parent can refresh. */
  onFollowChange?: () => void;
  onSelect: (symbol: string) => void;
  status: StreamStatus;
  lastBarMs: number | null;
  staleAfterMs?: number;
  nowMs: number;
  showConnection?: boolean;
};

// Display order + labels for the "available" sections in the dropdown.
const GROUP_ORDER: OnlineGroup[] = ["major", "active", "index"];
const GROUP_LABELS: Record<OnlineGroup, string> = {
  major: "Principais",
  active: "Mais ativos · live",
  index: "Índices",
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
  isFollowing,
  onFollowChange,
  onSelect,
  status,
  lastBarMs,
  staleAfterMs = 60000,
  nowMs,
  showConnection = true,
}: SymbolBarProps) {
  const [query, setQuery] = useState<string>("");
  const [open, setOpen] = useState<boolean>(false);
  const [followBusy, setFollowBusy] = useState<boolean>(false);
  const { results, loading } = useSymbolSearch(apiBaseUrl, authToken, query);
  const { online, loading: onlineLoading, refresh } = useOnlineSymbols(apiBaseUrl, authToken);

  const toggleFollow = async () => {
    if (followBusy || !symbol) return;
    setFollowBusy(true);
    try {
      if (isFollowing) {
        await unfollowInstrument(apiBaseUrl, authToken, symbol);
      } else {
        await followInstrument(apiBaseUrl, authToken, symbol, name);
      }
      onFollowChange?.();
    } catch {
      // Best-effort: a failed toggle leaves the prior state; the parent refresh
      // (or the next render) reconciles. No blocking error UI for a watchlist op.
    } finally {
      setFollowBusy(false);
    }
  };

  // The available universe shown on focus. While typing, it narrows to matches
  // so the box stays useful next to the IBKR search.
  const filteredOnline = useMemo(() => {
    const q = query.trim().toUpperCase();
    if (!q) return online;
    return online.filter(
      (o) => o.symbol.includes(q) || (o.name ?? "").toUpperCase().includes(q),
    );
  }, [online, query]);

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

      <button
        type="button"
        className={isFollowing ? "rt-follow rt-following" : "rt-follow"}
        onClick={toggleFollow}
        disabled={followBusy}
        title={isFollowing ? "Deixar de seguir este instrumento" : "Seguir este instrumento"}
      >
        {isFollowing ? "✓ A seguir" : "+ Seguir"}
      </button>

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
          placeholder="Escolher live ou pesquisar IBKR (AAPL, TSLA, SPY)…"
          autoComplete="off"
        />
        {open && (
          <ul className="rt-search-results">
            <li className="rt-search-group rt-search-group-row">
              <span>Disponíveis · IB Gateway</span>
              <button
                type="button"
                className="rt-search-refresh"
                onMouseDown={(e) => {
                  e.preventDefault();
                  refresh();
                }}
                title="Recarregar a lista a partir do IB Gateway"
              >
                {onlineLoading ? "A atualizar…" : "↻ Atualizar"}
              </button>
            </li>
            {filteredOnline.length === 0 && !onlineLoading && (
              <li className="rt-search-loading">
                Sem símbolos. Clique em Atualizar para recarregar do IB Gateway.
              </li>
            )}
            {GROUP_ORDER.map((group) => {
              const items = filteredOnline.filter((o) => o.group === group);
              if (items.length === 0) return null;
              return (
                <Fragment key={group}>
                  <li className="rt-search-subgroup">{GROUP_LABELS[group]}</li>
                  {items.map((o) => (
                    <li key={`online-${o.group}-${o.symbol}`}>
                      <button
                        type="button"
                        className="rt-search-item"
                        onMouseDown={(e) => {
                          e.preventDefault();
                          select(o.symbol);
                        }}
                      >
                        <span className="rt-search-sym">{o.symbol}</span>
                        {(o.name || o.exchange) && (
                          <span className="rt-search-desc">{o.name ?? o.exchange}</span>
                        )}
                      </button>
                    </li>
                  ))}
                </Fragment>
              );
            })}

            {(loading || results.length > 0) && (
              <li className="rt-search-group">Pesquisa IBKR</li>
            )}
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

      <div className="rt-clocks">
        <div className="rt-clock">
          <span className="rt-clock-lbl">Lisboa</span>
          <span className="rt-clock-val">{fmtClock(nowMs, "Europe/Lisbon")}</span>
        </div>
        <div className="rt-clock">
          <span className="rt-clock-lbl">Nova Iorque</span>
          <span className="rt-clock-val">{fmtClock(nowMs, "America/New_York")}</span>
        </div>
      </div>

      {showConnection && (
        <div className={`rt-conn rt-conn-${conn.tone}`}>
          <span className="rt-dot" />
          <span>IB Gateway</span>
          <span className="rt-conn-meta">
            · {conn.label} · última barra {fmtTimeUtc(lastBarMs)}
          </span>
        </div>
      )}
    </div>
  );
}
