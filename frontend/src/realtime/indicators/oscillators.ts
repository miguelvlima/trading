// Oscillators: each rendered in its own pane below the price chart.

import type { IndicatorBar, LinePoint, MacdResult, StochasticResult } from "./types";

function emaArr(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  if (values.length < period) return out;
  const k = 2 / (period + 1);
  let prev = 0;
  for (let i = 0; i < period; i++) prev += values[i];
  prev /= period;
  out[period - 1] = prev;
  for (let i = period; i < values.length; i++) {
    prev = values[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

// Wilder's RSI.
export function rsi(bars: IndicatorBar[], period = 14): LinePoint[] {
  if (bars.length < period + 1) return [];
  let avgGain = 0;
  let avgLoss = 0;
  for (let i = 1; i <= period; i++) {
    const change = bars[i].close - bars[i - 1].close;
    if (change >= 0) avgGain += change;
    else avgLoss -= change;
  }
  avgGain /= period;
  avgLoss /= period;

  const out: LinePoint[] = [];
  const toRsi = (g: number, l: number) =>
    l === 0 ? 100 : 100 - 100 / (1 + g / l);
  out.push({ time: bars[period].time, value: toRsi(avgGain, avgLoss) });

  for (let i = period + 1; i < bars.length; i++) {
    const change = bars[i].close - bars[i - 1].close;
    const gain = change > 0 ? change : 0;
    const loss = change < 0 ? -change : 0;
    avgGain = (avgGain * (period - 1) + gain) / period;
    avgLoss = (avgLoss * (period - 1) + loss) / period;
    out.push({ time: bars[i].time, value: toRsi(avgGain, avgLoss) });
  }
  return out;
}

export function macd(
  bars: IndicatorBar[],
  fastPeriod = 12,
  slowPeriod = 26,
  signalPeriod = 9,
): MacdResult {
  const closes = bars.map((b) => b.close);
  const fast = emaArr(closes, fastPeriod);
  const slow = emaArr(closes, slowPeriod);

  const macdLine: LinePoint[] = [];
  const compact: number[] = [];
  const times: number[] = [];
  for (let i = 0; i < bars.length; i++) {
    const f = fast[i];
    const s = slow[i];
    if (f !== null && s !== null) {
      const value = f - s;
      macdLine.push({ time: bars[i].time, value });
      compact.push(value);
      times.push(bars[i].time);
    }
  }

  const signalArr = emaArr(compact, signalPeriod);
  const signal: LinePoint[] = [];
  const histogram: LinePoint[] = [];
  for (let i = 0; i < compact.length; i++) {
    const sig = signalArr[i];
    if (sig !== null) {
      signal.push({ time: times[i], value: sig });
      histogram.push({ time: times[i], value: compact[i] - sig });
    }
  }
  return { macd: macdLine, signal, histogram };
}

// Wilder's ATR. tr index i corresponds to bars[i + 1].
export function atr(bars: IndicatorBar[], period = 14): LinePoint[] {
  if (bars.length < period + 1) return [];
  const tr: number[] = [];
  for (let i = 1; i < bars.length; i++) {
    const h = bars[i].high;
    const l = bars[i].low;
    const pc = bars[i - 1].close;
    tr.push(Math.max(h - l, Math.abs(h - pc), Math.abs(l - pc)));
  }
  const out: LinePoint[] = [];
  let prev = 0;
  for (let i = 0; i < period; i++) prev += tr[i];
  prev /= period;
  out.push({ time: bars[period].time, value: prev });
  for (let i = period; i < tr.length; i++) {
    prev = (prev * (period - 1) + tr[i]) / period;
    out.push({ time: bars[i + 1].time, value: prev });
  }
  return out;
}

export function stochastic(
  bars: IndicatorBar[],
  kPeriod = 14,
  dPeriod = 3,
): StochasticResult {
  const k: LinePoint[] = [];
  for (let i = kPeriod - 1; i < bars.length; i++) {
    let hh = -Infinity;
    let ll = Infinity;
    for (let j = i - kPeriod + 1; j <= i; j++) {
      hh = Math.max(hh, bars[j].high);
      ll = Math.min(ll, bars[j].low);
    }
    const denom = hh - ll;
    k.push({
      time: bars[i].time,
      value: denom === 0 ? 0 : ((bars[i].close - ll) / denom) * 100,
    });
  }
  const d: LinePoint[] = [];
  for (let i = dPeriod - 1; i < k.length; i++) {
    let sum = 0;
    for (let j = i - dPeriod + 1; j <= i; j++) sum += k[j].value;
    d.push({ time: k[i].time, value: sum / dPeriod });
  }
  return { k, d };
}

// Wilder's ADX (trend strength). Returns the ADX line only.
export function adx(bars: IndicatorBar[], period = 14): LinePoint[] {
  if (bars.length < period * 2) return [];
  const plusDM: number[] = [];
  const minusDM: number[] = [];
  const tr: number[] = [];
  for (let i = 1; i < bars.length; i++) {
    const up = bars[i].high - bars[i - 1].high;
    const down = bars[i - 1].low - bars[i].low;
    plusDM.push(up > down && up > 0 ? up : 0);
    minusDM.push(down > up && down > 0 ? down : 0);
    const h = bars[i].high;
    const l = bars[i].low;
    const pc = bars[i - 1].close;
    tr.push(Math.max(h - l, Math.abs(h - pc), Math.abs(l - pc)));
  }

  const smooth = (arr: number[]): number[] => {
    const res = new Array<number>(arr.length).fill(NaN);
    let sum = 0;
    for (let i = 0; i < period; i++) sum += arr[i];
    res[period - 1] = sum;
    for (let i = period; i < arr.length; i++) {
      sum = sum - sum / period + arr[i];
      res[i] = sum;
    }
    return res;
  };

  const sTr = smooth(tr);
  const sPlus = smooth(plusDM);
  const sMinus = smooth(minusDM);
  const dx = new Array<number>(tr.length).fill(NaN);
  for (let i = period - 1; i < tr.length; i++) {
    const pdi = sTr[i] === 0 ? 0 : (100 * sPlus[i]) / sTr[i];
    const mdi = sTr[i] === 0 ? 0 : (100 * sMinus[i]) / sTr[i];
    const denom = pdi + mdi;
    dx[i] = denom === 0 ? 0 : (100 * Math.abs(pdi - mdi)) / denom;
  }

  const firstDx = period - 1;
  if (tr.length < firstDx + period) return [];
  const out: LinePoint[] = [];
  let prev = 0;
  for (let i = firstDx; i < firstDx + period; i++) prev += dx[i];
  prev /= period;
  out.push({ time: bars[firstDx + period].time, value: prev });
  for (let i = firstDx + period; i < tr.length; i++) {
    prev = (prev * (period - 1) + dx[i]) / period;
    out.push({ time: bars[i + 1].time, value: prev });
  }
  return out;
}

export function obv(bars: IndicatorBar[]): LinePoint[] {
  const out: LinePoint[] = [];
  let cum = 0;
  for (let i = 0; i < bars.length; i++) {
    if (i > 0) {
      if (bars[i].close > bars[i - 1].close) cum += bars[i].volume;
      else if (bars[i].close < bars[i - 1].close) cum -= bars[i].volume;
    }
    out.push({ time: bars[i].time, value: cum });
  }
  return out;
}
