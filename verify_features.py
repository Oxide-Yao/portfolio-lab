"""Run deterministic phase-2 verification without Streamlit, web or market APIs.

python verify_features.py --output-dir ../evidence
"""
import argparse
from dataclasses import replace
from decimal import Decimal
import importlib.abc
import json
import math
from pathlib import Path
import sys


class NoWebImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'streamlit', 'yfinance', 'plotly'}:
            raise ImportError(f'Offline verification forbids importing {fullname}')
        return None


sys.meta_path.insert(0, NoWebImports())

import pandas as pd
from analytics_core import MACDParameters, PriceBasis, benchmark_comparison, ema, historical_beta, rsi
from data_core import demo_prices
from dca_core import create_plan, export_backup, import_backup, record_purchase, schedule, suggest, summarize
from research_core import export_research_snapshot, restore_research_snapshot
from verify_core import run_hand_checks, sample


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args(); args.output_dir.mkdir(parents=True, exist_ok=True)
    checks = run_hand_checks()
    def check(code, expected, actual, explanation):
        good = math.isclose(float(expected), float(actual), rel_tol=1e-10, abs_tol=1e-9)
        checks.append(dict(id=code, expected=float(expected), actual=float(actual), status='PASS' if good else 'FAIL', explanation=explanation))
    def series(values):
        return pd.Series(values, index=pd.bdate_range('2024-01-01', periods=len(values)), dtype=float)
    check('F01_EMA', 3, ema(series([1, 2, 3, 4]), 3).iloc[-1], 'SMA seed2; alpha .5; next EMA=.5*4+.5*2=3.')
    check('F02_RSI', 100-100/6, rsi(series([10, 11, 10, 12]), 2).iloc[-1], 'Wilder gain1.25/loss.25; RSI=83.333333.')
    basis = PriceBasis('demo', 'price_return', environment='hand-fixture-1')
    market = benchmark_comparison(series([100, 105, 112]), series([100, 104, 109]), portfolio_basis=basis, benchmark_basis=basis)
    check('F03_MARKET', 3, market['difference_percentage_points'], '12% minus9%=3 percentage points.')
    check('F04_BETA', 2, historical_beta(series([100, 120, 96]), series([100, 110, 99]))['beta'], 'Portfolio returns are twice each paired benchmark return.')
    cfg = dict(name='Offline DCA example', strategy='DCA', funding='fixed', symbols=['AAA', 'BBB'], weights=[60, 40],
               first_date='2024-01-31', frequency='monthly', total_budget='1000', periods=2,
               reserve_fraction='.2', contribution='100', annual_target='0')
    book = create_plan(cfg)
    quotes = {s: dict(price=str(p), date='2024-01-31', updated_at='2024-01-31T21:00:00+00:00', source='hand fixture', manual=True)
              for s, p in [('AAA', 100), ('BBB', 30)]}
    suggestion = suggest(book, quotes, as_of='2024-01-31')
    check('F05_DCA', 350, suggestion['estimated_spend'], '800 investable /2 periods=400; 60/40 weights ->2 shares at100 and5 at30.')
    trades = [dict(symbol=row['symbol'], shares=str(row['shares']), price=str(row['price']), fee='0') for row in suggestion['rows']]
    saved = record_purchase(book, request_id='verified-batch-1', period=1, actual_date='2024-01-31', trades=trades)
    state = summarize(saved, quotes, as_of='2024-01-31')
    check('F06_CASH', 650, state['cash'], '1000 budget minus350 purchases=650 cash, including200 protected reserve.')
    check('F07_GAIN', 0, state['investment_gain'], '350 holdings+650 cash-1000 contributed=0; reserve is not a second contribution.')
    archive = export_backup(saved); restored = import_backup(archive, mode='new')
    check('F08_DCA_RESTORE', state['cash'], summarize(restored, quotes, as_of='2024-01-31')['cash'], 'Full planner JSON replay under a new independent plan ID.')
    (args.output_dir/'dca_example.json').write_bytes(archive)
    prices, config = sample([10, 9, 8, 9, 11, 12, 15, 13, 10, 9, 12, 15, 13, 10, 9, 12])
    config = replace(config, start=prices.index[5].date().isoformat())
    benchmark = pd.Series(range(100, 100+len(prices)), index=prices.index, dtype=float)
    research = export_research_snapshot(prices, config, [MACDParameters(2, 3, 2), MACDParameters(2, 4, 2)],
        selection_note='Two small predeclared candidates for arithmetic verification, not optimized.',
        price_basis=basis, benchmark=benchmark, benchmark_basis=basis)
    _, _, result = restore_research_snapshot(research)
    check('F09_RESEARCH_RESTORE', 5, len(result['results']), 'Three original strategies and two MACD candidates restore with indicators, benchmark and trades.')
    (args.output_dir/'research_example.json').write_bytes(research)
    result['comparison'].to_csv(args.output_dir/'parameter_comparison.csv')
    # Synthetic symbols share a reproducible common process regardless of call order.
    demo = demo_prices(('AAA', 'SPY'))
    check('F10_DEMO', demo.AAA.iloc[-1], demo_prices(('SPY', 'AAA')).AAA.iloc[-1], 'Synthetic generation is stable across symbol order.')
    report = {'scope': 'Offline deterministic verification. No webpage, Streamlit, Plotly, Yahoo import, live API or deployment.',
              'hand_checks': checks, 'passed': sum(c['status']=='PASS' for c in checks), 'total': len(checks),
              'schedule': [schedule(cfg, p).isoformat() for p in (1, 2)],
              'calculation_version': result['calculation_version'],
              'limits': ['Fixtures are not market performance validation.', 'Live Yahoo/fundamentals fetching and UI integration were not tested in this phase.']}
    (args.output_dir/'features_verification.json').write_text(json.dumps(report, indent=2, allow_nan=False))
    print(f"Offline hand checks: {report['passed']}/{report['total']} passed; forbidden web imports: none")
    print('Evidence:', args.output_dir.resolve())
    if report['passed'] != report['total']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
