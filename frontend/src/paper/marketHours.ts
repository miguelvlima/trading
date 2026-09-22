// World-market wall clocks for the paper cockpit header.
//
// Everything derives from the viewer's clock (Date) projected into each
// market's IANA timezone via Intl — no timezone library, DST-correct. Like
// the backend session logic (quotes.py) this ignores exchange holidays: a
// holiday that falls on a weekday shows as "aberto".

export type MarketSession = { open: string; close: string }; // "HH:MM" in the market's tz

export type Market = {
  id: string;
  city: string;
  exchange: string;
  tz: string;
  // One session, or two when the exchange has a lunch break.
  sessions: MarketSession[];
};

export const MARKETS: Market[] = [
  {
    id: "nyse",
    city: "Nova Iorque",
    exchange: "NYSE · Nasdaq",
    tz: "America/New_York",
    sessions: [{ open: "09:30", close: "16:00" }],
  },
  {
    id: "lse",
    city: "Londres",
    exchange: "LSE",
    tz: "Europe/London",
    sessions: [{ open: "08:00", close: "16:30" }],
  },
  {
    id: "lis",
    city: "Lisboa",
    exchange: "Euronext",
    tz: "Europe/Lisbon",
    sessions: [{ open: "08:00", close: "16:30" }],
  },
  {
    id: "fra",
    city: "Frankfurt",
    exchange: "Xetra",
    tz: "Europe/Berlin",
    sessions: [{ open: "09:00", close: "17:30" }],
  },
  {
    id: "tse",
    city: "Tóquio",
    exchange: "TSE",
    tz: "Asia/Tokyo",
    sessions: [
      { open: "09:00", close: "11:30" },
      { open: "12:30", close: "15:30" },
    ],
  },
  {
    id: "hkex",
    city: "Hong Kong",
    exchange: "HKEX",
    tz: "Asia/Hong_Kong",
    sessions: [
      { open: "09:30", close: "12:00" },
      { open: "13:00", close: "16:00" },
    ],
  },
  {
    id: "asx",
    city: "Sydney",
    exchange: "ASX",
    tz: "Australia/Sydney",
    sessions: [{ open: "10:00", close: "16:00" }],
  },
];

type ZonedParts = {
  year: number;
  month: number; // 1-12
  day: number;
  weekday: number; // 0 = Sunday .. 6 = Saturday
  minutes: number; // minutes since local midnight
};

const WEEKDAYS: Record<string, number> = {
  Sun: 0,
  Mon: 1,
  Tue: 2,
  Wed: 3,
  Thu: 4,
  Fri: 5,
  Sat: 6,
};

// The wall-clock reading of `at` in timezone `tz`.
function zonedParts(at: Date, tz: string): ZonedParts {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    hourCycle: "h23",
    weekday: "short",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).formatToParts(at);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return {
    year: Number(get("year")),
    month: Number(get("month")),
    day: Number(get("day")),
    weekday: WEEKDAYS[get("weekday")] ?? 0,
    minutes: Number(get("hour")) * 60 + Number(get("minute")),
  };
}

function toMinutes(hhmm: string): number {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
}

export type MarketStatus = "open" | "lunch" | "closed";

export const STATUS_LABEL: Record<MarketStatus, string> = {
  open: "aberto",
  lunch: "almoço",
  closed: "fechado",
};

export function marketStatus(market: Market, at: Date): MarketStatus {
  const zoned = zonedParts(at, market.tz);
  if (zoned.weekday === 0 || zoned.weekday === 6) return "closed";
  const inSession = market.sessions.some(
    (s) => zoned.minutes >= toMinutes(s.open) && zoned.minutes < toMinutes(s.close),
  );
  if (inSession) return "open";
  if (
    market.sessions.length === 2 &&
    zoned.minutes >= toMinutes(market.sessions[0].close) &&
    zoned.minutes < toMinutes(market.sessions[1].open)
  ) {
    return "lunch";
  }
  return "closed";
}

// Offset of `tz` relative to UTC at instant `at` (ms). Derived by reading the
// zone's wall clock and comparing it with UTC; offsets are whole minutes.
function tzOffsetMs(tz: string, at: Date): number {
  const zoned = zonedParts(at, tz);
  const asUtc = Date.UTC(
    zoned.year,
    zoned.month - 1,
    zoned.day,
    Math.floor(zoned.minutes / 60),
    zoned.minutes % 60,
  );
  const ref = Date.UTC(
    at.getUTCFullYear(),
    at.getUTCMonth(),
    at.getUTCDate(),
    at.getUTCHours(),
    at.getUTCMinutes(),
  );
  return asUtc - ref;
}

// The instant at which the market's wall clock reads `hhmm` today (today by
// the market's calendar). Assumes the offset holds across the day — only off
// during the few hours around a DST switch.
function instantAtMarketTime(tz: string, hhmm: string, at: Date): Date {
  const zoned = zonedParts(at, tz);
  const [h, m] = hhmm.split(":").map(Number);
  const naiveUtc = Date.UTC(zoned.year, zoned.month - 1, zoned.day, h, m);
  return new Date(naiveUtc - tzOffsetMs(tz, at));
}

function fmtHm(at: Date, tz?: string): string {
  return at.toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: tz,
  });
}

// "09:30–16:00" (or "09:00–11:30 · 12:30–15:30") in the market's own clock.
export function sessionsLabelMarket(market: Market): string {
  return market.sessions.map((s) => `${s.open}–${s.close}`).join(" · ");
}

// The same sessions translated to the viewer's clock ("14:30–21:00").
// `viewTz` is only used by tests; the UI leaves it undefined (browser local).
export function sessionsLabelLocal(market: Market, at: Date, viewTz?: string): string {
  return market.sessions
    .map((s) => {
      const open = instantAtMarketTime(market.tz, s.open, at);
      const close = instantAtMarketTime(market.tz, s.close, at);
      return `${fmtHm(open, viewTz)}–${fmtHm(close, viewTz)}`;
    })
    .join(" · ");
}

// "15:04:05" — ticking clock, optionally in another timezone.
export function fmtClock(at: Date, tz?: string): string {
  return at.toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: tz,
  });
}

// "ter., 14 jul." — weekday + date, optionally in another timezone.
export function fmtDay(at: Date, tz?: string): string {
  return at.toLocaleDateString("pt-PT", {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: tz,
  });
}
