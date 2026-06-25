import { useEffect, useMemo, useState } from "react";

import { type IndexSpec, type Instrument, fetchIndices, fetchInstruments } from "./api";
import { type FormingBar, type HoverBar, CandleChart } from "./CandleChart";
import { ChartControls } from "./ChartControls";
import { RealtimeErrorBoundary } from "./ErrorBoundary";
import { IndexStrip } from "./IndexStrip";
import { type LastBarSnapshot, LastBarPanel } from "./LastBarPanel";
import { LiveDataPanel } from "./LiveDataPanel";
import { SymbolBar } from "./SymbolBar";
import { fmtCompact, fmtPrice } from "./format";
import {
  type IndicatorBar,
  type IndicatorId,
  type IndicatorRender,
  INDICATORS,
  INDICATOR_BY_ID,
  computeIndicator,
} from "./indicators";
import { useBars } from "./useBars";
import { useTickStream, type LiveTick, type LiveIndex, type StreamStatus } from "./useTickStream";
import {
  type CandleCode,
  type WindowCode,
  CANDLE_SECONDS,
  SUGGESTED_CANDLE,
  WINDOW_SECONDS,
  fetchLimitFor,
} from "./windowCandle";
import "./realtime.css";

type RealtimePageProps = {
  apiBaseUrl: string;
  authToken: string;
  /** When set, symbol/candle/window come from the global market filters. */
  symbol?: string;
  onSymbolChange?: (symbol: string) => void;
  candle?: CandleCode;
  window?: WindowCode;
  manualCandle?: boolean;
  onCandleChange?: (candle: CandleCode) => void;
  onWindowChange?: (window: WindowCode) => void;
  hideTimeframeControls?: boolean;
  hideIndicatorControls?: boolean;
  hideSymbolBar?: boolean;
  activeIndicators?: ReadonlySet<IndicatorId>;
  onToggleIndicator?: (id: IndicatorId) => void;
  /** Parent-owned WS stream (avoids duplicate connection). */
  useParentStream?: boolean;
  tick?: LiveTick | null;
  indices?: Record<string, LiveIndex>;
  streamStatus?: StreamStatus;
  streamError?: string | null;
};

const DEFAULT_SYMBOL = "AAPL";
const DEFAULT_WINDOW: WindowCode = "4h";
const DEFAULT_FOLLOWED = ["AAPL", "MSFT", "NVDA"];

function isoSec(iso: string): number {
  const hasTz = /[zZ]$|[+-]\d\d:?\d\d$/.test(iso);
  return Math.floor(Date.parse(hasTz ? iso : `${iso}Z`) / 1000);
}

export function RealtimePage(props: RealtimePageProps) {
  return (
    <RealtimeErrorBoundary>
      <RealtimePageContent {...props} />
    </RealtimeErrorBoundary>
  );
}

