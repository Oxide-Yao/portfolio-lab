from dataclasses import replace
import json

import numpy as np
import pandas as pd
import pytest

from analytics_core import (MACDParameters, PriceBasis, benchmark_comparison, capm_required_return,
                            clean_price_records, ema, fundamental_value, historical_beta, macd, rsi, sma, stock_insights)
from feature_backtest import compare_macd_parameters, export_feature_experiment, restore_feature_experiment, run_macd
from models import ValidationError
from trading_strategy import run_signal_strategy, run_strategy
from conftest import sample


def series(values):
    return pd.Series(values, index=pd.bdate_range('2024-01-01', periods=len(values)), dtype=float)


def test_clean_records_sort_normalize_and_reject_duplicates():
    rows = pd.DataFrame({'Date': ['2024-01-02', '2024-01-01'], 'Symbol': [' aaa ', 'AAA'], 'Price': [12, 10]})
    clean, audit = clean_price_records(rows, ('AAA',))
    assert clean.AAA.tolist() == [10, 12]
    assert audit['price_fill'] == 'none'
    with pytest.raises(ValidationError, match='Duplicate'):
        clean_price_records(pd.concat([rows, rows.iloc[:1]]), ('AAA',))
    with pytest.raises(ValidationError, match='match'):
        clean_price_records(rows, ('BBB',))


def test_missing_policy_requires_explicit_choice():
    rows = pd.DataFrame({'Date': ['2024-01-01', '2024-01-02', '2024-01-02'],
                         'Symbol': ['AAA', 'AAA', 'BBB'], 'Price': [10, 12, 20]})
    with pytest.raises(ValidationError, match='Missing'):
        clean_price_records(rows, ('AAA', 'BBB'))
    cleaned, audit = clean_price_records(rows, ('AAA', 'BBB'), missing='common_dates')
    assert len(cleaned) == 1
    assert audit['removed_dates'] == ['2024-01-01']
    rows.loc[0, 'Price'] = -1
    with pytest.raises(ValidationError):
        clean_price_records(rows, ('AAA', 'BBB'), missing='common_dates')


def test_hand_sma_ema_rsi_and_warmup():
    close = series([1, 2, 3, 4])
    assert sma(close, 3).iloc[-1] == 3
    assert ema(close, 3).iloc[2:].tolist() == [2, 3]
    assert ema(close, 3).iloc[:2].isna().all()
    # Changes +1, -1 seed average gain/loss .5/.5 -> RSI50;
    # next change +2 -> Wilder gain1.25/loss.25 -> RSI83 1/3.
    actual = rsi(series([10, 11, 10, 12]), 2)
    assert actual.iloc[:2].isna().all()
    assert actual.iloc[2] == 50
    assert actual.iloc[3] == pytest.approx(100 - 100 / 6)
    assert rsi(series([10, 10, 10]), 2).iloc[-1] == 50
    assert rsi(close, 2).iloc[-1] == 100


def test_hand_macd_and_prefix_invariance():
    close = series([1, 2, 3, 4, 3, 2, 4, 6, 3, 2])
    params = MACDParameters(2, 3, 2)
    result = macd(close, params)
    # EMA2 [1.5,2.5,3.5,19/6]; EMA3 [2,3,3];
    # line .5,.5,1/6; signal seed .5 then5/18.
    assert result.macd.iloc[2:5].tolist() == pytest.approx([.5, .5, 1/6])
    assert result.signal.iloc[4] == pytest.approx(5/18)
    assert bool(result.exit.iloc[4])
    for cut in range(3, len(close)):
        pd.testing.assert_frame_equal(macd(close.iloc[:cut], params), result.iloc[:cut])
        pd.testing.assert_series_equal(rsi(close.iloc[:cut], 2), rsi(close, 2).iloc[:cut])
    insights = stock_insights(close.iloc[:2], short=2, long=3, macd_parameters=params)
    assert insights['states']['macd'] == 'Insufficient history'


