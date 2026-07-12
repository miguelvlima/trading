from __future__ import annotations

"""
Strategy signal generation for backtesting and live signal views.

Signal contract (no lookahead across bars):
- A signal timestamped at bar *T* uses OHLCV from bars ``0..T`` inclusive.
- The decision point is the **close of bar T** (end-of-bar), never a future bar.
- Pair with ``execution_timing=next_open`` in the backtest engine to enter at T+1 open,
  or ``signal_close`` to enter at the close of T after the signal is known.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from app.services.indicator_engine import atr, bollinger_bands, ema, macd, rsi, sma


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


STRATEGY_REGISTRY: dict[str, BaseStrategy] = {
    RsiMeanReversionStrategy.name: RsiMeanReversionStrategy(),
    MacdCrossoverStrategy.name: MacdCrossoverStrategy(),
    SmaEmaCrossoverStrategy.name: SmaEmaCrossoverStrategy(),
    BollingerBreakoutStrategy.name: BollingerBreakoutStrategy(),
}


def get_available_strategies() -> list[str]:
    return sorted(STRATEGY_REGISTRY.keys())


def run_strategy(strategy_name: str, symbol: str, bars: list[BarInput]) -> list[StrategySignal]:
    strategy = STRATEGY_REGISTRY.get(strategy_name)
    if strategy is None:
        available = ", ".join(get_available_strategies())
        raise ValueError(f"Unknown strategy '{strategy_name}'. Available strategies: {available}")
    return strategy.generate_signals(symbol=symbol, bars=bars)
