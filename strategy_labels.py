"""Stable labels for original strategies and parameterized MACD experiments."""
from trading_strategy import STRATEGIES

def strategy_name(key):
    return STRATEGIES.get(key, 'MACD · ' + key.removeprefix('macd_').replace('_','/'))

def strategy_color(key):
    return {'hold':'#456ca3','golden':'#7f93ad','stop':'#5e7fbd'}.get(key,'#826e9c')

def strategy_dash(key):
    return {'hold':'solid','golden':'dash','stop':'dot'}.get(key,'dashdot')
