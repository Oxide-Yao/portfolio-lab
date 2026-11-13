"""Offline orchestration and full research snapshots for later website integration."""
from dataclasses import asdict
import json

import pandas as pd

from analytics_core import (CALCULATION_VERSION, MACDParameters, PriceBasis, benchmark_comparison,
                            historical_beta, stock_insights)
from feature_backtest import compare_macd_parameters
from trading_strategy import analyze
from models import AnalysisConfig, ValidationError
from price_validation import validate_prices
from storage import _same, encode_results


def analyze_experiment(prices, config, candidates, *, selection_note, price_basis, scope=None,
                       benchmark=None, benchmark_basis=None, benchmark_symbol='SPY',
                       observed_strategy='hold', insight_parameters=None):
    """Fixed snapshot in, new result out. No session changes, caching or fallback.

    PriceBasis is explicit provenance supplied by the data adapter. Historical
    observations are not silently substituted when benchmark coverage fails.
    """
    config.validate(); price_basis.validate()
    if price_basis.source != config.source:
        raise ValidationError('Price provenance must match the configured data source.')
    prices = validate_prices(prices, config)
    candidates = tuple(candidates)
    if candidates:
        run = compare_macd_parameters(prices, config, candidates, selection_note=selection_note, scope=scope)
    else:
        results = analyze(prices, config)
        run = {'results':results, 'comparison':pd.DataFrame({k:v.metrics for k,v in results.items()}).T,
               'parameters':[], 'selection_note':selection_note, 'scope':list(config.symbols),
               'execution':'Original strategies; signals at close, execution at next common close.',
               'calculation_version':CALCULATION_VERSION}

    if observed_strategy not in run['results']:
        raise ValidationError('Choose an existing strategy for market comparison.')
    params = insight_parameters or {'short': config.short_window, 'long': config.long_window,
                                    'rsi_period': 14, 'macd': asdict(MACDParameters())}
    if set(params) != {'short', 'long', 'rsi_period', 'macd'}:
        raise ValidationError('Specify short, long, rsi_period and macd insight parameters.')
    insights = {s: stock_insights(prices[s], short=params['short'], long=params['long'],
                                  rsi_period=params['rsi_period'], macd_parameters=MACDParameters(**params['macd']))
                for s in config.symbols}
    market = beta = None
    if benchmark is not None:
        if not isinstance(benchmark_basis, PriceBasis):
            raise ValidationError('Benchmark provenance is required.')
        equity = run['results'][observed_strategy].equity
        market = benchmark_comparison(equity, benchmark, portfolio_basis=price_basis,
                                      benchmark_basis=benchmark_basis, benchmark_symbol=benchmark_symbol)
        if len(equity) >= 3:
            try:
                beta = historical_beta(equity, benchmark.loc[equity.index])
            except ValidationError as exc:
                beta = {'status': 'Not available', 'reason': str(exc)}
        else:
            beta = {'status': 'Not available', 'reason': 'At least two paired daily returns are required.'}
    return {**run, 'insights': insights, 'insight_parameters': params, 'market': market, 'beta': beta,
            'observed_strategy': observed_strategy, 'price_basis': asdict(price_basis),
            'requested_dates': [config.start, config.end],
            'effective_dates': [run['results']['hold'].equity.index[0].date().isoformat(),
                                run['results']['hold'].equity.index[-1].date().isoformat()]}


def _frame(frame):
    return {'dates': [d.date().isoformat() for d in frame.index], 'columns': list(frame.columns),
            'values': frame.to_numpy().tolist()}


def _restore_frame(data):
    if not isinstance(data, dict) or set(data) != {'dates', 'columns', 'values'}:
        raise ValidationError('Invalid data snapshot.')
    return pd.DataFrame(data['values'], columns=data['columns'], index=pd.to_datetime(data['dates']))


def _encoded_run(run):
    def table(frame):
        # Explicit null for indicator warm-up, never a fabricated zero.
        return json.loads(frame.to_json(orient='split', date_format='iso', double_precision=15))
    insights = {s: {**{k: v for k, v in item.items() if k != 'data'}, 'data': table(item['data'])}
                for s, item in run['insights'].items()}
    market = None if run['market'] is None else {**{k: v for k, v in run['market'].items() if k not in ('curves', 'csv')},
                                              'curves': table(run['market']['curves'])}
    return {'strategies': encode_results(run['results']), 'insights': insights, 'market': market, 'beta': run['beta'],
            'requested_dates': run['requested_dates'], 'effective_dates': run['effective_dates'], 'execution': run['execution']}


def export_research_snapshot(prices, config, candidates, **options):
    run = analyze_experiment(prices, config, candidates, **options)
    benchmark = options.get('benchmark')
    inputs = {'prices': _frame(prices), 'config': config.to_dict(), 'parameters': run['parameters'],
              'selection_note': run['selection_note'], 'scope': run['scope'], 'price_basis': run['price_basis'],
              'insight_parameters': run['insight_parameters'], 'observed_strategy': run['observed_strategy'],
              'benchmark': None if benchmark is None else _frame(benchmark.to_frame('benchmark')),
              'benchmark_basis': None if benchmark is None else asdict(options['benchmark_basis']),
              'benchmark_symbol': options.get('benchmark_symbol', 'SPY')}
    payload = {'schema': 'portfolio-lab-research-1', 'calculation_version': CALCULATION_VERSION,
               'inputs': inputs, 'results': _encoded_run(run)}
    return json.dumps(payload, allow_nan=False, ensure_ascii=False).encode()


def restore_research_snapshot(raw):
    if not isinstance(raw, bytes) or len(raw) > 16 * 1024 * 1024:
        raise ValidationError('Provide a research JSON snapshot of at most 16 MB.')
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValidationError('Duplicate JSON key.')
            result[k] = v
        return result
    try:
        data = json.loads(raw, object_pairs_hook=unique)
        if set(data) != {'schema', 'calculation_version', 'inputs', 'results'} or data['schema'] != 'portfolio-lab-research-1' or data['calculation_version'] != CALCULATION_VERSION:
            raise ValidationError('Unsupported research snapshot version.')
        args = dict(data['inputs'])
        prices = _restore_frame(args.pop('prices')); config = AnalysisConfig.from_dict(args.pop('config'))
        candidates = [MACDParameters(**p) for p in args.pop('parameters')]
        args['price_basis'] = PriceBasis(**args['price_basis'])
        if args['benchmark'] is not None:
            frame = _restore_frame(args['benchmark'])
            if list(frame.columns) != ['benchmark']:
                raise ValidationError('Invalid benchmark snapshot columns.')
            args['benchmark'] = frame['benchmark']
            args['benchmark_basis'] = PriceBasis(**args['benchmark_basis'])
        replay = export_research_snapshot(prices, config, candidates, **args)
        if not _same(data, json.loads(replay)):
            raise ValidationError('Snapshot results or provenance differ from deterministic replay.')
        return prices, config, analyze_experiment(prices, config, candidates, **args)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
        raise ValidationError(f'Cannot restore research snapshot: {exc}') from exc
