"""Cash-account backtest: signals at close, orders executed next common close."""
from dataclasses import dataclass
import math
from numbers import Real

import numpy as np
import pandas as pd

from price_validation import positive_real_values, validate_prices
from models import AnalysisConfig, ValidationError

STRATEGIES = {"hold": "Buy & hold", "golden": "Golden cross", "stop": "Golden cross + stop"}
COLORS = {"hold": "#8194B0", "golden": "#5277C3", "stop": "#127C68"}
TRADE_COLUMNS = ["symbol", "side", "signal_date", "date", "price", "shares", "gross", "fee", "reason", "pnl", "return", "holding_days"]


@dataclass
class StrategyResult:
    equity: pd.Series
    trades: pd.DataFrame
    metrics: dict
    cash: pd.DataFrame | None = None
    holdings: pd.DataFrame | None = None


def risk_metrics(equity: pd.Series, initial: float) -> dict:
    if isinstance(initial, (bool, np.bool_)) or not isinstance(initial, Real) or not math.isfinite(initial) or initial <= 0:
        raise ValidationError("Initial capital must be a finite positive real number.")
    if not isinstance(equity, pd.Series) or equity.empty:
        raise ValidationError("Equity must be a non-empty series.")
    values = np.r_[initial, positive_real_values(equity.to_numpy(), 'Equity values')]
    changes = values[1:] / values[:-1] - 1
    drawdown = values / np.maximum.accumulate(values) - 1
    return {
        "final_value": float(values[-1]),
        "total_return": float(values[-1] / initial - 1),
        "max_drawdown": float(drawdown.min()),
        "volatility": float(np.std(changes, ddof=1) * np.sqrt(252)) if len(changes) > 1 else 0.0,
    }


def run_strategy(prices: pd.DataFrame, config: AnalysisConfig, kind: str) -> StrategyResult:
    """Validate the standalone entry point just as strictly as analyze()."""
    if kind not in STRATEGIES:
        raise ValueError("Unknown strategy")
    config.validate()
    return _run_validated_strategy(validate_prices(prices, config), config, kind)


def _run_validated_strategy(prices: pd.DataFrame, config: AnalysisConfig, kind: str,
                            entries=None, exits=None) -> StrategyResult:
    displayed = prices.loc[config.start:config.end]
    portfolio = pd.Series(0.0, index=displayed.index, name=kind)
    events = []
    cash_history = pd.DataFrame(0.0, index=displayed.index, columns=config.symbols)
    holdings = cash_history.copy()
    open_count = 0
    # Normalize the tiny tolerated weight error so that allocated cash equals capital.
    allocations = np.asarray(config.weights, dtype=float) / sum(config.weights) * config.capital
    for symbol, allocation in zip(config.symbols, allocations):
        full = prices[symbol]
        short = full.rolling(config.short_window, min_periods=config.short_window).mean()
        long = full.rolling(config.long_window, min_periods=config.long_window).mean()
        crossing = ((short > long) & (short.shift(1) <= long.shift(1))).reindex(displayed.index)
        cash, shares, entry, entry_cost = float(allocation), 0.0, 0.0, 0.0
        entry_date = None
        pending = None
        for i, (day, price) in enumerate(displayed[symbol].items()):
            price = float(price)
            if kind == "hold" and i == 0 and cash > 0:
                pending = ("buy", day, "Initial allocation")
            if pending is not None:
                side, signal_day, reason = pending
                if side == "buy" and cash > 0 and shares == 0:
                    shares = cash / (price * (1 + config.fee))
                    gross = shares * price
                    fee = gross * config.fee
                    entry, entry_date, entry_cost = price, day, cash
                    cash = 0.0
                    events.append(dict(symbol=symbol, side="buy", signal_date=signal_day.date().isoformat(),
                                       date=day.date().isoformat(), price=price, shares=shares, gross=gross,
                                       fee=fee, reason=reason, pnl=None, **{"return": None}, holding_days=None))
                elif side == "sell" and shares > 0:
                    gross = shares * price
                    fee = gross * config.fee
                    cash = gross - fee
                    pnl = cash - entry_cost
                    events.append(dict(symbol=symbol, side="sell", signal_date=signal_day.date().isoformat(),
                                       date=day.date().isoformat(), price=price, shares=shares, gross=gross,
                                       fee=fee, reason=reason, pnl=pnl, **{"return": pnl / entry_cost},
                                       holding_days=(day - entry_date).days))
                    shares = 0.0
                pending = None
            portfolio.at[day] += cash + shares * price
            cash_history.at[day, symbol] = cash
            holdings.at[day, symbol] = shares
            if entries is not None:
                # Explicit crossover strategy: exits override entries. Existing
                # take-profit/stop/holding rules only apply to the original kinds.
                if shares > 0 and bool(exits.at[day, symbol]):
                    pending = ("sell", day, f"{kind} downward crossover")
                elif shares == 0 and cash > 0 and bool(entries.at[day, symbol]):
                    pending = ("buy", day, f"{kind} upward crossover")
            elif kind != "hold":
                if shares > 0:
                    gain = price / entry - 1
                    reason = None
                    if kind == "stop" and (gain <= -config.stop_loss or math.isclose(gain, -config.stop_loss, abs_tol=1e-12)):
                        reason = "Stop loss"
                    elif gain >= config.take_profit or math.isclose(gain, config.take_profit, abs_tol=1e-12):
                        reason = "Take profit"
                    elif (day - entry_date).days >= config.max_hold_days:
                        reason = "Holding limit"
                    if reason:
                        pending = ("sell", day, reason)
                elif bool(crossing.at[day]) and cash > 0:
                    pending = ("buy", day, "Golden cross signal")
            # An order generated on the last date remains unexecuted by design.
        open_count += int(shares > 0)
    trades = pd.DataFrame(events, columns=TRADE_COLUMNS)
    metrics = risk_metrics(portfolio, config.capital)
    metrics.update(completed_trades=int((trades["side"] == "sell").sum()),
                   open_positions=open_count, fees=float(trades["fee"].sum()))
    return StrategyResult(portfolio, trades, metrics, cash_history, holdings)


def run_signal_strategy(prices, config, entries, exits, name="MACD"):
    """Pure execution of boolean close signals on the next common close.

    Unallocated/non-selected sleeves stay in cash. No shorting, forced final
    liquidation or cross-sleeve cash reuse. Signal generation is separate.
    """
    if not isinstance(name, str) or not name.strip() or name in STRATEGIES:
        raise ValidationError("Use a distinct non-empty name for an explicit signal strategy.")
    config.validate()
    prices = validate_prices(prices, config)
    dates = prices.loc[config.start:config.end].index
    for signals in (entries, exits):
        if (not isinstance(signals, pd.DataFrame) or not signals.index.equals(dates)
                or list(signals.columns) != list(config.symbols)
                or any(dtype != bool for dtype in signals.dtypes)):
            raise ValidationError("Signals must be complete boolean frames matching the analysis dates and symbols.")
    if (entries & exits).any().any():
        raise ValidationError("Entry and exit cannot both occur on the same date.")
    return _run_validated_strategy(prices, config, name, entries, exits)


def analyze(prices: pd.DataFrame, config: AnalysisConfig) -> dict[str, StrategyResult]:
    config.validate()
    prices = validate_prices(prices, config)
    return {key: _run_validated_strategy(prices, config, key) for key in STRATEGIES}
