// lightweight-charts renders the time axis and crosshair labels in UTC by
// default, which left the charts out of sync with every other clock in the
// app (fmtTime & co. format in the viewer's local timezone). Every chart must
// pass these formatters so the whole page reads on one clock.
import { TickMarkType, type UTCTimestamp } from "lightweight-charts";

function toDate(time: UTCTimestamp | number): Date {
  return new Date(Number(time) * 1000);
}

// Crosshair label: "14/07 15:04" in the viewer's local timezone.
export function crosshairTimeFormatter(time: UTCTimestamp): string {
  const date = toDate(time);
  const day = date.toLocaleDateString("en-GB", { day: "2-digit", month: "2-digit" });
  const clock = date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  return `${day} ${clock}`;
}

// Axis tick labels at the granularity the chart asks for, local timezone.
export function tickMarkFormatter(
  time: UTCTimestamp,
  tickMarkType: TickMarkType,
): string {
  const date = toDate(time);
  switch (tickMarkType) {
    case TickMarkType.Year:
      return date.toLocaleDateString("en-GB", { year: "numeric" });
    case TickMarkType.Month:
      return date.toLocaleDateString("en-GB", { month: "short" });
    case TickMarkType.DayOfMonth:
      return date.toLocaleDateString("en-GB", { day: "2-digit" });
    case TickMarkType.Time:
      return date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
    case TickMarkType.TimeWithSeconds:
    default:
      return date.toLocaleTimeString("en-GB", {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
  }
}
