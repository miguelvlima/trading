import math


def _validate_period(period: int) -> None:
    if period <= 0:
        raise ValueError("period must be greater than zero")


def _validate_same_length(*series: list[float]) -> None:
    lengths = {len(values) for values in series}
    if len(lengths) > 1:
        raise ValueError("all input series must have the same length")


def sma(values: list[float], period: int) -> list[float | None]:
    _validate_period(period)
    result: list[float | None] = []
    rolling_sum = 0.0
    for index, value in enumerate(values):
        rolling_sum += value
        if index >= period:
            rolling_sum -= values[index - period]
        if index + 1 >= period:
            result.append(rolling_sum / period)
        else:
            result.append(None)
    return result


def ema(values: list[float], period: int) -> list[float | None]:
    _validate_period(period)
    if not values:
        return []

    result: list[float | None] = [None] * len(values)
    multiplier = 2.0 / (period + 1)
    if len(values) < period:
        return result

    initial_sma = sum(values[:period]) / period
    ema_value = initial_sma
    result[period - 1] = ema_value

    for index in range(period, len(values)):
        ema_value = (values[index] - ema_value) * multiplier + ema_value
        result[index] = ema_value

    return result


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    _validate_period(period)
    if len(values) < 2:
        return [None for _ in values]

    result: list[float | None] = [None] * len(values)
    if len(values) <= period:
        return result

    gains: list[float] = []
    losses: list[float] = []
    for index in range(1, period + 1):
        delta = values[index] - values[index - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    average_gain = sum(gains) / period
    average_loss = sum(losses) / period

    if average_loss == 0:
        result[period] = 100.0
    else:
        relative_strength = average_gain / average_loss
        result[period] = 100.0 - (100.0 / (1.0 + relative_strength))

    for index in range(period + 1, len(values)):
        delta = values[index] - values[index - 1]
        gain = max(delta, 0.0)
        loss = max(-delta, 0.0)

        average_gain = ((average_gain * (period - 1)) + gain) / period
        average_loss = ((average_loss * (period - 1)) + loss) / period

        if average_loss == 0:
            result[index] = 100.0
        else:
            relative_strength = average_gain / average_loss
            result[index] = 100.0 - (100.0 / (1.0 + relative_strength))

    return result


def macd(
    values: list[float], fast_period: int = 12, slow_period: int = 26, signal_period: int = 9
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    _validate_period(fast_period)
    _validate_period(slow_period)
    _validate_period(signal_period)
    if fast_period >= slow_period:
        raise ValueError("fast_period must be less than slow_period")

    fast_ema = ema(values, fast_period)
    slow_ema = ema(values, slow_period)

    macd_line: list[float | None] = []
    for fast_value, slow_value in zip(fast_ema, slow_ema, strict=False):
        if fast_value is None or slow_value is None:
            macd_line.append(None)
        else:
            macd_line.append(fast_value - slow_value)

    signal_line: list[float | None] = [None] * len(values)
    valid_macd = [value for value in macd_line if value is not None]
    signal_values = ema(valid_macd, signal_period) if valid_macd else []

    signal_index = 0
    for index, value in enumerate(macd_line):
        if value is None:
            continue
        if signal_index < len(signal_values):
            signal_line[index] = signal_values[signal_index]
            signal_index += 1

    histogram: list[float | None] = []
    for macd_value, signal_value in zip(macd_line, signal_line, strict=False):
        if macd_value is None or signal_value is None:
            histogram.append(None)
        else:
            histogram.append(macd_value - signal_value)

    return macd_line, signal_line, histogram


def bollinger_bands(
    values: list[float], period: int = 20, std_dev_multiplier: float = 2.0
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    _validate_period(period)
    middle = sma(values, period)
    upper: list[float | None] = [None] * len(values)
    lower: list[float | None] = [None] * len(values)

    for index in range(period - 1, len(values)):
        window = values[index - period + 1 : index + 1]
        mean = middle[index]
        if mean is None:
            continue
        variance = sum((value - mean) ** 2 for value in window) / period
        deviation = math.sqrt(variance)
        upper[index] = mean + std_dev_multiplier * deviation
        lower[index] = mean - std_dev_multiplier * deviation

    return upper, middle, lower


def atr(high: list[float], low: list[float], close: list[float], period: int = 14) -> list[float | None]:
    _validate_period(period)
    _validate_same_length(high, low, close)
    if not high:
        return []

    true_ranges: list[float] = []
    for index in range(len(high)):
        if index == 0:
            true_ranges.append(high[index] - low[index])
        else:
            true_ranges.append(
                max(
                    high[index] - low[index],
                    abs(high[index] - close[index - 1]),
                    abs(low[index] - close[index - 1]),
                )
            )

    result: list[float | None] = [None] * len(high)
    if len(true_ranges) < period:
        return result

    atr_value = sum(true_ranges[:period]) / period
    result[period - 1] = atr_value
    for index in range(period, len(true_ranges)):
        atr_value = ((atr_value * (period - 1)) + true_ranges[index]) / period
        result[index] = atr_value
    return result


def vwap(high: list[float], low: list[float], close: list[float], volume: list[float]) -> list[float | None]:
    _validate_same_length(high, low, close, volume)
    cumulative_price_volume = 0.0
    cumulative_volume = 0.0
    result: list[float | None] = []

    for h, l, c, v in zip(high, low, close, volume, strict=False):
        typical_price = (h + l + c) / 3.0
        cumulative_price_volume += typical_price * v
        cumulative_volume += v
        if cumulative_volume == 0:
            result.append(None)
        else:
            result.append(cumulative_price_volume / cumulative_volume)
    return result


def relative_volume(volume: list[float], period: int = 20) -> list[float | None]:
    _validate_period(period)
    volume_sma = sma(volume, period)
    result: list[float | None] = []
    for vol, average in zip(volume, volume_sma, strict=False):
        if average is None or average == 0:
            result.append(None)
        else:
            result.append(vol / average)
    return result
