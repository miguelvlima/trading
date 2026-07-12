from __future__ import annotations

"""
Strategy signal generation for backtesting and live signal views.

Signal contract (no lookahead across bars):
- A signal timestamped at bar *T* uses OHLCV from bars ``0..T`` inclusive.
- The decision point is the **close of bar T** (end-of-bar), never a future bar.
- Pair with ``execution_timing=next_open`` in the backtest engine to enter at T+1 open,
  or ``signal_close`` to enter at the close of T after the signal is known.
"""

import math
from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from app.services.indicator_engine import (
    atr,
    bollinger_bands,
    ema,
    macd,
    rsi,
    sma,
    swing_pivots,
)

_NY = ZoneInfo("America/New_York")


@dataclass
class StrategySignal:
    symbol: str
    strategy: str
    direction: str
    strength: float
    rationale: str
    timestamp: datetime
    indicator_snapshot: dict[str, float | None]
    # Exit levels suggested by the signal itself (percentages 0-100 relative to
    # the entry price). None → the paper engine falls back to the portfolio
    # defaults; the risk manager still vetoes entries that end up with no stop.
    suggested_stop_pct: float | None = None
    suggested_take_profit_pct: float | None = None


@dataclass
class BarInput:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


class BaseStrategy(ABC):
    name: str

    @abstractmethod
    def generate_signals(self, symbol: str, bars: list[BarInput]) -> list[StrategySignal]:
        raise NotImplementedError


def _clamp_strength(raw_value: float) -> float:
    return max(0.0, min(1.0, raw_value))


def _session_day(timestamp: datetime) -> date:
    """Trading-session date of a bar, in exchange local time.

    Naive timestamps are treated as UTC (how MarketBar rows come out of the
    DB); the NY conversion keeps a session's bars together even though an
    American session crosses midnight UTC in winter.
    """
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(_NY).date()


def _group_by_session(bars: list[BarInput]) -> dict[date, list[int]]:
    """Bar indices per NY session day, preserving intra-session order."""
    sessions: dict[date, list[int]] = {}
    for index, bar in enumerate(bars):
        sessions.setdefault(_session_day(bar.timestamp), []).append(index)
    return sessions


class RsiMeanReversionStrategy(BaseStrategy):
    name = "rsi_mean_reversion"

    # Stop at 1.5x ATR(14) from the entry: wide enough to survive normal noise
    # on a volatile symbol, tight on a calm one. Floor of 0.5% because an ATR
    # near zero (thin/flat session) would put the stop inside the spread.
    ATR_STOP_MULTIPLE = 1.5
    MIN_STOP_PCT = 0.5

    @classmethod
    def _suggested_stop_pct(cls, atr_value: float | None, close: float) -> float | None:
        if atr_value is None or close <= 0:
            return None
        return max(cls.MIN_STOP_PCT, atr_value / close * 100.0 * cls.ATR_STOP_MULTIPLE)

    def generate_signals(self, symbol: str, bars: list[BarInput]) -> list[StrategySignal]:
        closes = [bar.close for bar in bars]
        rsi_values = rsi(closes, period=14)
        atr_values = atr(
            [bar.high for bar in bars], [bar.low for bar in bars], closes, period=14
        )
        signals: list[StrategySignal] = []

        for index, (bar, rsi_value) in enumerate(zip(bars, rsi_values, strict=False)):
            if rsi_value is None:
                continue
            atr_value = atr_values[index]
            stop_pct = self._suggested_stop_pct(atr_value, bar.close)
            if rsi_value < 30:
                strength = _clamp_strength((30 - rsi_value) / 30)
                signals.append(
                    StrategySignal(
                        symbol=symbol,
                        strategy=self.name,
                        direction="BUY",
                        strength=strength,
                        rationale=f"RSI(14) em sobrevenda ({rsi_value:.2f} < 30).",
                        timestamp=bar.timestamp,
                        indicator_snapshot={"rsi_14": rsi_value, "atr_14": atr_value},
                        suggested_stop_pct=stop_pct,
                    )
                )
            elif rsi_value > 70:
                strength = _clamp_strength((rsi_value - 70) / 30)
                signals.append(
                    StrategySignal(
                        symbol=symbol,
                        strategy=self.name,
                        direction="SELL",
                        strength=strength,
                        rationale=f"RSI(14) em sobrecompra ({rsi_value:.2f} > 70).",
                        timestamp=bar.timestamp,
                        indicator_snapshot={"rsi_14": rsi_value, "atr_14": atr_value},
                        suggested_stop_pct=stop_pct,
                    )
                )
        return signals


