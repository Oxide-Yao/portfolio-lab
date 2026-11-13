"""Daily analytics without UI/network imports. Returns are decimal fractions.

EMA uses an SMA seed; RSI uses Wilder's SMA seed then 1/n smoothing. Missing
history is NaN, never zero. All recurrences use only the current/past close.
"""
from dataclasses import asdict, dataclass
import math
import re

import numpy as np
import pandas as pd

from models import ValidationError
from price_validation import positive_real_values

CALCULATION_VERSION = "core-features-1"


def symbols_checked(symbols):
    if not isinstance(symbols, (tuple, list)) or not 1 <= len(symbols) <= 20:
        raise ValidationError("Select 1–20 unique US symbols.")
    if any(not isinstance(s, str) or not re.fullmatch(r"[A-Z][A-Z0-9.\-^]{0,9}", s) for s in symbols):
        raise ValidationError("Use normalized uppercase US symbols.")
    if len(set(symbols)) != len(symbols):
        raise ValidationError("Duplicate stock symbols.")
    return tuple(symbols)


def daily_series(values, label="Prices", positive=True):
    if not isinstance(values, pd.Series) or values.empty:
        raise ValidationError(f"{label} must be a non-empty daily series.")
    idx = values.index
    if (not isinstance(idx, pd.DatetimeIndex) or idx.hasnans or idx.has_duplicates
            or not idx.is_monotonic_increasing or idx.tz is not None
            or not idx.equals(idx.normalize())):
        raise ValidationError("Daily dates must be sorted, unique, timezone-free and complete.")
    if positive:
        arr = positive_real_values(values.to_numpy(), label)
    else:
        arr = values.to_numpy()
        if arr.dtype.kind not in 'iuf' or not np.isfinite(arr).all():
            raise ValidationError(f"{label} must contain finite real values.")
        arr = arr.astype(float)
    return pd.Series(arr, index=idx, name=values.name)


def clean_price_records(records, symbols, *, missing="reject"):
    """Long Date/Symbol/Price records -> sorted wide frame + audit metadata.

    Symbols are explicitly normalized. Duplicate normalized symbol/date pairs
    are rejected, including identical duplicates. Missing cells may only be
    dropped by explicitly requesting common_dates; prices are never filled.
    """
    symbols = symbols_checked(symbols)
    if missing not in ("reject", "common_dates"):
        raise ValidationError("Unknown missing-price policy.")
    if not isinstance(records, pd.DataFrame) or not {"Date", "Symbol", "Price"}.issubset(records.columns):
        raise ValidationError("Data requires Date, Symbol and Price columns.")
    data = records.loc[:, ["Date", "Symbol", "Price"]].copy()
    if data.empty or len(data) > 100_000:
        raise ValidationError("Price records must contain 1–100,000 rows.")
    if any(not isinstance(s, str) for s in data.Symbol):
        raise ValidationError("Missing or invalid stock symbol.")
    data["Symbol"] = data.Symbol.str.strip().str.upper()
    symbols_checked(list(data.Symbol.unique()))
    if set(data.Symbol) != set(symbols):
        raise ValidationError("Price symbols must exactly match the requested symbols.")
    try:
        stamps = [pd.Timestamp(d) for d in data.Date]
        if any(pd.isna(d) or d != d.normalize() for d in stamps):
            raise ValueError
        data["Date"] = [pd.Timestamp(d.date()) for d in stamps]
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValidationError("Use valid daily dates; local trading dates are retained.") from exc
    if data.duplicated(["Date", "Symbol"]).any():
        raise ValidationError("Duplicate stock/date records; resolve them before analysis.")
    present = data.Price.notna()
    positive_real_values(data.loc[present, "Price"].to_numpy(), "Prices")
    wide = data.pivot(index="Date", columns="Symbol", values="Price").reindex(columns=symbols).sort_index()
    incomplete = wide.isna().any(axis=1)
    if incomplete.any() and missing == "reject":
        raise ValidationError("Missing prices; provide complete data or explicitly select common_dates.")
    result = wide.loc[~incomplete].astype(float)
    if result.empty:
        raise ValidationError("No complete common trading dates.")
    return result, {"removed_dates": [d.date().isoformat() for d in wide.index[incomplete]],
                    "missing_policy": missing, "date_basis": "exchange-local daily date",
                    "price_fill": "none", "symbols": list(symbols)}


def read_price_csv(path, symbols, *, missing="reject"):
    """Read the explicit Date,Symbol,Price CSV format; no guessed price basis."""
    try:
        records = pd.read_csv(path, dtype={"Date": str, "Symbol": str})
    except (OSError, ValueError) as exc:
        raise ValidationError("Cannot read price CSV.") from exc
    return clean_price_records(records, symbols, missing=missing)


