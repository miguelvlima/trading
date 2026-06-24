import { useEffect, useRef, useState } from "react";

import type { LiveTick } from "./useTickStream";
import { fmtCompact, fmtInt, fmtPrice } from "./format";

type LiveDataPanelProps = {
  tick: LiveTick | null;
};

// Per-tick stream card: last, bid/ask (+ spread), sizes, day volume and range.
// The last price flashes green/red on each change (functional colour cue).
export function LiveDataPanel({ tick }: LiveDataPanelProps) {
  const prevLast = useRef<number | null>(null);
  const [flash, setFlash] = useState<{ dir: "up" | "down"; key: number } | null>(null);

  useEffect(() => {
    const last = tick?.last ?? null;
    if (last !== null && prevLast.current !== null && last !== prevLast.current) {
      setFlash({ dir: last > prevLast.current ? "up" : "down", key: Date.now() });
    }
    if (last !== null) prevLast.current = last;
  }, [tick]);

  const bid = tick?.bid ?? null;
  const ask = tick?.ask ?? null;
  const spread = bid !== null && ask !== null ? ask - bid : null;
  // Visual spread fill, clamped against a 0.10 reference width.
  const spreadPct = spread !== null ? Math.min((spread / 0.1) * 100, 100) : 0;
  const lastDir = flash?.dir ?? "up";

  return (
    <div className="rt-card">
      <div className="rt-card-h">
        <span className="rt-card-t">Dados ao vivo</span>
        <span className="rt-badge rt-badge-live">● STREAM</span>
      </div>
      <div className="rt-rows">
        <div className="rt-r">
          <span className="rt-k">Last</span>
          <span
            key={flash?.key}
            className={`rt-v rt-v-big rt-${lastDir} ${flash ? `rt-flash-${lastDir}` : ""}`}
          >
            {fmtPrice(tick?.last ?? null)}
          </span>
        </div>
        <div className="rt-r">
          <span className="rt-k">Bid / Ask</span>
          <span className="rt-v rt-v-dual">
            <span>{fmtPrice(bid)}</span>
            <span className="rt-sub">/</span>
            <span>{fmtPrice(ask)}</span>
          </span>
        </div>
        <div className="rt-spread-bar">
          <i style={{ width: `${spreadPct}%` }} />
        </div>
        <div className="rt-r">
          <span className="rt-k">Spread</span>
          <span className="rt-v">{fmtPrice(spread)}</span>
        </div>
        <div className="rt-r">
          <span className="rt-k">Bid / Ask sz</span>
          <span className="rt-v rt-v-dual">
            <span>{fmtInt(tick?.bidSize ?? null)}</span>
            <span className="rt-sub">/</span>
            <span>{fmtInt(tick?.askSize ?? null)}</span>
          </span>
        </div>
        <div className="rt-r">
          <span className="rt-k">Last size</span>
          <span className="rt-v">{fmtInt(tick?.lastSize ?? null)}</span>
        </div>
        <div className="rt-r">
          <span className="rt-k">Volume dia</span>
          <span className="rt-v">{fmtCompact(tick?.volume ?? null)}</span>
        </div>
        <div className="rt-r">
          <span className="rt-k">H / L dia</span>
          <span className="rt-v rt-v-dual">
            <span>{fmtPrice(tick?.dayHigh ?? null)}</span>
            <span className="rt-sub">/</span>
            <span>{fmtPrice(tick?.dayLow ?? null)}</span>
          </span>
        </div>
      </div>
    </div>
  );
}
