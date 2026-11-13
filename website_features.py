"""Web adapters around independently tested analysis functions."""
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json

from analytics_core import MACDParameters, PriceBasis, CALCULATION_VERSION, benchmark_comparison
from feature_backtest import compare_macd_parameters
from models import ValidationError
from research_core import analyze_experiment, export_research_snapshot, restore_research_snapshot
import market_data

DEFAULT_FEATURES = {'benchmark': 'SPY', 'macd_enabled': False, 'candidates': [{'fast':12,'slow':26,'signal':9}],
                    'scope': None, 'selection_note': 'Conventional 12/26/9 settings selected before viewing results; exploratory comparison.',
                    'rsi_period':14, 'insight_macd': {'fast':12,'slow':26,'signal':9}}


def feature_options(value=None):
    return deepcopy(DEFAULT_FEATURES if value is None else value)


def validate_features(options, symbols):
    if options['benchmark'] not in ('SPY','QQQ'):
        raise ValidationError('Choose SPY or QQQ as the market benchmark.')
    if not 2 <= options['rsi_period'] <= 100:
        raise ValidationError('RSI period must be between 2 and 100 trading days.')
    MACDParameters(**options['insight_macd']).validate()
    if options['macd_enabled']:
        if not 1 <= len(options['candidates']) <= 5:
            raise ValidationError('Enter 1–5 distinct MACD candidates.')
        candidates=[MACDParameters(**p).validate() for p in options['candidates']]
        if len(set(candidates)) != len(candidates):
            raise ValidationError('Remove duplicate MACD candidates.')
        if not options['selection_note'].strip():
            raise ValidationError('Explain how you chose the MACD parameters.')
        if options['scope'] is not None and (not options['scope'] or not set(options['scope']).issubset(symbols)):
            raise ValidationError('Select a current holding for MACD, or choose All holdings.')
    return options


def basis_for(config):
    return PriceBasis(config.source, 'price_return' if config.source=='demo' else 'adjusted_close',
                      environment='synthetic-4145-v1' if config.source=='demo' else 'yahoo-adjusted-v1')


def research_args(config, options, benchmark=None):
    basis=basis_for(config)
    return dict(selection_note=options['selection_note'], scope=options['scope'] if options['macd_enabled'] else None,
                price_basis=basis, benchmark=benchmark, benchmark_basis=basis if benchmark is not None else None,
                benchmark_symbol=options['benchmark'],
                insight_parameters={'short':config.short_window,'long':config.long_window,
                                    'rsi_period':options['rsi_period'],'macd':options['insight_macd']})


def candidates_for(options):
    return [MACDParameters(**p) for p in options['candidates']] if options['macd_enabled'] else []


def compute_features(config, options=None):
    options=validate_features(feature_options(options),config.symbols)
    # Load enough prior dates for every displayed indicator, without changing applied strategy settings.
    lookback=max([config.long_window, options['rsi_period']+1,
                  options['insight_macd']['slow']+options['insight_macd']['signal']] +
                 [p['slow']+p['signal'] for p in options['candidates'] if options['macd_enabled']])
    load_config=replace(config,long_window=min(500,max(config.long_window,lookback)))
    prices,notes=market_data.load_prices(load_config)
    run=analyze_experiment(prices,config,candidates_for(options),**research_args(config,options))
    benchmark=None; benchmark_error=None
    try:
        symbol=options['benchmark']
        if symbol in prices:
            benchmark=prices[symbol].copy()
        else:
            benchmark_config=replace(load_config,symbols=(symbol,),weights=(100.,))
            bp,_=market_data.load_prices(benchmark_config)
            benchmark=bp[symbol]
        benchmark_comparison(run['results']['hold'].equity,benchmark,portfolio_basis=basis_for(config),
                             benchmark_basis=basis_for(config),benchmark_symbol=symbol)
        run=analyze_experiment(prices,config,candidates_for(options),**research_args(config,options,benchmark))
    except Exception as exc:
        benchmark=None
        benchmark_error=f'Benchmark unavailable: {exc}. Portfolio results are unchanged. Apply again to retry.'
    return {'config':config,'prices':prices,'results':run['results'],'notes':notes,
            'calculated_at':datetime.now(timezone.utc).isoformat(),'name':None,
            'features':options,'research':run,'benchmark':benchmark,'benchmark_error':benchmark_error}


def snapshot_for(active):
    options=active['features']
    return export_research_snapshot(active['prices'],active['config'],candidates_for(options),
                                   **research_args(active['config'],options,active.get('benchmark')))


def restore_features(raw):
    prices,config,run=restore_research_snapshot(raw)
    inputs=json.loads(raw)['inputs']
    options=feature_options()
    options.update(benchmark=inputs['benchmark_symbol'],macd_enabled=bool(inputs['parameters']),
                   scope=inputs['scope'] if inputs['parameters'] and inputs['scope']!=list(config.symbols) else None,
                   candidates=inputs['parameters'] or options['candidates'], selection_note=inputs['selection_note'],
                   rsi_period=inputs['insight_parameters']['rsi_period'],insight_macd=inputs['insight_parameters']['macd'])
    benchmark=None
    if inputs['benchmark'] is not None:
        import pandas as pd
        frame=inputs['benchmark']
        benchmark=pd.Series([v[0] for v in frame['values']],index=pd.to_datetime(frame['dates']))
    return {'features':options,'research':run,'benchmark':benchmark,'benchmark_error':None,
            'prices':prices,'config':config,'results':run['results']}
