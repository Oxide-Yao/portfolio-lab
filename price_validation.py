"""Pure price validation shared by the backtest, data adapters and archives.

This module has no Streamlit, charting or network dependencies.
"""
from numbers import Real

import numpy as np
import pandas as pd

from models import AnalysisConfig, ValidationError


def positive_real_values(data, label: str) -> np.ndarray:
    """Reject booleans/complex values instead of silently converting them."""
    raw = np.asarray(data)
    if raw.dtype.kind not in 'iuf':
        if any(isinstance(value, (bool, np.bool_)) or not isinstance(value, Real)
               for value in raw.flat):
            raise ValidationError(f"{label} must contain real numeric values, not booleans or complex values.")
    values = raw.astype(float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValidationError(f"{label} contain missing, infinite or non-positive values.")
    return values


def validate_prices(prices: pd.DataFrame, config: AnalysisConfig) -> pd.DataFrame:
    if not isinstance(prices, pd.DataFrame) or list(prices.columns) != list(config.symbols):
        raise ValidationError("Price columns do not match the portfolio. Failed symbols cannot be ignored.")
    if not isinstance(prices.index, pd.DatetimeIndex) or prices.index.has_duplicates or not prices.index.is_monotonic_increasing:
        raise ValidationError("Price dates must be unique and sorted in ascending order.")
    if prices.index.tz is not None or not prices.index.equals(prices.index.normalize()):
        raise ValidationError("Prices must use daily dates without time zones.")
    if len(prices) > 4500 or prices.empty:
        raise ValidationError("Price data is empty or exceeds the 4,500-row limit.")
    values = positive_real_values(prices.to_numpy(), 'Prices')
    start = pd.Timestamp(config.start)
    visible = prices.loc[config.start:config.end]
    if len(visible) < 2:
        raise ValidationError("Fewer than two common trading days. Extend the date range or check the symbols.")
    if (prices.index < visible.index[0]).sum() < config.long_window:
        raise ValidationError(f"Insufficient shared history: at least {config.long_window} trading days of warm-up are needed. Move the start date forward or reduce the long window.")
    if prices.index[-1] > pd.Timestamp(config.end):
        raise ValidationError("The price snapshot contains dates beyond the analysis end date.")
    if (start - prices.index[0]).days > 1800:
        raise ValidationError("The warm-up period exceeds the supported range.")
    return pd.DataFrame(values, index=prices.index, columns=prices.columns)