function RealtimePageContent({
  apiBaseUrl,
  authToken,
  symbol: symbolProp,
  onSymbolChange,
  candle: candleProp,
  window: windowProp,
  manualCandle: manualCandleProp,
  onCandleChange,
  onWindowChange,
  hideTimeframeControls = false,
  hideIndicatorControls = false,
  hideSymbolBar = false,
  activeIndicators: activeIndicatorsProp,
  onToggleIndicator: onToggleIndicatorProp,
  useParentStream = false,
  tick: tickProp,
  indices: indicesProp,
  streamStatus: streamStatusProp,
  streamError: streamErrorProp,
}: RealtimePageProps) {
  const [localSymbol, setLocalSymbol] = useState<string>(DEFAULT_SYMBOL);
  const [localWindow, setLocalWindow] = useState<WindowCode>(DEFAULT_WINDOW);
  const [localCandle, setLocalCandle] = useState<CandleCode>(SUGGESTED_CANDLE[DEFAULT_WINDOW]);
  const [localManualCandle, setLocalManualCandle] = useState<boolean>(false);

  const symbol = symbolProp ?? localSymbol;
  const window = windowProp ?? localWindow;
  const candle = candleProp ?? localCandle;
  const manualCandle = manualCandleProp ?? localManualCandle;

  const setSymbol = (next: string) => {
    onSymbolChange?.(next);
    if (symbolProp === undefined) {
      setLocalSymbol(next);
    }
  };
  const [localActiveIndicators, setLocalActiveIndicators] = useState<ReadonlySet<IndicatorId>>(
    () => new Set(INDICATORS.filter((d) => d.defaultOn).map((d) => d.id)),
  );
  const active = activeIndicatorsProp ?? localActiveIndicators;
  const onToggleIndicator = (id: IndicatorId) => {
    onToggleIndicatorProp?.(id);
    if (activeIndicatorsProp === undefined) {
      setLocalActiveIndicators((previous) => {
        const next = new Set(previous);
        if (next.has(id)) {
          next.delete(id);
        } else {
          next.add(id);
        }
        return next;
      });
    }
  };
  const [hoverBar, setHoverBar] = useState<HoverBar | null>(null);
  const [nowMs, setNowMs] = useState<number>(() => Date.now());

  // 1s ticker so the connection "última barra há Xs" label advances.
  useEffect(() => {
    const timer = globalThis.setInterval(() => setNowMs(Date.now()), 1000);
    return () => globalThis.clearInterval(timer);
  }, []);

  const { bars, loading, error: barsError } = useBars(
    apiBaseUrl,
    authToken,
    symbol,
    candle,
    window,
    fetchLimitFor(window, candle),
  );
  const { tick: ownedTick, indices: ownedIndices, status: ownedStatus, error: ownedStreamError } =
    useTickStream(apiBaseUrl, useParentStream ? "" : authToken, symbol);
  const tick = useParentStream ? (tickProp ?? null) : ownedTick;
  const indices = useParentStream ? (indicesProp ?? {}) : ownedIndices;
  const status = useParentStream ? (streamStatusProp ?? "closed") : ownedStatus;
  const streamError = useParentStream ? streamErrorProp : ownedStreamError;

  // Followed chips: default set merged with persisted instruments.
  const [instruments, setInstruments] = useState<Instrument[]>([]);
  const [indexSpecs, setIndexSpecs] = useState<IndexSpec[]>([]);
  useEffect(() => {
    if (!authToken) return;
    let cancelled = false;
    fetchInstruments(apiBaseUrl, authToken)
      .then((rows) => !cancelled && setInstruments(rows))
      .catch(() => undefined);
    fetchIndices(apiBaseUrl, authToken)
      .then((rows) => !cancelled && setIndexSpecs(rows))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [apiBaseUrl, authToken]);

  const followed = useMemo(() => {
    const set = new Set<string>(DEFAULT_FOLLOWED);
    for (const inst of instruments) set.add(inst.symbol);
    set.add(symbol);
    return Array.from(set).sort();
  }, [instruments, symbol]);

  const symbolName = useMemo(
    () => instruments.find((i) => i.symbol === symbol)?.name ?? null,
    [instruments, symbol],
  );

  // Indicator bars (numeric, ascending, deduped) memoized off the loaded bars.
  const indicatorBars: IndicatorBar[] = useMemo(() => {
    const mapped = bars
      .map((b) => ({
        time: isoSec(b.timestamp),
        open: Number(b.open),
        high: Number(b.high),
        low: Number(b.low),
        close: Number(b.close),
        volume: Number(b.volume),
      }))
      .filter((b) => Number.isFinite(b.close))
      .sort((a, b) => a.time - b.time);
    const out: IndicatorBar[] = [];
    for (const b of mapped) {
      const last = out[out.length - 1];
      if (last && last.time === b.time) out[out.length - 1] = b;
      else out.push(b);
    }
    return out;
  }, [bars]);

  const indicatorRenders: IndicatorRender[] = useMemo(
    () => Array.from(active).map((id) => computeIndicator(INDICATOR_BY_ID[id], indicatorBars)),
    [active, indicatorBars],
  );

  // Live forming bar: only mutate a genuinely non-final last bar with the tick,
  // never a closed one (the closed-bars-only persistence contract, mirrored in
  // the UI). Closed bars stay a SNAPSHOT.
  const lastBar = bars.length > 0 ? bars[bars.length - 1] : null;
  const isForming = lastBar !== null && lastBar.is_final === false;

  const forming: FormingBar | null = useMemo(() => {
    if (!lastBar || !isForming || tick?.last == null) return null;
    return {
      time: isoSec(lastBar.timestamp),
      open: Number(lastBar.open),
      high: Math.max(Number(lastBar.high), tick.last),
      low: Math.min(Number(lastBar.low), tick.last),
      close: tick.last,
      volume: Number(lastBar.volume),
    };
  }, [lastBar, isForming, tick]);

  const lastSnapshot: LastBarSnapshot | null = useMemo(() => {
    if (!lastBar) return null;
    const live = isForming && tick?.last != null;
    return {
      open: Number(lastBar.open),
      high: live ? Math.max(Number(lastBar.high), tick.last as number) : Number(lastBar.high),
      low: live ? Math.min(Number(lastBar.low), tick.last as number) : Number(lastBar.low),
      close: live ? (tick.last as number) : Number(lastBar.close),
      volume: Number(lastBar.volume),
      wap: null, // WAP/trades only arrive on keepUpToDate bars
      trades: null,
      closeTimeMs: (isoSec(lastBar.timestamp) + CANDLE_SECONDS[candle]) * 1000,
      forming: isForming,
    };
  }, [lastBar, isForming, tick, candle]);

  const lastBarMs = lastBar ? isoSec(lastBar.timestamp) * 1000 : null;

  // chart-head: hovered bar, else the live/last bar.
  const headBar = hoverBar ?? (forming as HoverBar | null) ??
    (lastBar
      ? {
          time: isoSec(lastBar.timestamp),
          open: Number(lastBar.open),
          high: Number(lastBar.high),
          low: Number(lastBar.low),
          close: Number(lastBar.close),
          volume: Number(lastBar.volume),
        }
      : null);
  const headDir = headBar ? (headBar.close >= headBar.open ? "up" : "down") : "up";

  const onWindow = (w: WindowCode) => {
    onWindowChange?.(w);
    if (windowProp === undefined) {
      setLocalWindow(w);
      if (!manualCandle) {
        setLocalCandle(SUGGESTED_CANDLE[w]);
      }
    }
  };
  const onCandle = (c: CandleCode) => {
    onCandleChange?.(c);
    if (candleProp === undefined) {
      setLocalCandle(c);
      setLocalManualCandle(c !== SUGGESTED_CANDLE[window]);
    }
  };

  if (!authToken) {
    return (
      <div className="rt-page">
        <p className="hint">Inicie sessão para ver o feed em tempo real.</p>
      </div>
    );
  }

  return (
    <div className="rt-page">
      {!hideSymbolBar && (
        <SymbolBar
          apiBaseUrl={apiBaseUrl}
          authToken={authToken}
          symbol={symbol}
          name={symbolName}
          followed={followed}
          onSelect={setSymbol}
          status={status}
          lastBarMs={lastBarMs}
          nowMs={nowMs}
        />
      )}

      <ChartControls
        window={window}
        candle={candle}
        manualCandle={manualCandle}
        active={active}
        onWindow={onWindow}
        onCandle={onCandle}
        onToggleIndicator={onToggleIndicator}
        hideTimeframeRows={hideTimeframeControls}
        hideIndicatorRows={hideIndicatorControls}
      />

      {streamError && <p className="hint">{streamError}</p>}

      <div className="rt-main">
        <div className="rt-chart-wrap">
          {headBar && (
            <div className="rt-chart-head">
              <span className={`rt-head-px rt-${headDir}`}>{fmtPrice(headBar.close)}</span>
              <span className="rt-head-ohlc">
                <span>O <b>{fmtPrice(headBar.open)}</b></span>
                <span>H <b>{fmtPrice(headBar.high)}</b></span>
                <span>L <b>{fmtPrice(headBar.low)}</b></span>
                <span>C <b>{fmtPrice(headBar.close)}</b></span>
                <span>Vol <b>{fmtCompact(headBar.volume)}</b></span>
              </span>
            </div>
          )}
          {loading && bars.length === 0 && <p className="hint rt-chart-empty">A carregar velas…</p>}
          {!loading && !barsError && bars.length === 0 && (
            <p className="hint rt-chart-empty">
              Sem velas para {symbol} ({candle}). Verifique o IB Gateway / worker.
            </p>
          )}
          {barsError && bars.length === 0 && <p className="error rt-chart-empty">{barsError}</p>}
          {bars.length > 0 && (
            <CandleChart
              bars={bars}
              forming={forming}
              indicators={indicatorRenders}
              windowSeconds={WINDOW_SECONDS[window]}
              onHoverBar={setHoverBar}
            />
          )}
        </div>

        <div className="rt-rail">
          <LiveDataPanel tick={tick} />
          <LastBarPanel bar={lastSnapshot} candle={candle} />
        </div>
      </div>

      <IndexStrip specs={indexSpecs} live={indices} />
    </div>
  );
}
