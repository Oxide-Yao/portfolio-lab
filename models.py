"""Validated, serializable analysis inputs shared by UI, engine and archives."""
from dataclasses import asdict, dataclass
from datetime import date
import math
import re


class ValidationError(ValueError):
    """A user-facing validation failure."""


def weight_guidance(weights):
    total = sum(weights)
    if any(w < 0 or w > 100 for w in weights):
        return 'Enter each weight between 0% and 100%.'
    difference = abs(total - 100)
    value = f'{difference:.4f}'.rstrip('0').rstrip('.')
    shown = f'{total:.4f}'.rstrip('0').rstrip('.')
    if total > 100:
        return f'Weights total {shown}%. Reduce {value} percentage points to continue.'
    return f'Weights total {shown}%. Allocate the remaining {value} percentage points.'


@dataclass(frozen=True)
class AnalysisConfig:
    symbols: tuple[str, ...] = ("AAPL", "MSFT", "GOOGL")
    weights: tuple[float, ...] = (40.0, 35.0, 25.0)
    capital: float = 100_000.0
    start: str = "2023-01-01"
    end: str = "2025-12-31"
    source: str = "demo"
    short_window: int = 50
    long_window: int = 200
    take_profit: float = 0.15
    stop_loss: float = 0.08
    max_hold_days: int = 60
    fee: float = 0.001

    def validate(self):
        if not isinstance(self.symbols, (tuple, list)) or not 1 <= len(self.symbols) <= 20:
            raise ValidationError("Enter between 1 and 20 US stock symbols.")
        if any(not isinstance(s, str) or not re.fullmatch(r"[A-Z][A-Z0-9.\-^]{0,9}", s) for s in self.symbols):
            raise ValidationError("Use uppercase letters, numbers, dots or hyphens, for example AAPL or BRK-B.")
        if len(set(self.symbols)) != len(self.symbols):
            raise ValidationError("Stock symbols must be unique. Remove repeated symbols, then select Update list.")
        if not isinstance(self.weights, (list, tuple)) or len(self.weights) != len(self.symbols):
            raise ValidationError("Provide one weight for each stock symbol.")
        for value in (*self.weights, self.capital, self.take_profit, self.stop_loss, self.fee):
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValidationError("Capital, weights and strategy parameters must be finite numbers.")
        if any(w < 0 or w > 100 for w in self.weights) or not math.isclose(sum(self.weights), 100, abs_tol=0.001):
            raise ValidationError(weight_guidance(self.weights))
        if not 0 < self.capital <= 1_000_000_000_000:
            raise ValidationError("Initial capital must be positive and no greater than USD 1 trillion.")
        try:
            start, end = date.fromisoformat(self.start), date.fromisoformat(self.end)
        except (ValueError, TypeError):
            raise ValidationError("Start and end dates must use YYYY-MM-DD format.") from None
        if start >= end:
            raise ValidationError("The end date must be later than the start date.")
        if start < date(1990, 1, 1) or end > date(2100, 1, 1) or (end - start).days > 3653:
            raise ValidationError("The analysis period is limited to 10 years, within 1990–2100.")
        if self.source not in ("demo", "yahoo"):
            raise ValidationError("Unsupported data source.")
        if any(type(v) is not int for v in (self.short_window, self.long_window, self.max_hold_days)):
            raise ValidationError("Moving average windows and holding period must be integers.")
        if not 2 <= self.short_window < self.long_window <= 500:
            raise ValidationError("The short window must be smaller than the long window; use 2–500 trading days.")
        if not 1 <= self.max_hold_days <= 1095:
            raise ValidationError("The maximum holding period must be 1–1,095 calendar days.")
        if not 0 < self.take_profit <= 10 or not 0 < self.stop_loss < 1 or not 0 <= self.fee <= 0.05:
            raise ValidationError("Take profit must be above 0 and at most 1,000%; stop loss between 0 and 100%; fee between 0 and 5%.")
        return self

    def to_dict(self):
        result = asdict(self)
        result["symbols"] = list(self.symbols)
        result["weights"] = list(self.weights)
        return result

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) != set(cls.__dataclass_fields__):
            raise ValidationError("Experiment configuration is incomplete or contains unknown fields.")
        values = dict(data)
        if not isinstance(values["symbols"], list) or not isinstance(values["weights"], list):
            raise ValidationError("Symbols and weights must be arrays.")
        values["symbols"] = tuple(values["symbols"])
        values["weights"] = tuple(values["weights"])
        return cls(**values).validate()


def parse_inputs(symbols: str, weights: str, **kwargs) -> AnalysisConfig:
    tickers = tuple(s.strip().upper() for s in symbols.replace("，", ",").split(","))
    try:
        allocation = tuple(float(w.strip()) for w in weights.replace("，", ",").split(","))
    except ValueError:
        raise ValidationError("Enter comma-separated numeric weights, for example 40, 35, 25.") from None
    return AnalysisConfig(symbols=tickers, weights=allocation, **kwargs).validate()
