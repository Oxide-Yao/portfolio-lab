"""Reproducible phase-2 checks without a browser or live market download.

Run with --output-dir to retain expected/actual values and source fingerprints.
The optional teacher replay extracts only three reviewed calculation functions;
it never executes notebook top-level calls, installation commands or downloads.
"""
import argparse
import ast
from dataclasses import replace
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
import math
from pathlib import Path
import statistics
from zoneinfo import ZoneInfo

import pandas as pd

from course_data import read_course_prices
from models import AnalysisConfig, ValidationError
from trading_strategy import analyze, risk_metrics


def sample(values=None, **overrides):
    values = values if values is not None else [10,9,8,9,11,12,15,16,16]
    prices = pd.DataFrame({'AAA': values}, index=pd.bdate_range('2024-01-01', periods=len(values)))
    config = AnalysisConfig(symbols=('AAA',),weights=(100.,),capital=1000.,
        start=prices.index[3].date().isoformat(),end=prices.index[-1].date().isoformat(),
        short_window=2,long_window=3,fee=.01)
    return prices, replace(config,**overrides)


def run_hand_checks():
    checks=[]
    def check(code, description, expected, actual, explanation):
        def same(a,b):
            if isinstance(a,dict):return set(a)==set(b) and all(same(a[k],b[k]) for k in a)
            if isinstance(a,list):return len(a)==len(b) and all(same(x,y) for x,y in zip(a,b))
            if type(a) in (int,float):return math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-9)
            return a==b
        checks.append(dict(id=code,description=description,expected=expected,actual=actual,
                           status='PASS' if same(expected,actual) else 'FAIL',explanation=explanation))
    p=pd.DataFrame({'AAA':[100,100,100,100,110],'BBB':[50,50,50,50,47.5]},index=pd.bdate_range('2024-01-01',periods=5))
    _,base=sample()
    c=replace(base,symbols=('AAA','BBB'),weights=(60.,40.),fee=0.,end='2024-01-05')
    r=analyze(p,c)['hold']
    check('C01','Two-stock portfolio hand calculation',{'final_value':1040.,'return':.04},
        {'final_value':r.metrics['final_value'],'return':r.metrics['total_return']},
        'USD 600 / 100 = 6 shares; USD 400 / 50 = 8 shares; 6×110 + 8×47.5 = 1040. No fees or rebalancing.')
    p,c=sample();r=analyze(p,c)['golden']
    shares=Decimal(1000)/(Decimal(12)*Decimal('1.01'))
    proceeds=shares*Decimal(16)*Decimal('.99')
    fees=shares*Decimal(12)*Decimal('.01') + shares*Decimal(16)*Decimal('.01')
    check('C02','Both-side fees and net profit',{'shares':float(shares),'final_value':float(proceeds),'pnl':float(proceeds-1000),'fees':float(fees)},
        {'shares':float(r.trades.iloc[0]['shares']),'final_value':r.metrics['final_value'],'pnl':float(r.trades.iloc[1]['pnl']),'fees':r.metrics['fees']},
        'Independent Decimal calculation: shares=1000/(12×1.01); sell cash=shares×16×0.99. Fees reduce cash on both sides.')
    check('C03','Signals execute at the next trading close',
        ['2024-01-05','2024-01-08',12.,'2024-01-09','2024-01-10',16.],
        [r.trades.iloc[0]['signal_date'],r.trades.iloc[0]['date'],float(r.trades.iloc[0]['price']),r.trades.iloc[1]['signal_date'],r.trades.iloc[1]['date'],float(r.trades.iloc[1]['price'])],
        'The Jan 5 signal closes at 11; purchase uses Jan 8 at 12. Jan 9 trigger closes at 15; sale uses Jan 10 at 16.')
    m=risk_metrics(pd.Series([90.,81.,99.]),100.)
    check('C04','Initial baseline drawdown and sample volatility',
        {'max_drawdown':-.19,'volatility':statistics.stdev([-.1,-.1,99/81-1])*math.sqrt(252)},
        {'max_drawdown':m['max_drawdown'],'volatility':m['volatility']},
        'Initial 100 is included in the running peak; trough 81 gives −19%. Sample standard deviation uses n−1 and √252.')
    p,c=sample([10,9,8,9,11,12,11.04,9,9]);r=analyze(p,c)['stop']
    stop_return=float(Decimal(9)*Decimal('.99')/(Decimal(12)*Decimal('1.01'))-1)
    check('C05','Stop-loss threshold is not a guaranteed fill price',
        {'reason':'Stop loss','sell_date':'2024-01-10','fill':9.,'net_return':stop_return},
        {'reason':r.trades.iloc[1]['reason'],'sell_date':r.trades.iloc[1]['date'],'fill':float(r.trades.iloc[1]['price']),'net_return':float(r.trades.iloc[1]['return'])},
        'Entry is 12; −8% observed at 11.04; next-close sale at 9. Realized loss includes the gap and both fees.')
    p,c=sample([10]*9);r=analyze(p,c)['golden']
    check('C06','No crossing preserves initial cash',{'value':1000.,'fees':0.,'executions':0},
        {'value':r.metrics['final_value'],'fees':r.metrics['fees'],'executions':len(r.trades)},'Flat prices produce no golden cross; no invented trades or costs.')
    p,c=sample([10,9,8,9,11]);r=analyze(p,c)['golden']
    check('C07','Final-day entry signal cannot execute',{'value':1000.,'executions':0},
        {'value':r.metrics['final_value'],'executions':len(r.trades)},'No following trading close exists, so the final signal is not filled.')
    p,c=sample([10,9,8,9,11,12,15]);r=analyze(p,c)['golden']
    check('C08','Open final position has no fictional exit fee',
        {'value':float(shares*15),'completed_trades':0,'open_positions':1,'executions':1},
        {'value':r.metrics['final_value'],'completed_trades':r.metrics['completed_trades'],'open_positions':r.metrics['open_positions'],'executions':len(r.trades)},
        'The final date has a sell trigger but no future fill; mark remaining shares at 15 and charge only the actual buy fee.')
    return checks


