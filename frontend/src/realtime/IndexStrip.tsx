import type { IndexSpec } from "./api";
import type { LiveIndex } from "./useTickStream";
import { fmtPct, fmtPrice } from "./format";

type IndexStripProps = {
  specs: IndexSpec[];
  live: Record<string, LiveIndex>;
};

// Bottom strip of market indices. Specs render immediately (static skeleton);
// values fill in as the WebSocket pushes each index's reqMktData line.
export function IndexStrip({ specs, live }: IndexStripProps) {
  return (
    <div className="rt-indices">
      <span className="rt-indices-lbl">Índices</span>
      {specs.map((spec) => {
        const value = live[spec.symbol.toUpperCase()];
        const change = value?.changePct ?? null;
        const tone = change === null ? "flat" : change >= 0 ? "up" : "down";
        const decimals = value && value.last !== null && value.last < 10 ? 4 : 2;
        return (
          <div key={spec.symbol} className="rt-idx">
            <span className="rt-idx-nm">{spec.name}</span>
            <span className="rt-idx-vl">
              {fmtPrice(value?.last ?? null, decimals)}
              <span className={`rt-idx-ch rt-${tone}`}>
                {change === null ? "" : change >= 0 ? "▲" : "▼"}
                {fmtPct(change)}
              </span>
            </span>
          </div>
        );
      })}
    </div>
  );
}
