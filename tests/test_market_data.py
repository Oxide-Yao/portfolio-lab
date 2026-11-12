from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
import yfinance as yf

from conftest import sample
from market_data import demo_prices, load_prices, validate_prices, yahoo_prices
from models import AnalysisConfig, ValidationError, parse_inputs


def test_demo_reproducible_independent_of_symbol_order():
    a = demo_prices(("AAPL", "MSFT"))
    b = demo_prices(("MSFT", "AAPL"))
    pd.testing.assert_series_equal(a["AAPL"], b["AAPL"])
    assert (a > 0).all().all()
    prices, _ = load_prices(AnalysisConfig())
    assert (prices.index < pd.Timestamp("2023-01-01")).sum() >= 200


@pytest.mark.parametrize("symbols,weights", [("AAPL,AAPL", "50,50"), ("AAPL,MSFT", "60,30"),
    ("AAPL,MSFT", "-10,110"), ("AAPL", "nan"), ("AAPL", "inf"), ("", "100"),
    ("<script>", "100"), ("AAPL,MSFT", "100"), (",".join(f"A{i}" for i in range(21)), ",".join([str(100/21)]*21))])
def test_invalid_symbols_and_weights(symbols, weights):
    with pytest.raises(ValidationError):
        parse_inputs(symbols, weights)


@pytest.mark.parametrize("change", [{"capital": 0}, {"capital": -1}, {"short_window": 200},
    {"start": "2026-01-01", "end": "2025-01-01"}, {"fee": .06}, {"stop_loss": 1},
    {"long_window": True}, {"start": "bad date"}, {"source": "unknown"}])
def test_invalid_config(change):
    with pytest.raises(ValidationError):
        replace(AnalysisConfig(), **change).validate()


def test_chinese_commas_and_case_normalization():
    config = parse_inputs("aapl，msft", "60，40")
    assert config.symbols == ("AAPL", "MSFT")


def test_no_common_dates_and_insufficient_history():
    prices, config = sample()
    with pytest.raises(ValidationError, match="Fewer than two"):
        validate_prices(prices, replace(config, start="2024-01-11", end="2024-01-12"))
    with pytest.raises(ValidationError, match="warm-up"):
        validate_prices(prices, replace(config, long_window=5))
    bad = prices.copy()
    bad.iloc[0, 0] = np.nan
    with pytest.raises(ValidationError, match="missing"):
        validate_prices(bad, config)


def test_demo_outside_supported_dates():
    with pytest.raises(ValidationError, match="Demo prices cover"):
        load_prices(replace(AnalysisConfig(), end="2026-12-01"))


def test_yahoo_alignment_no_fill_and_adjusted_request(monkeypatch):
    yahoo_prices.clear()
    calls = []
    def download(symbol, **kwargs):
        calls.append(kwargs)
        values = [10, 11, 12] if symbol == "AAA" else [20, np.nan, 22]
        return pd.DataFrame({"Close": values}, index=pd.bdate_range("2024-01-01", periods=3))
    monkeypatch.setattr(yf, "download", download)
    frame, notes = yahoo_prices(("AAA", "BBB"), "2024-01-01", "2024-01-05")
    assert len(frame) == 2
    assert frame.index.tolist() == [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-03")]
    assert calls[0]["auto_adjust"] is True
    assert "1 incomplete" in notes[0]
    yahoo_prices.clear()


def test_yahoo_failure_never_silently_ignored(monkeypatch):
    yahoo_prices.clear()
    monkeypatch.setattr(yf, "download", lambda *args, **kwargs: pd.DataFrame())
    with pytest.raises(ValidationError, match="AAA.*BBB"):
        yahoo_prices(("AAA", "BBB"), "2024-01-01", "2024-01-05")
    yahoo_prices.clear()


def test_yahoo_excludes_current_day_and_end_is_inclusive(monkeypatch):
    import market_data
    prices, config = sample()
    captured = {}
    def fake(symbols, start, end):
        captured.update(start=start, end=end)
        return prices, []
    monkeypatch.setattr(market_data, "last_completed_us_date", lambda: "2024-01-11")
    monkeypatch.setattr(market_data, "yahoo_prices", fake)
    frame, notes = load_prices(replace(config, source="yahoo", end="2024-01-12"))
    assert captured["end"] == "2024-01-12"  # Yahoo exclusive bound for Jan 11.
    assert frame.index[-1] == pd.Timestamp("2024-01-11")
    assert notes
