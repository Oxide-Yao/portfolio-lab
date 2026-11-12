from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from conftest import sample
from trading_strategy import analyze, risk_metrics, run_strategy


def test_two_stock_allocation_hand_calculation():
    prices = pd.DataFrame({"AAA": [100, 100, 100, 100, 110, 90], "BBB": [50, 50, 50, 50, 45, 60]},
                          index=pd.bdate_range("2024-01-01", periods=6))
    _, base = sample()
    config = replace(base, symbols=("AAA", "BBB"), weights=(60.0, 40.0),
                     start="2024-01-04", end="2024-01-08", fee=0.0)
    result = analyze(prices, config)["hold"]
    # 600/100 = 6 shares AAA; 400/50 = 8 shares BBB. No rebalancing.
    assert result.trades["shares"].tolist() == [6, 8]
    assert result.equity.tolist() == pytest.approx([1000, 1020, 1020])
    assert result.metrics["total_return"] == pytest.approx(.02)


def test_drawdown_includes_initial_and_daily_volatility():
    curve = pd.Series([90.0, 81.0, 99.0])
    metrics = risk_metrics(curve, 100.0)
    assert metrics["max_drawdown"] == pytest.approx(-.19)
    assert metrics["volatility"] == pytest.approx(np.std([-.1, -.1, 99/81-1], ddof=1) * np.sqrt(252))


def test_both_fees_and_net_profit():
    prices, config = sample()
    result = analyze(prices, config)["golden"]
    buy, sell = result.trades.iloc[0], result.trades.iloc[1]
    shares = 1000 / (12 * 1.01)
    proceeds = shares * 16 * .99
    assert buy["shares"] == pytest.approx(shares)
    assert buy["fee"] == pytest.approx(shares * 12 * .01)
    assert sell["fee"] == pytest.approx(shares * 16 * .01)
    assert sell["pnl"] == pytest.approx(proceeds - 1000)
    assert sell["return"] == pytest.approx(proceeds/1000 - 1)
    assert result.metrics["final_value"] == pytest.approx(proceeds)
    assert result.metrics["fees"] == pytest.approx(buy["fee"] + sell["fee"])
    assert result.metrics["completed_trades"] == 1
    assert result.metrics["open_positions"] == 0


def test_next_close_entry_and_take_profit():
    prices, config = sample()
    result = analyze(prices, config)["golden"]
    buy, sell = result.trades.iloc[0], result.trades.iloc[1]
    assert buy["signal_date"] == "2024-01-05"
    assert buy["date"] == "2024-01-08"
    assert buy["price"] == 12  # Not the signal day's 11.
    assert sell["signal_date"] == "2024-01-09"
    assert sell["date"] == "2024-01-10"
    assert sell["price"] == 16  # Not the trigger day's 15.
    assert sell["reason"] == "Take profit"


def test_stop_loss_gap_exceeds_threshold():
    prices, config = sample([10, 9, 8, 9, 11, 12, 11.04, 9, 9])
    result = analyze(prices, config)["stop"]
    sell = result.trades.iloc[1]
    assert sell["reason"] == "Stop loss"
    assert sell["signal_date"] == "2024-01-09"
    assert sell["date"] == "2024-01-10"
    assert sell["price"] == 9
    assert sell["return"] < -.08
    assert analyze(prices, config)["golden"].metrics["open_positions"] == 1


def test_holding_period_is_calendar_days_and_next_close():
    prices, config = sample([10, 9, 8, 11, 12, 12, 12], max_hold_days=2)
    result = analyze(prices, config)["golden"]
    buy, sell = result.trades.iloc[0], result.trades.iloc[1]
    assert buy["date"] == "2024-01-05"  # Friday
    assert sell["signal_date"] == "2024-01-08"  # Monday, three calendar days later
    assert sell["date"] == "2024-01-09"
    assert sell["holding_days"] == 4


def test_no_signal_preserves_cash():
    prices, config = sample([10] * 9)
    result = analyze(prices, config)["golden"]
    assert result.trades.empty
    assert result.equity.tolist() == [1000] * 6
    assert result.metrics["fees"] == 0
    assert result.metrics["open_positions"] == 0


def test_last_day_entry_signal_cannot_execute():
    prices, config = sample([10, 9, 8, 9, 11])
    result = analyze(prices, config)["golden"]
    assert result.trades.empty
    assert result.metrics["final_value"] == 1000


def test_last_day_exit_signal_stays_open_no_sell_fee():
    prices, config = sample([10, 9, 8, 9, 11, 12, 15])
    result = analyze(prices, config)["golden"]
    assert result.trades["side"].tolist() == ["buy"]
    assert result.metrics["completed_trades"] == 0
    assert result.metrics["open_positions"] == 1
    shares = 1000 / (12 * 1.01)
    assert result.metrics["final_value"] == pytest.approx(shares * 15)
    assert result.metrics["fees"] == pytest.approx(shares * 12 * .01)


def test_pre_start_signal_not_inherited():
    prices, config = sample(start="2024-01-08")
    result = analyze(prices, config)["golden"]
    assert result.trades.empty  # Crossing was before start.


def test_future_prices_do_not_change_past_equity_or_orders():
    prices, config = sample()
    future = prices.copy()
    future.iloc[7:, 0] = [3, 99]
    for kind in ("hold", "golden", "stop"):
        a = analyze(prices, config)[kind]
        b = analyze(future, config)[kind]
        pd.testing.assert_series_equal(a.equity.iloc[:4], b.equity.iloc[:4])
        pd.testing.assert_frame_equal(a.trades[a.trades["date"] < "2024-01-10"].reset_index(drop=True),
                                      b.trades[b.trades["date"] < "2024-01-10"].reset_index(drop=True))


def test_zero_weight_no_orders_and_no_reused_cash():
    prices, base = sample()
    prices["BBB"] = prices["AAA"]
    config = replace(base, symbols=("AAA", "BBB"), weights=(100.0, 0.0))
    result = analyze(prices, config)["golden"]
    assert set(result.trades["symbol"]) == {"AAA"}
    buy, sell = result.trades.iloc[0], result.trades.iloc[1]
    assert buy["gross"] + buy["fee"] == pytest.approx(config.capital)
    assert result.equity.min() > 0
    assert result.metrics["final_value"] == pytest.approx(sell["gross"] - sell["fee"])


def test_hold_first_day_fee_is_drawdown():
    prices, config = sample([10] * 9)
    m = analyze(prices, config)["hold"].metrics
    assert m["max_drawdown"] == pytest.approx(1/1.01-1)


def test_weights_tolerance_still_allocates_exact_capital():
    prices, base = sample([10] * 9)
    prices["BBB"] = prices["AAA"]
    config = replace(base, symbols=("AAA", "BBB"), weights=(50.0001, 50.0), fee=0)
    assert analyze(prices, config)["hold"].equity.iloc[0] == pytest.approx(1000)


def test_reentry_uses_only_cash_from_previous_sale():
    prices, config = sample([10, 9, 8, 9, 11, 12, 15, 16, 8, 7, 12, 13, 15, 16])
    result = analyze(prices, config)["golden"]
    buys = result.trades[result.trades["side"] == "buy"]
    sells = result.trades[result.trades["side"] == "sell"]
    assert len(buys) == 2
    assert buys.iloc[1]["gross"] + buys.iloc[1]["fee"] == pytest.approx(sells.iloc[0]["gross"] - sells.iloc[0]["fee"])


def test_invalid_strategy_rejected():
    prices, config = sample()
    with pytest.raises(ValueError):
        run_strategy(prices, config, "unknown")
