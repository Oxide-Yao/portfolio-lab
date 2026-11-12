"""Offline reproducible demo and explicitly requested Yahoo adjusted closes."""
from datetime import date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import streamlit as st

from models import AnalysisConfig, ValidationError
from price_validation import validate_prices

DEMO_START = "2018-01-01"
DEMO_END = "2026-10-30"



@st.cache_data(show_spinner=False, max_entries=32)
def demo_prices(symbols: tuple[str, ...]) -> pd.DataFrame:
    dates = pd.bdate_range(DEMO_START, DEMO_END)
    t = np.arange(len(dates))
    common = np.random.default_rng(4145).normal(0, 0.006, len(dates))
    data = {}
    for symbol in symbols:
        seed = int.from_bytes(sha256(symbol.encode()).digest()[:4], "big")
        rng = np.random.default_rng(seed)
        phase = (seed % 628) / 100
        cycle = 0.0026 * np.sin(t / 46 + phase) + 0.0010 * np.sin(t / 137 + phase)
        returns = 0.00035 + cycle + common + rng.normal(0, 0.009, len(dates))
        # Occasional reproducible shocks make cash periods and exits observable.
        returns[(t + seed % 167) % 251 == 0] -= 0.065
        data[symbol] = (60 + seed % 160) * np.exp(np.cumsum(returns))
    return pd.DataFrame(data, index=dates)


def last_completed_us_date() -> str:
    # Conservatively exclude the whole current New York date, including after close.
    return (datetime.now(ZoneInfo("America/New_York")).date() - timedelta(days=1)).isoformat()


@st.cache_data(ttl=3600, max_entries=24, show_spinner=False)
def yahoo_prices(symbols: tuple[str, ...], start: str, end: str) -> tuple[pd.DataFrame, list[str]]:
    import yfinance as yf

    cache_path = Path("data/yfinance-cache")
    cache_path.mkdir(parents=True, exist_ok=True)
    yf.set_tz_cache_location(str(cache_path))
    data, failures = {}, []
    for symbol in symbols:
        try:
            frame = yf.download(symbol, start=start, end=end, auto_adjust=True,
                                progress=False, threads=False, timeout=15)
            if frame.empty or "Close" not in frame:
                failures.append(symbol)
                continue
            close = frame["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
            close.index = pd.DatetimeIndex(close.index).tz_localize(None).normalize()
            data[symbol] = close.rename(symbol)
        except Exception:
            failures.append(symbol)
    if failures:
        raise ValidationError("Yahoo download failed for: " + "、".join(failures) + ". Check symbols and connectivity, then retry later. Use Demo mode if rate limited. No failed symbols were omitted or replaced.")
    raw = pd.concat([data[s] for s in symbols], axis=1).sort_index()
    aligned = raw.dropna(how="any")
    notes = []
    dropped = len(raw) - len(aligned)
    if dropped:
        notes.append(f"Removed {dropped} incomplete dates. Only common trading days are used; no forward fill or future-price backfill.")
    return aligned, notes


def load_prices(config: AnalysisConfig) -> tuple[pd.DataFrame, list[str]]:
    config.validate()
    notes = []
    warm_start = (date.fromisoformat(config.start) - timedelta(days=config.long_window * 2 + 60)).isoformat()
    if config.source == "demo":
        if config.start < DEMO_START or config.end > DEMO_END:
            raise ValidationError(f"Demo prices cover {DEMO_START} to {DEMO_END}. Allow enough history before the start date for moving average warm-up.")
        prices = demo_prices(config.symbols).loc[warm_start:config.end].copy()
        notes.append("Synthetic demo data, not real stock history. Trading dates approximate weekdays and do not model US market holidays.")
    else:
        end = min(config.end, last_completed_us_date())
        if end < config.start:
            raise ValidationError("No completed US daily bars are available in this period. Select an earlier start date.")
        # Yahoo's end is exclusive; the user's end is inclusive.
        exclusive_end = (date.fromisoformat(end) + timedelta(days=1)).isoformat()
        prices, notes = yahoo_prices(config.symbols, warm_start, exclusive_end)
        if end != config.end:
            notes.append(f"To exclude unfinished daily bars, prices end on {end} (New York) or the previous available trading day.")
    prices = validate_prices(prices, config)
    effective = prices.loc[config.start:config.end]
    if (effective.index[0] - pd.Timestamp(config.start)).days > 7 or (pd.Timestamp(config.end) - effective.index[-1]).days > 7:
        notes.append("The actual common trading range differs materially from the requested period. Review the effective dates above.")
    return prices, notes
