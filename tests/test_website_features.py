from copy import deepcopy
from pathlib import Path
import json
from datetime import date
import pytest
from streamlit.testing.v1 import AppTest
from models import AnalysisConfig, ValidationError
from website_features import compute_features, feature_options, snapshot_for, restore_features
from experiments import make_active_record
from storage import export_records, import_records

ROOT=Path(__file__).resolve().parents[1]


def button(app,label):
    next(b for b in app.button if b.label==label).click().run()
    assert not app.exception,[e.message for e in app.exception]


def test_full_research_archive_replay_and_tampering():
    options=feature_options();options['macd_enabled']=True
    options['candidates'].append({'fast':8,'slow':21,'signal':5})
    active=compute_features(AnalysisConfig(),options)
    record=make_active_record('MACD research',active)
    restored=import_records(export_records([record]))[0]
    opened=restore_features(json.dumps(restored['research']).encode())
    assert len(opened['results'])==5
    assert opened['features']['candidates']==options['candidates']
    assert opened['benchmark'].equals(active['benchmark'])
    bad=deepcopy(record);bad['research']['inputs']['parameters'][0]['fast']=10
    with pytest.raises(ValidationError):import_records(export_records([bad]))


def test_benchmark_failure_preserves_successful_portfolio(monkeypatch):
    import market_data
    original=market_data.load_prices
    def load(config):
        if config.symbols==('SPY',):raise ValidationError('Benchmark test failure')
        return original(config)
    monkeypatch.setattr(market_data,'load_prices',load)
    active=compute_features(AnalysisConfig())
    assert active['benchmark'] is None and 'Benchmark test failure' in active['benchmark_error']
    assert active['results']['hold'].metrics['final_value']>0
    assert restore_features(snapshot_for(active))['benchmark'] is None


def test_new_research_pages_and_feature_draft_restore():
    app=AppTest.from_file(ROOT/'app.py',default_timeout=40).run()
    for page in ('Stock insights','Risk analysis','Overview'):
        app.radio(key='page').set_value(page).run()
        assert not app.exception
    previous=app.session_state.active['calculated_at'];completed=set(app.session_state.completed)
    app.selectbox(key='feature_benchmark').set_value('QQQ').run()
    assert app.session_state.active['features']['benchmark']=='SPY'
    assert app.button(key='header_save').disabled
    app.selectbox(key='feature_benchmark').set_value('SPY').run()
    assert not app.button(key='header_save').disabled
    assert app.session_state.completed==completed
    app.checkbox(key='feature_macd_enabled').set_value(True).run()
    app.button(key='analyze').click().run()
    assert not app.exception
    assert app.session_state.active['calculated_at']!=previous
    assert len(app.session_state.active['results'])==4
    app.selectbox(key='view_choice').set_value('macd_12_26_9').run()
    assert not app.exception and app.session_state.page=='Overview'
    app.radio(key='page').set_value('Strategy comparison').run()
    assert not app.exception
    app.radio(key='page').set_value('Saved experiments').run()
    button(app,'Save to this session')
    button(app,'Open full results')
    assert app.session_state.active['features']['macd_enabled']
    assert not app.button(key='header_save').disabled


def test_planner_create_suggest_record_and_isolated_simulation():
    app=AppTest.from_file(ROOT/'app.py',default_timeout=40).run()
    app.radio(key='page').set_value('DCA Planner').run()
    button(app,'Create plan in this session')
    assert len(app.session_state.plans)==1
    pid=app.session_state.planner_selected
    app.radio(key='planner_page').set_value('This period').run()
    for symbol,price in [('AAPL',100.),('MSFT',200.),('VOO',50.)]:
        app.number_input(key='qp_'+pid+'_actual'+symbol).set_value(price).run()
    app.button(key='calculate_suggestion').click().run()
    assert not app.exception
    confirm=next(x for x in app.checkbox if x.label=='I confirm this is a actual record, not an order.')
    confirm.set_value(True)
    button(app,'Record purchase')
    from dca_core import replay, export_backup, import_backup
    book=app.session_state.plans[pid]
    assert replay(book)['completed_periods']==1
    assert replay(book,'simulated')['completed_periods']==0
    assert replay(import_backup(export_backup(book),mode='new'))['cash']==replay(book)['cash']
    app.radio(key='planner_page').set_value('History').run()
    assert not app.exception
    app.radio(key='planner_page').set_value('Plan settings').run()
    assert not app.exception
    other=AppTest.from_file(ROOT/'app.py',default_timeout=40).run()
    other.radio(key='page').set_value('DCA Planner').run()
    assert other.session_state.plans=={}