def test_benchmark_difference_beta_and_basis_guards():
    basis = PriceBasis('demo', 'price_return', environment='seed4145')
    comparison = benchmark_comparison(series([100, 105, 112]), series([100, 104, 109]),
                                     portfolio_basis=basis, benchmark_basis=basis)
    assert comparison['difference_percentage_points'] == pytest.approx(3)
    assert comparison['curves'].iloc[0].tolist() == [100, 100]
    # Market returns +10%,-10%; portfolio +20%,-20% => beta2.
    assert historical_beta(series([100, 120, 96]), series([100, 110, 99]))['beta'] == pytest.approx(2)
    assert capm_required_return(2, .03, .05)['required_return'] == pytest.approx(.13)
    with pytest.raises(ValidationError, match='variance'):
        historical_beta(series([100, 110, 120]), series([100, 100, 100]))
    with pytest.raises(ValidationError, match='missing'):
        benchmark_comparison(series([100, 105, 112]), series([100, 104]), portfolio_basis=basis, benchmark_basis=basis)
    with pytest.raises(ValidationError, match='same source'):
        benchmark_comparison(series([100, 105, 112]), series([100, 104, 109]), portfolio_basis=basis,
                             benchmark_basis=PriceBasis('yahoo', 'adjusted_close'))


def test_display_only_fundamental_missing_and_negative_earnings():
    metadata = dict(period='2024FY', currency='ratio', source='manual fixture', updated_at='2025-01-01',
                    basis='actual', definition='price / trailing twelve month earnings per share')
    assert fundamental_value('P/E', None, **metadata)['status'] == 'Not available'
    assert fundamental_value('P/E', -2, **metadata)['value'] is None


def test_signal_execution_next_close_and_cash_conservation():
    prices, config = sample()
    dates = prices.loc[config.start:config.end].index
    entries = pd.DataFrame(False, index=dates, columns=config.symbols)
    exits = entries.copy()
    entries.iloc[1] = True  # Jan5 -> Jan8 at12
    exits.iloc[3] = True    # Jan9 -> Jan10 at16
    entries.iloc[-1] = True # last-date signal cannot execute
    result = run_signal_strategy(prices, config, entries, exits)
    assert result.trades.date.tolist() == ['2024-01-08', '2024-01-10']
    shares = 1000 / (12 * 1.01)
    final = shares * 16 * .99
    assert result.metrics['final_value'] == pytest.approx(final)
    assert result.metrics['fees'] == pytest.approx(shares * 12 * .01 + shares * 16 * .01)
    pd.testing.assert_series_equal((result.cash + result.holdings * prices.loc[dates]).sum(axis=1), result.equity, check_names=False)
    assert (result.cash >= 0).all().all() and (result.holdings >= 0).all().all()
    # Changing later prices cannot alter earlier executions/equity.
    future = prices.copy(); future.iloc[-1] *= 2
    again = run_signal_strategy(future, config, entries, exits)
    pd.testing.assert_series_equal(result.equity.iloc[:-1], again.equity.iloc[:-1])


def macd_fixture():
    prices, config = sample([10, 9, 8, 9, 11, 12, 15, 13, 10, 9, 12, 15, 13, 10, 9, 12])
    prices['BBB'] = 20
    return prices, replace(config, symbols=('AAA', 'BBB'), weights=(60., 40.), start=prices.index[5].date().isoformat())