def teacher_replay(notebook, prices):
    raw=Path(notebook).read_bytes();data=json.loads(raw)
    source=next(''.join(c.get('source',[])) for c in data['cells']
        if c.get('cell_type')=='code' and 'def implement_strategy(data):' in ''.join(c.get('source',[])))
    names={'calculate_moving_averages','identify_golden_cross','implement_strategy'}
    nodes=[n for n in ast.parse(source).body if isinstance(n,ast.FunctionDef) and n.name in names]
    if {n.name for n in nodes}!=names:raise ValueError('Teacher reference functions missing')
    namespace={'pd':pd}
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'<reviewed-course-functions>','exec'),namespace)
    frame=prices[['MSFT']].rename(columns={'MSFT':'Close'}).copy()
    frame=namespace['calculate_moving_averages'](frame)
    frame=namespace['identify_golden_cross'](frame)
    original=namespace['implement_strategy'](frame)
    c=AnalysisConfig(symbols=('MSFT',),weights=(100.,),capital=100000.,fee=0.,
        start=frame.index[200].date().isoformat(),end=frame.index[-1].date().isoformat())
    current=analyze(prices[['MSFT']],c)['golden']
    return {
        'notebook_sha256':sha256(raw).hexdigest(),'reference':'Part II, code cell 6; selected definitions only',
        'input_price':'Same supplied CSV adjusted MSFT prices for both versions; no Yahoo download.',
        'settings':{'short_ma':50,'long_ma':200,'take_profit':.15,'max_hold_calendar_days':60,'fee':0.,
                    'effective_start':c.start,'effective_end':c.end},
        'teacher_round_trips':len(original),'teacher_trades':json.loads(original.to_json(orient='records',date_format='iso',double_precision=15)),
        'current_closed_trades':current.metrics['completed_trades'],
        'current_open_positions':current.metrics['open_positions'],
        'current_ledger':json.loads(current.trades.to_json(orient='records',double_precision=15)),
        'interpretation':'Rule audit, not a performance ranking: fill timing, capital constraints and end-of-data treatment differ. Do not sum the teacher trade percentages as portfolio return.',
    }


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',required=True,type=Path)
    parser.add_argument('--course-csv',type=Path)
    parser.add_argument('--teacher-notebook',type=Path)
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=True)
    report={'executed_at_hkt':datetime.now(ZoneInfo('Asia/Hong_Kong')).isoformat(),
        'executor':'Codex automated verification; team owner/reviewer sign-off remains pending.',
        'hand_checks':run_hand_checks()}
    if args.course_csv:
        prices,meta=read_course_prices(args.course_csv,('AAPL','MSFT','GOOGL'))
        # analyze() accepts an explicit snapshot and never fetches data. Its
        # source field is an unused UI adapter selector here, not provenance.
        # The actual provenance is always the supplied-file metadata below.
        c=AnalysisConfig(start='2023-01-01',end=meta['last_date'])
        results=analyze(prices,c)
        visible=prices.loc[c.start:c.end]
        expected=sum(Decimal(str(c.capital))*Decimal(str(w))/100 * Decimal(str(visible.iloc[-1][s]))/Decimal(str(visible.iloc[0][s]))/(1+Decimal(str(c.fee))) for s,w in zip(c.symbols,c.weights))
        actual=results['hold'].metrics['final_value']
        params=c.to_dict();params.pop('source')
        report['historical_csv']={'provenance':meta,'parameters':params,
            'adapter_note':'Direct snapshot calculation; load_prices() and its demo/yahoo selector are not used. CSV is not yet selectable in the web UI.',
            'effective_start':visible.index[0].date().isoformat(),'effective_end':visible.index[-1].date().isoformat(),
            'performance_rows':len(visible),'warm_up_rows':int((prices.index<visible.index[0]).sum()),
            'hold_independent_check':{'expected':float(expected),'actual':actual,'absolute_difference':abs(actual-float(expected)),
                'status':'PASS' if abs(actual-float(expected))<.01 else 'FAIL',
                'formula':'Σ(initial capital × weight / 100 × last adjusted price / first adjusted price / (1 + buy fee)); no forced final sale.'},
            'metrics':{k:r.metrics for k,r in results.items()},
            'assumptions':'USD, daily adjusted close, fractional shares, fixed initial cash sleeves, no rebalancing/leverage, next-common-close signal fills, no final forced liquidation.',
            'limit':'Rounded prices in the supplied file; fixed historical window and three selected stocks. This is not out-of-sample validation or proof of investment performance.'}
        for name,r in results.items():
            detail={'dates':[d.date().isoformat() for d in r.equity.index],'equity':r.equity.tolist(),
                    'metrics':r.metrics,'trades':json.loads(r.trades.to_json(orient='records',double_precision=15))}
            (args.output_dir/f'historical_{name}.json').write_text(json.dumps(detail,indent=2,allow_nan=False))
        # Parameter sensitivity is descriptive. No tuning or best-rule claim.
        report['parameter_sensitivity']={}
        for label,config in [('MA20_100',replace(c,short_window=20,long_window=100)),
                             ('fee_0',replace(c,fee=0.)),('fee_0_5pct',replace(c,fee=.005))]:
            report['parameter_sensitivity'][label]={k:r.metrics for k,r in analyze(prices,config).items()}
        if args.teacher_notebook:
            report['teacher_comparison']=teacher_replay(args.teacher_notebook,prices)
    output=args.output_dir/'core_verification.json'
    output.write_text(json.dumps(report,indent=2,allow_nan=False))
    failures=[c['id'] for c in report['hand_checks'] if c['status']!='PASS']
    if report.get('historical_csv',{}).get('hold_independent_check',{}).get('status','PASS')!='PASS':failures.append('historical_hold')
    print(f'Hand-calculated checks: {len(report["hand_checks"])-len([c for c in report["hand_checks"] if c["status"]!="PASS"])}/{len(report["hand_checks"])} passed')
    if 'historical_csv' in report:
        print(json.dumps(report['historical_csv'],indent=2))
    print('Evidence:',output)
    if failures:raise SystemExit('Failed: '+', '.join(failures))


if __name__=='__main__':main()