class MacdCrossoverStrategy(BaseStrategy):
    name = "macd_crossover"

    def generate_signals(self, symbol: str, bars: list[BarInput]) -> list[StrategySignal]:
        closes = [bar.close for bar in bars]
        macd_line, signal_line, _ = macd(closes, 12, 26, 9)
        signals: list[StrategySignal] = []

        for index in range(1, len(bars)):
            previous_macd = macd_line[index - 1]
            previous_signal = signal_line[index - 1]
            current_macd = macd_line[index]
            current_signal = signal_line[index]
            if (
                previous_macd is None
                or previous_signal is None
                or current_macd is None
                or current_signal is None
            ):
                continue

            spread = abs(current_macd - current_signal)
            strength = _clamp_strength(spread / max(abs(current_signal), 1.0))
            if previous_macd <= previous_signal and current_macd > current_signal:
                signals.append(
                    StrategySignal(
                        symbol=symbol,
                        strategy=self.name,
                        direction="BUY",
                        strength=strength,
                        rationale=(
                            f"MACD cruzou acima da linha de sinal ({current_macd:.4f} > {current_signal:.4f})."
                        ),
                        timestamp=bars[index].timestamp,
                        indicator_snapshot={"macd": current_macd, "macd_signal": current_signal},
                    )
                )
            elif previous_macd >= previous_signal and current_macd < current_signal:
                signals.append(
                    StrategySignal(
                        symbol=symbol,
                        strategy=self.name,
                        direction="SELL",
                        strength=strength,
                        rationale=(
                            f"MACD cruzou abaixo da linha de sinal ({current_macd:.4f} < {current_signal:.4f})."
                        ),
                        timestamp=bars[index].timestamp,
                        indicator_snapshot={"macd": current_macd, "macd_signal": current_signal},
                    )
                )
        return signals


class SmaEmaCrossoverStrategy(BaseStrategy):
    name = "sma_ema_crossover"

    def generate_signals(self, symbol: str, bars: list[BarInput]) -> list[StrategySignal]:
        closes = [bar.close for bar in bars]
        sma_values = sma(closes, 20)
        ema_values = ema(closes, 50)
        signals: list[StrategySignal] = []

        for index in range(1, len(bars)):
            previous_sma = sma_values[index - 1]
            previous_ema = ema_values[index - 1]
            current_sma = sma_values[index]
            current_ema = ema_values[index]
            if previous_sma is None or previous_ema is None or current_sma is None or current_ema is None:
                continue

            spread = abs(current_sma - current_ema)
            strength = _clamp_strength(spread / max(abs(current_ema), 1.0))
            if previous_sma <= previous_ema and current_sma > current_ema:
                signals.append(
                    StrategySignal(
                        symbol=symbol,
                        strategy=self.name,
                        direction="BUY",
                        strength=strength,
                        rationale=f"SMA(20) cruzou acima de EMA(50) ({current_sma:.4f} > {current_ema:.4f}).",
                        timestamp=bars[index].timestamp,
                        indicator_snapshot={"sma_20": current_sma, "ema_50": current_ema},
                    )
                )
            elif previous_sma >= previous_ema and current_sma < current_ema:
                signals.append(
                    StrategySignal(
                        symbol=symbol,
                        strategy=self.name,
                        direction="SELL",
                        strength=strength,
                        rationale=f"SMA(20) cruzou abaixo de EMA(50) ({current_sma:.4f} < {current_ema:.4f}).",
                        timestamp=bars[index].timestamp,
                        indicator_snapshot={"sma_20": current_sma, "ema_50": current_ema},
                    )
                )
        return signals


