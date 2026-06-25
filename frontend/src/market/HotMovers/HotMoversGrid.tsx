import { useState } from "react";

import { type HotDirection, type HotSort } from "./api";
import { HotMoverCard } from "./HotMoverCard";
import { useHotMovers } from "./useHotMovers";
import "./hot-movers.css";

type HotMoversGridProps = {
  apiBaseUrl: string;
  authToken: string;
  /** Current central-chart symbol — the matching card shows as active. */
  symbol: string;
  /** Promote a symbol to the central chart (inherits candle/window/indicators). */
  onSelect: (symbol: string) => void;
};

const SORTS: { code: HotSort; label: string }[] = [
  { code: "change_pct", label: "% Variação" },
  { code: "rvol", label: "RVol" },
  { code: "volume", label: "Volume" },
];

const DIRECTIONS: { code: HotDirection; label: string }[] = [
  { code: "both", label: "Ambos" },
  { code: "up", label: "Sobe" },
  { code: "down", label: "Desce" },
];

export function HotMoversGrid({ apiBaseUrl, authToken, symbol, onSelect }: HotMoversGridProps) {
  const [sort, setSort] = useState<HotSort>("change_pct");
  const [direction, setDirection] = useState<HotDirection>("both");
  const { items, loading, stale } = useHotMovers(apiBaseUrl, authToken, sort, direction);

  if (!authToken) return null;

  return (
    <section className="hm-section" aria-label="Dez mais quentes do mercado">
      <div className="hm-controls">
        <span className="hm-title">▸ 10 mais quentes</span>
        <div className="hm-seg-group">
          <span className="hm-seg-lbl">Ordenar</span>
          <div className="rt-seg">
            {SORTS.map((option) => (
              <button
                key={option.code}
                type="button"
                className={option.code === sort ? "rt-seg-active" : ""}
                onClick={() => setSort(option.code)}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
        <div className="hm-seg-group">
          <span className="hm-seg-lbl">Direção</span>
          <div className="rt-seg">
            {DIRECTIONS.map((option) => (
              <button
                key={option.code}
                type="button"
                className={option.code === direction ? "rt-seg-active" : ""}
                onClick={() => setDirection(option.code)}
              >
                {option.label}
              </button>
            ))}
          </div>
        </div>
        {stale && (
          <span className="hm-stale" title="Falha ao atualizar — a mostrar últimos dados">
            desatualizado
          </span>
        )}
      </div>

      {items.length === 0 ? (
        <p className="hint">{loading ? "A carregar mais quentes…" : "Sem dados de mercado."}</p>
      ) : (
        <div className="hm-grid">
          {items.slice(0, 10).map((mover, index) => (
            <HotMoverCard
              key={mover.symbol}
              mover={mover}
              rank={index + 1}
              isActive={mover.symbol === symbol}
              onSelect={() => onSelect(mover.symbol)}
            />
          ))}
        </div>
      )}
    </section>
  );
}
