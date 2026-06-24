import { fmtInt, fmtPrice, fmtTimeUtc } from "./format";

export type LastBarSnapshot = {
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
  // WAP / trade count only arrive on keepUpToDate bars; null when unavailable.
  wap: number | null;
  trades: number | null;
  closeTimeMs: number | null;
  forming: boolean;
};

type LastBarPanelProps = {
  bar: LastBarSnapshot | null;
  candle: string;
};

// Snapshot of the most recent candle. The badge makes the persistence state
// explicit: a forming bar (LIVE) is NOT written to market_bars; only a closed
// bar (SNAPSHOT) is persisted.
export function LastBarPanel({ bar, candle }: LastBarPanelProps) {
  const forming = bar?.forming ?? false;
  return (
    <div className="rt-card">
      <div className="rt-card-h">
        <span className="rt-card-t">Última vela · {candle}</span>
        <span className={`rt-badge ${forming ? "rt-badge-live" : "rt-badge-snap"}`}>
          {forming ? "● EM FORMAÇÃO" : "SNAPSHOT"}
        </span>
      </div>
      <div className="rt-rows">
        <Row k="Open" v={fmtPrice(bar?.open ?? null)} />
        <Row k="High" v={fmtPrice(bar?.high ?? null)} />
        <Row k="Low" v={fmtPrice(bar?.low ?? null)} />
        <Row k="Close" v={fmtPrice(bar?.close ?? null)} />
        <Row k="Volume" v={fmtInt(bar?.volume ?? null)} />
        <Row k="WAP" v={fmtPrice(bar?.wap ?? null)} />
        <Row k="Trades" v={fmtInt(bar?.trades ?? null)} />
        <Row k="Fecho" v={fmtTimeUtc(bar?.closeTimeMs ?? null)} muted />
      </div>
      {forming && (
        <p className="rt-card-note">Em formação — ainda não persistida em market_bars.</p>
      )}
    </div>
  );
}

function Row({ k, v, muted }: { k: string; v: string; muted?: boolean }) {
  return (
    <div className="rt-r">
      <span className="rt-k">{k}</span>
      <span className={muted ? "rt-v rt-v-muted" : "rt-v"}>{v}</span>
    </div>
  );
}