class BollingerBreakoutStrategy(BaseStrategy):
    name = "bollinger_breakout"

    def generate_signals(self, symbol: str, bars: list[BarInput]) -> list[StrategySignal]:
        closes = [bar.close for bar in bars]
        upper, middle, lower = bollinger_bands(closes, 20, 2.0)
        signals: list[StrategySignal] = []

        # Bands at T-1 vs close at T: avoids same-bar circularity (close moving the band it breaks).
        for index in range(1, len(bars)):
            bar = bars[index]
            close_price = closes[index]
            upper_band = upper[index - 1]
            middle_band = middle[index - 1]
            lower_band = lower[index - 1]
            if upper_band is None or middle_band is None or lower_band is None:
                continue

            width = max(upper_band - lower_band, 1.0)
            if close_price > upper_band:
                strength = _clamp_strength((close_price - upper_band) / width)
                signals.append(
                    StrategySignal(
                        symbol=symbol,
                        strategy=self.name,
                        direction="BUY",
                        strength=strength,
                        rationale=(
                            f"Fecho acima da banda superior de Bollinger ({close_price:.4f} > {upper_band:.4f})."
                        ),
                        timestamp=bar.timestamp,
                        indicator_snapshot={
                            "close": close_price,
                            "bollinger_upper": upper_band,
                            "bollinger_middle": middle_band,
                            "bollinger_lower": lower_band,
                        },
                    )
                )
            elif close_price < lower_band:
                strength = _clamp_strength((lower_band - close_price) / width)
                signals.append(
                    StrategySignal(
                        symbol=symbol,
                        strategy=self.name,
                        direction="SELL",
                        strength=strength,
                        rationale=(
                            f"Fecho abaixo da banda inferior de Bollinger ({close_price:.4f} < {lower_band:.4f})."
                        ),
                        timestamp=bar.timestamp,
                        indicator_snapshot={
                            "close": close_price,
                            "bollinger_upper": upper_band,
                            "bollinger_middle": middle_band,
                            "bollinger_lower": lower_band,
                        },
                    )
                )
        return signals


