import { fmtCompact, fmtPrice } from "../../realtime/format";
import { type HotMover } from "./api";
import { Sparkline } from "./Sparkline";

type HotMoverCardProps = {
  mover: HotMover;
  rank: number;
  isActive: boolean;
  onSelect: () => void;
};

export function HotMoverCard({ mover, rank, isActive, onSelect }: HotMoverCardProps) {
  const change = Number(mover.change_pct);
  const up = change >= 0;
  const last = Number(mover.last);
  const relVolume = mover.rel_volume !== null ? Number(mover.rel_volume) : null;

  const ariaLabel = `${mover.symbol} ${up ? "sobe" : "desce"} ${Math.abs(change).toFixed(2)} por cento, preço ${fmtPrice(last)}`;

  const onKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      onSelect();
    }
  };

  return (
    <div
      role="button"
      tabIndex={0}
      className={isActive ? "hm-card hm-card-active" : "hm-card"}
      onClick={onSelect}
      onKeyDown={onKeyDown}
      aria-pressed={isActive}
      aria-label={ariaLabel}
    >
      <span className="hm-rank">{String(rank).padStart(2, "0")}</span>
      <div className="hm-head">
        <span className="hm-sym">{mover.symbol}</span>
        <span className={up ? "hm-chg hm-up" : "hm-chg hm-down"}>
          {(up ? "+" : "") + change.toFixed(2)}%
        </span>
      </div>
      <div className="hm-price">{fmtPrice(last)}</div>
      <Sparkline points={mover.spark.points} up={up} />
      <div className="hm-foot">
        <span>Vol {fmtCompact(mover.volume)}</span>
        <span>RVol {relVolume !== null ? relVolume.toFixed(2) : "—"}</span>
      </div>
    </div>
  );
}