def window_checked(window):
    if type(window) is not int or not 1 <= window <= 500:
        raise ValidationError("Indicator periods must be integers between 1 and 500 trading days.")


def sma(close, window):
    window_checked(window)
    return daily_series(close).rolling(window, min_periods=window).mean()


def _ema_seeded(values, period):
    out = pd.Series(np.nan, index=values.index, dtype=float)
    valid = values.dropna()
    if len(valid) < period:
        return out
    # Internal callers only pass a contiguous suffix after warm-up.
    seed_index = valid.index[period - 1]
    previous = float(valid.iloc[:period].mean())
    out.at[seed_index] = previous
    alpha = 2 / (period + 1)
    for day, value in valid.iloc[period:].items():
        previous += alpha * (value - previous)
        out.at[day] = previous
    return out


def ema(close, window):
    window_checked(window)
    return _ema_seeded(daily_series(close), window)


def rsi(close, window=14):
    window_checked(window)
    close = daily_series(close)
    result = pd.Series(np.nan, index=close.index, name="rsi")
    if len(close) <= window:
        return result
    changes = close.diff()
    gains, losses = changes.clip(lower=0), -changes.clip(upper=0)
    gain, loss = float(gains.iloc[1:window+1].mean()), float(losses.iloc[1:window+1].mean())
    for i in range(window, len(close)):
        if i > window:
            gain = (gain * (window - 1) + gains.iloc[i]) / window
            loss = (loss * (window - 1) + losses.iloc[i]) / window
        result.iloc[i] = 50.0 if gain == loss == 0 else (100.0 if loss == 0 else 100 - 100 / (1 + gain / loss))
    return result


@dataclass(frozen=True)
class MACDParameters:
    fast: int = 12
    slow: int = 26
    signal: int = 9

    def validate(self):
        for n in (self.fast, self.slow, self.signal):
            window_checked(n)
        if self.fast >= self.slow:
            raise ValidationError("MACD fast period must be smaller than slow period.")
        return self


def crosses(left, right):
    if not left.index.equals(right.index):
        raise ValidationError("Crossing series must use identical dates.")
    return pd.DataFrame({"entry": (left > right) & (left.shift(1) <= right.shift(1)),
                         "exit": (left < right) & (left.shift(1) >= right.shift(1))})


def macd(close, parameters=MACDParameters()):
    parameters.validate()
    close = daily_series(close)
    line = _ema_seeded(close, parameters.fast) - _ema_seeded(close, parameters.slow)
    signal = _ema_seeded(line, parameters.signal)
    return pd.DataFrame({"macd": line, "signal": signal, "histogram": line - signal}).join(crosses(line, signal))


def stock_insights(close, *, short=50, long=200, rsi_period=14, macd_parameters=MACDParameters()):
    if short >= long:
        raise ValidationError("Short SMA must be smaller than long SMA.")
    close = daily_series(close)
    frame = pd.DataFrame({"close": close, "short_sma": sma(close, short), "long_sma": sma(close, long),
                          "rsi": rsi(close, rsi_period)})
    frame = frame.join(macd(close, macd_parameters).add_prefix("macd_"))
    frame = frame.join(crosses(frame.short_sma, frame.long_sma).add_prefix("sma_"))
    last = frame.iloc[-1]
    states = {
        "sma": "Insufficient history" if pd.isna(last.long_sma) else
            ("Short average above long average" if last.short_sma > last.long_sma else "Short average at or below long average"),
        "rsi": "Insufficient history" if pd.isna(last.rsi) else
            ("Recent gains are strong; above 70 does not predict an immediate decline." if last.rsi > 70 else
             "Recent losses are strong; below 30 does not predict an immediate recovery." if last.rsi < 30 else "RSI is between 30 and 70."),
        "macd": "Insufficient history" if pd.isna(last.macd_signal) else
            ("MACD above signal line" if last.macd_macd > last.macd_signal else "MACD at or below signal line"),
    }
    recent = {}
    for column in ("sma_entry", "sma_exit", "macd_entry", "macd_exit"):
        dates = frame.index[frame[column]]
        recent[column] = dates[-1].date().isoformat() if len(dates) else None
    return {"data": frame, "states": states, "recent_events": recent,
            "parameters": {"short": short, "long": long, "rsi": rsi_period, "macd": asdict(macd_parameters)},
            "as_of": close.index[-1].date().isoformat(), "calculation_version": CALCULATION_VERSION,
            "convention": "Trading days; SMA-seeded EMA; Wilder RSI; flat RSI=50; states/events are not executions."}