class OpeningRangeBreakoutStrategy(BaseStrategy):
    """Breakout do range de abertura: high/low dos primeiros 30 min da sessão.

    BUY quando um fecho posterior quebra acima do range high, SELL quando
    quebra abaixo do range low — no máximo um sinal por direção por sessão.
    O stop sugerido é o lado oposto do range (a invalidação natural do padrão).
    """

    name = "opening_range_breakout"
    RANGE_MINUTES = 30
    DEFAULT_RANGE_BARS = 6  # 30 min in 5m bars

    @classmethod
    def _range_bar_count(cls, bars: list[BarInput]) -> int:
        """Bars that make up 30 minutes, from the modal spacing between bars.

        The modal (not minimum) spacing survives session gaps and the odd
        missing bar. Spacing above 30 min (daily bars) falls back to the 5m
        default — the session grouping then leaves no room to signal, which
        is the correct behaviour for a strategy that is intraday-only.
        """
        deltas = [
            (bars[index].timestamp - bars[index - 1].timestamp).total_seconds()
            for index in range(1, len(bars))
        ]
        deltas = [delta for delta in deltas if delta > 0]
        if not deltas:
            return cls.DEFAULT_RANGE_BARS
        spacing = Counter(deltas).most_common(1)[0][0]
        if spacing > cls.RANGE_MINUTES * 60:
            return cls.DEFAULT_RANGE_BARS
        return max(1, int(cls.RANGE_MINUTES * 60 // spacing))

    def generate_signals(self, symbol: str, bars: list[BarInput]) -> list[StrategySignal]:
        signals: list[StrategySignal] = []
        if len(bars) < 2:
            return signals
        range_bars = self._range_bar_count(bars)

        for indices in _group_by_session(bars).values():
            if len(indices) <= range_bars:
                continue
            opening = [bars[i] for i in indices[:range_bars]]
            range_high = max(bar.high for bar in opening)
            range_low = min(bar.low for bar in opening)
            width = range_high - range_low
            if width <= 0:
                continue

            fired = {"BUY": False, "SELL": False}
            for index in indices[range_bars:]:
                bar = bars[index]
                if not fired["BUY"] and bar.close > range_high:
                    fired["BUY"] = True
                    signals.append(
                        StrategySignal(
                            symbol=symbol,
                            strategy=self.name,
                            direction="BUY",
                            strength=_clamp_strength((bar.close - range_high) / width),
                            rationale=(
                                f"Quebra acima do range de abertura ({bar.close:.2f} > "
                                f"{range_high:.2f}; range {range_low:.2f}-{range_high:.2f})."
                            ),
                            timestamp=bar.timestamp,
                            indicator_snapshot={
                                "range_high": range_high,
                                "range_low": range_low,
                                "range_bars": float(range_bars),
                            },
                            # Invalidation = the far side of the opening range.
                            suggested_stop_pct=(bar.close - range_low) / bar.close * 100.0,
                        )
                    )
                elif not fired["SELL"] and bar.close < range_low:
                    fired["SELL"] = True
                    signals.append(
                        StrategySignal(
                            symbol=symbol,
                            strategy=self.name,
                            direction="SELL",
                            strength=_clamp_strength((range_low - bar.close) / width),
                            rationale=(
                                f"Quebra abaixo do range de abertura ({bar.close:.2f} < "
                                f"{range_low:.2f}; range {range_low:.2f}-{range_high:.2f})."
                            ),
                            timestamp=bar.timestamp,
                            indicator_snapshot={
                                "range_high": range_high,
                                "range_low": range_low,
                                "range_bars": float(range_bars),
                            },
                            suggested_stop_pct=(range_high - bar.close) / bar.close * 100.0,
                        )
                    )
                if fired["BUY"] and fired["SELL"]:
                    break
        return signals


class VwapReversionStrategy(BaseStrategy):
    """Reversão à média do VWAP intradiário (reset por sessão).

    BUY quando o fecho está mais de K desvios abaixo do VWAP, SELL simétrico.
    O desvio-padrão é o dos desvios ANTERIORES da própria sessão — a barra em
    avaliação nunca entra na régua que a mede.
    """

    name = "vwap_reversion"
    K = 1.5
    # Deviations needed before the session std is trustworthy; also keeps the
    # noisy first half-hour (in 1m/5m bars) from firing on a cold start.
    MIN_HISTORY = 10

    def generate_signals(self, symbol: str, bars: list[BarInput]) -> list[StrategySignal]:
        signals: list[StrategySignal] = []

        for indices in _group_by_session(bars).values():
            cumulative_pv = 0.0
            cumulative_volume = 0.0
            deviations: list[float] = []
            for index in indices:
                bar = bars[index]
                typical = (bar.high + bar.low + bar.close) / 3.0
                cumulative_pv += typical * bar.volume
                cumulative_volume += bar.volume
                if cumulative_volume <= 0:
                    continue  # no volume yet: VWAP undefined, keep accumulating
                session_vwap = cumulative_pv / cumulative_volume
                deviation = bar.close - session_vwap

                if len(deviations) >= self.MIN_HISTORY:
                    mean = sum(deviations) / len(deviations)
                    variance = sum((d - mean) ** 2 for d in deviations) / len(deviations)
                    std = math.sqrt(variance)
                    if std > 0:
                        z_score = deviation / std
                        if abs(z_score) >= self.K:
                            direction = "BUY" if z_score < 0 else "SELL"
                            side_text = "abaixo" if z_score < 0 else "acima"
                            signals.append(
                                StrategySignal(
                                    symbol=symbol,
                                    strategy=self.name,
                                    direction=direction,
                                    strength=_clamp_strength(
                                        (abs(z_score) - self.K) / self.K
                                    ),
                                    rationale=(
                                        f"Fecho {bar.close:.2f} está {abs(z_score):.1f} desvios "
                                        f"{side_text} do VWAP da sessão ({session_vwap:.2f})."
                                    ),
                                    timestamp=bar.timestamp,
                                    indicator_snapshot={
                                        "vwap": session_vwap,
                                        "deviation": deviation,
                                        "z_score": z_score,
                                    },
                                )
                            )
                deviations.append(deviation)
        return signals


class DoubleTopBottomStrategy(BaseStrategy):
    """Duplo topo / duplo fundo sobre pivots zigzag.

    Dois pivots do mesmo lado ao mesmo nível (tolerância 0.5%) com o pivot
    oposto entre eles como neckline; o sinal dispara APENAS na barra cujo
    fecho quebra a neckline — nunca antes (os pivots só contam depois de
    confirmados: ``confirmed_at_index``). Alvo = altura do padrão projetada
    da neckline (measured move); stop = para lá do segundo topo/fundo.
    """

    name = "double_top_bottom"
    PIVOT_THRESHOLD_PCT = 1.0
    LEVEL_TOLERANCE = 0.005  # the two tops/bottoms must match within 0.5%
    MIN_BARS = 10
    # height/price is a few percent on a real pattern; x10 maps a 3% pattern
    # to strength 0.3 (the engine's default minimum) and a 10% one to 1.0.
    STRENGTH_SCALE = 10.0

    @staticmethod
    def _first_break_index(
        bars: list[BarInput], *, start: int, level: float, below: bool
    ) -> int | None:
        for index in range(start, len(bars)):
            close = bars[index].close
            if below and close < level:
                return index
            if not below and close > level:
                return index
        return None

    def _level_pct(self, reference: float, close: float) -> float | None:
        pct = abs(reference - close) / close * 100.0
        return pct if pct > 0 else None

    def generate_signals(self, symbol: str, bars: list[BarInput]) -> list[StrategySignal]:
        signals: list[StrategySignal] = []
        if len(bars) < self.MIN_BARS:
            return signals
        pivots = swing_pivots(bars, self.PIVOT_THRESHOLD_PCT)

        for j in range(2, len(pivots)):
            first, middle, second = pivots[j - 2], pivots[j - 1], pivots[j]
            if first.kind != second.kind:  # needs two same-side pivots
                continue
            if abs(second.price - first.price) > self.LEVEL_TOLERANCE * first.price:
                continue
            neckline = middle.price
            extreme = (first.price + second.price) / 2.0
            is_top = first.kind == "high"
            height = extreme - neckline if is_top else neckline - extreme
            if height <= 0 or neckline <= 0:
                continue

            # The pattern only exists once the second pivot is CONFIRMED; the
            # break scan starts there, so the signal can never predate the
            # information it uses.
            break_index = self._first_break_index(
                bars, start=second.confirmed_at_index, level=neckline, below=is_top
            )
            if break_index is None:
                continue
            bar = bars[break_index]

            if is_top:
                direction = "SELL"
                label = "Duplo topo"
                target = neckline - height
                stop_pct = self._level_pct(second.price, bar.close)
                target_pct = self._level_pct(target, bar.close) if target < bar.close else None
            else:
                direction = "BUY"
                label = "Duplo fundo"
                target = neckline + height
                stop_pct = self._level_pct(second.price, bar.close)
                target_pct = self._level_pct(target, bar.close) if target > bar.close else None

            signals.append(
                StrategySignal(
                    symbol=symbol,
                    strategy=self.name,
                    direction=direction,
                    strength=_clamp_strength(height / bar.close * self.STRENGTH_SCALE),
                    rationale=(
                        f"{label} em {first.price:.2f}/{second.price:.2f} com neckline "
                        f"{neckline:.2f}; fecho {bar.close:.2f} quebra a neckline "
                        f"(alvo {target:.2f})."
                    ),
                    timestamp=bar.timestamp,
                    indicator_snapshot={
                        "first_pivot": first.price,
                        "second_pivot": second.price,
                        "neckline": neckline,
                        "pattern_height": height,
                        "measured_move_target": target,
                    },
                    suggested_stop_pct=stop_pct,
                    suggested_take_profit_pct=target_pct,
                )
            )
        return signals


STRATEGY_REGISTRY: dict[str, BaseStrategy] = {
    RsiMeanReversionStrategy.name: RsiMeanReversionStrategy(),
    MacdCrossoverStrategy.name: MacdCrossoverStrategy(),
    SmaEmaCrossoverStrategy.name: SmaEmaCrossoverStrategy(),
    BollingerBreakoutStrategy.name: BollingerBreakoutStrategy(),
    OpeningRangeBreakoutStrategy.name: OpeningRangeBreakoutStrategy(),
    VwapReversionStrategy.name: VwapReversionStrategy(),
    DoubleTopBottomStrategy.name: DoubleTopBottomStrategy(),
}


def get_available_strategies() -> list[str]:
    return sorted(STRATEGY_REGISTRY.keys())


def run_strategy(strategy_name: str, symbol: str, bars: list[BarInput]) -> list[StrategySignal]:
    strategy = STRATEGY_REGISTRY.get(strategy_name)
    if strategy is None:
        available = ", ".join(get_available_strategies())
        raise ValueError(f"Unknown strategy '{strategy_name}'. Available strategies: {available}")
    return strategy.generate_signals(symbol=symbol, bars=bars)
