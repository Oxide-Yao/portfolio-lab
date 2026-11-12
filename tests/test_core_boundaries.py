"""Independent arithmetic and invalid-data checks for the phase-2 core boundary."""
from dataclasses import replace
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest

from conftest import sample
from market_data import validate_prices
from models import ValidationError
from trading_strategy import analyze, risk_metrics, run_strategy


def test_core_import_and_calculation_without_web_or_network_packages():
    root = Path(__file__).resolve().parents[1]
    code = '''
import importlib.abc
import sys
class NoWebPackages(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'streamlit', 'yfinance', 'plotly'}:
            raise ModuleNotFoundError('Forbidden core dependency: ' + fullname)
sys.meta_path.insert(0, NoWebPackages())
import pandas as pd
from models import AnalysisConfig
from trading_strategy import analyze
p = pd.DataFrame({'AAA': [100,100,100,100,110], 'BBB': [50,50,50,50,47.5]},
                 index=pd.bdate_range('2024-01-01', periods=5))
c = AnalysisConfig(symbols=('AAA','BBB'), weights=(60.,40.), capital=1000.,
                   start='2024-01-04', end='2024-01-05', short_window=2,
                   long_window=3, fee=0.)
assert abs(analyze(p,c)['hold'].metrics['final_value'] - 1040.) < .01
assert not {'streamlit','yfinance','plotly'}.intersection(sys.modules)
print('CORE_ONLY_PASS final_value=1040.00')
'''
    result = subprocess.run([sys.executable, '-c', code], cwd=root,
                            env=dict(os.environ, PYTHONDONTWRITEBYTECODE='1'),
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'CORE_ONLY_PASS' in result.stdout


def test_phase1_two_stock_acceptance_example_and_no_input_mutation():
    prices = pd.DataFrame({'AAA': [100,100,100,100,110], 'BBB': [50,50,50,50,47.5]},
                          index=pd.bdate_range('2024-01-01', periods=5))
    _, base = sample()
    config = replace(base, symbols=('AAA','BBB'), weights=(60.,40.),
                     start='2024-01-04', end='2024-01-05', fee=0.)
    original = prices.copy(deep=True)
    result = analyze(prices, config)['hold']
    # 6 x 110 + 8 x 47.5 = 1,040; 4% return, not the sum of stock returns.
    assert result.metrics['final_value'] == pytest.approx(1040, abs=.01)
    assert result.metrics['total_return'] == pytest.approx(.04)
    pd.testing.assert_frame_equal(prices, original)


@pytest.mark.parametrize('bad', [True, complex(10, 2)])
def test_boolean_and_complex_prices_rejected(bad):
    prices, config = sample()
    prices = prices.astype(object)
    prices.iloc[0, 0] = bad
    with pytest.raises(ValidationError, match='real numeric'):
        validate_prices(prices, config)


@pytest.mark.parametrize('change', [
    {'capital': 0}, {'weights': (-100.,)}, {'fee': float('nan')},
])
def test_single_strategy_entrypoint_validates_configuration(change):
    prices, config = sample()
    with pytest.raises(ValidationError):
        run_strategy(prices, replace(config, **change), 'hold')


def test_single_strategy_entrypoint_validates_prices():
    prices, config = sample()
    prices.iloc[0,0] = 0
    with pytest.raises(ValidationError):
        run_strategy(prices, config, 'hold')


@pytest.mark.parametrize('values, initial', [
    ([], 100.), ([100.], 0.), ([100.], -1.), ([100.], True),
    ([100.], float('inf')), ([0.], 100.), ([-1.], 100.),
    ([float('nan')], 100.), ([float('inf')], 100.),
    ([True], 100.), ([complex(100, 2)], 100.),
])
def test_risk_metrics_reject_invalid_input(values, initial):
    with pytest.raises(ValidationError):
        risk_metrics(pd.Series(values), initial)


def test_constant_curve_and_single_day_risk_values():
    for values in ([1000.], [1000.,1000.,1000.]):
        result = risk_metrics(pd.Series(values), 1000.)
        assert result == {'final_value':1000., 'total_return':0.,
                          'max_drawdown':0., 'volatility':0.}


@pytest.mark.parametrize('condition', ['duplicate','reverse','timezone','intraday','infinite','negative','missing_column'])
def test_reject_corrupt_price_snapshot(condition):
    prices, config = sample()
    prices = prices.astype(float)
    if condition == 'duplicate':
        prices.index = pd.DatetimeIndex([prices.index[0], *prices.index[:-1]])
    elif condition == 'reverse': prices = prices.iloc[::-1]
    elif condition == 'timezone': prices.index = prices.index.tz_localize('America/New_York')
    elif condition == 'intraday': prices.index = pd.DatetimeIndex([d.replace(hour=12) for d in prices.index])
    elif condition == 'infinite': prices.iloc[0,0] = np.inf
    elif condition == 'negative': prices.iloc[0,0] = -1
    elif condition == 'missing_column': prices.columns = ['BBB']
    with pytest.raises(ValidationError):
        validate_prices(prices, config)