@dataclass(frozen=True)
class PriceBasis:
    source: str  # demo or yahoo (never silently mixed)
    return_basis: str  # adjusted_close or price_return
    currency: str = "USD"
    environment: str = "default"  # synthetic seed/version or historical snapshot family

    def validate(self):
        if self.source not in ("demo", "yahoo") or self.return_basis not in ("adjusted_close", "price_return") or self.currency != "USD":
            raise ValidationError("Specify supported source, USD and an explicit return basis.")
        if not isinstance(self.environment, str) or not self.environment:
            raise ValidationError("Specify the data environment/version.")
        return self


def benchmark_comparison(equity, benchmark, *, portfolio_basis, benchmark_basis, benchmark_symbol="SPY"):
    """Exact coverage, no truncation or filling. First observed close = 100.

    Normalized return excludes fees already embedded in the first equity point.
    The engine's total_return remains the full experiment return from capital.
    Benchmark is frictionless; adjusted close includes vendor adjustments (not
    separately credited dividends). Original strategy results are never mutated.
    """
    equity, benchmark = daily_series(equity, "Equity"), daily_series(benchmark, "Benchmark")
    portfolio_basis.validate(); benchmark_basis.validate()
    symbols_checked([benchmark_symbol])
    if portfolio_basis != benchmark_basis:
        raise ValidationError("Portfolio and benchmark must use the same source, currency, return basis and environment.")
    if len(equity) < 2:
        raise ValidationError("At least two equity dates are required for market comparison.")
    if not equity.index.isin(benchmark.index).all():
        raise ValidationError("Benchmark has missing portfolio dates. Retry without changing the original backtest interval.")
    aligned = benchmark.loc[equity.index]
    normalized = pd.DataFrame({"portfolio": equity / equity.iloc[0] * 100,
                               "benchmark": aligned / aligned.iloc[0] * 100})
    a, b = normalized.iloc[-1] / 100 - 1
    return {"curves": normalized, "portfolio_return": float(a), "benchmark_return": float(b),
            "difference_percentage_points": float((a - b) * 100),
            "benchmark": benchmark_symbol, "basis": asdict(portfolio_basis), "benchmark_fee": 0.0,
            "start": equity.index[0].date().isoformat(), "end": equity.index[-1].date().isoformat(),
            "return_note": "First observed equity/price = 100; excludes initial-date entry cost from normalized return. Portfolio already net of strategy fees; benchmark frictionless.",
            "csv": normalized.to_csv(index_label="Date")}


def historical_beta(equity, benchmark):
    equity, benchmark = daily_series(equity, "Equity"), daily_series(benchmark, "Benchmark")
    if not equity.index.equals(benchmark.index) or len(equity) < 3:
        raise ValidationError("Beta requires identical daily dates and at least two paired returns.")
    p, b = equity.pct_change(fill_method=None).iloc[1:], benchmark.pct_change(fill_method=None).iloc[1:]
    variance = float(b.var(ddof=1))
    if variance <= 1e-18:
        raise ValidationError("Benchmark variance is zero or too small to estimate beta.")
    return {"beta": float(p.cov(b) / variance), "observations": len(b), "frequency": "daily",
            "start": b.index[0].date().isoformat(), "end": b.index[-1].date().isoformat()}


def capm_required_return(beta, risk_free_rate, market_risk_premium):
    if any(type(x) not in (int, float) or not math.isfinite(x) for x in (beta, risk_free_rate, market_risk_premium)):
        raise ValidationError("CAPM inputs must be finite numbers, with annual rates in decimal fractions.")
    return {"required_return": risk_free_rate + beta * market_risk_premium,
            "beta": beta, "risk_free_rate": risk_free_rate, "market_risk_premium": market_risk_premium,
            "label": "CAPM required return", "rate_unit": "annual decimal", "assumptions": "User supplied; not a realized return or valuation verdict."}


def fundamental_value(name, value, *, period, currency, source, updated_at, basis, definition):
    """Normalize a display-only observation; deliberately not a backtest input.

    Provider adapters must supply period/basis/definition instead of guessing
    whether Yahoo values are percentages, TTM or forecasts. No weighted P/E.
    """
    required = (name, period, currency, source, updated_at, basis, definition)
    if any(not isinstance(x, str) or not x.strip() for x in required):
        raise ValidationError("Fundamentals require name, period, currency/unit, source, update time, basis and definition.")
    if value is not None and (type(value) not in (float, int) or not math.isfinite(value)):
        raise ValidationError("Fundamental value must be finite or None.")
    status = "Not available" if value is None else "Available"
    if name == "P/E" and value is not None and value <= 0:
        value, status = None, "Not applicable: non-positive earnings or invalid P/E."
    return dict(name=name, value=value, status=status, period=period, currency=currency, source=source,
                updated_at=updated_at, basis=basis, definition=definition, usage="Display only; not point-in-time backtest data.")
