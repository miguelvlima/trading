type SparklineProps = {
  points: number[];
  up: boolean;
  width?: number;
  height?: number;
};

// Lightweight SVG sparkline — a single <path>, no chart library (10 cards would
// be 10 wasted lightweight-charts instances). Colour follows the move's sign.
export function Sparkline({ points, up, width = 124, height = 34 }: SparklineProps) {
  if (points.length < 2) {
    return <svg className="hm-spark" width={width} height={height} aria-hidden="true" />;
  }
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const stepX = width / (points.length - 1);
  const d = points
    .map((value, index) => {
      const x = (index * stepX).toFixed(2);
      const y = (height - ((value - min) / span) * height).toFixed(2);
      return `${index === 0 ? "M" : "L"}${x} ${y}`;
    })
    .join(" ");

  return (
    <svg
      className="hm-spark"
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <path d={d} fill="none" stroke={up ? "var(--rt-up)" : "var(--rt-down)"} strokeWidth={1.5} />
    </svg>
  );
}