def test_macd_scope_and_parameters_share_data_and_conditions():
    prices, config = macd_fixture()
    result = run_macd(prices, config, MACDParameters(2, 3, 2), scope=['AAA'])
    assert result.holdings.BBB.eq(0).all() and result.cash.BBB.eq(400).all()
    assert set(result.trades.symbol) == {'AAA'}
    assert (pd.to_datetime(result.trades.date) > pd.to_datetime(result.trades.signal_date)).all()
    comparison = compare_macd_parameters(prices, config, [MACDParameters(2, 3, 2), MACDParameters(2, 4, 2)],
                                         selection_note='Small predeclared educational candidates.', scope=(s for s in ['AAA']))
    assert comparison['scope'] == ['AAA']
    assert len(comparison['results']) == 5
    for result in comparison['results'].values():
        assert result.equity.index.equals(comparison['results']['hold'].equity.index)
    assert 'no best-parameter' in comparison['selection_method']
    with pytest.raises(ValidationError, match='history'):
        run_macd(prices, config)


def test_feature_archive_replays_and_rejects_changed_results():
    prices, config = macd_fixture()
    raw = export_feature_experiment(prices, config, [MACDParameters(2, 3, 2)], selection_note='Declared before comparison.')
    restored, saved_config, results = restore_feature_experiment(raw)
    pd.testing.assert_frame_equal(restored, prices, check_freq=False)
    assert saved_config == config
    assert len(results['results']) == 4
    tampered = json.loads(raw)
    tampered['results']['hold']['equity'][-1] += 1
    with pytest.raises(ValidationError, match='replay'):
        restore_feature_experiment(json.dumps(tampered).encode())


def test_two_stock_weighted_return_and_drawdown_hand_calculation():
    prices, config = sample([100, 100, 100, 100, 110])
    prices['BBB'] = [50, 50, 50, 50, 47.5]
    config = replace(config, symbols=('AAA', 'BBB'), weights=(60., 40.), fee=0)
    result = run_strategy(prices, config, 'hold')
    assert result.holdings.iloc[0].tolist() == [6, 8]
    assert result.metrics['final_value'] == pytest.approx(1040)
    assert result.metrics['total_return'] == pytest.approx(.04)
    assert result.metrics['max_drawdown'] == 0
    # Reversing weights gives .4*10%+.6*(-5%)=1%.
    assert run_strategy(prices, replace(config, weights=(40., 60.)), 'hold').metrics['total_return'] == pytest.approx(.01)
    with pytest.raises(ValidationError):
        run_strategy(prices, replace(config, weights=(60., 45.)), 'hold')


def test_full_research_snapshot_keeps_benchmark_indicators_and_execution():
    from research_core import export_research_snapshot, restore_research_snapshot
    prices, config = macd_fixture()
    benchmark = pd.Series(np.arange(len(prices)) + 100., index=prices.index)
    basis = PriceBasis('demo', 'price_return', environment='hand-fixture-1')
    raw = export_research_snapshot(prices, config, [MACDParameters(2, 3, 2)],
        selection_note='Predeclared educational example.', price_basis=basis, benchmark=benchmark,
        benchmark_basis=basis, insight_parameters={'short': 2, 'long': 3, 'rsi_period': 2, 'macd': {'fast': 2, 'slow': 3, 'signal': 2}})
    _, _, replay = restore_research_snapshot(raw)
    assert replay['market']['benchmark'] == 'SPY'
    assert replay['insight_parameters']['rsi_period'] == 2
    assert replay['price_basis']['environment'] == 'hand-fixture-1'
    changed = json.loads(raw); changed['results']['market']['difference_percentage_points'] += 1
    with pytest.raises(ValidationError, match='replay'):
        restore_research_snapshot(json.dumps(changed).encode())


def test_offline_cli_runs_with_web_imports_forbidden(tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    completed = subprocess.run([sys.executable, 'verify_features.py', '--output-dir', str(tmp_path)],
                               cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr
    report = json.loads((tmp_path / 'features_verification.json').read_text())
    assert report['passed'] == report['total'] == 18


def test_signal_strategy_name_cannot_trigger_buy_and_hold_shortcut():
    prices, config = sample()
    signals = pd.DataFrame(False, index=prices.loc[config.start:config.end].index, columns=config.symbols)
    with pytest.raises(ValidationError, match='distinct'):
        run_signal_strategy(prices, config, signals, signals, name='hold')
