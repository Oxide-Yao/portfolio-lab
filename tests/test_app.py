from pathlib import Path
from datetime import date

import pytest
from streamlit.testing.v1 import AppTest


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv('PORTFOLIO_STORAGE','session')
    return AppTest.from_file(Path(__file__).resolve().parents[1]/'app.py',default_timeout=30).run()


def click(app,label=None,key=None):
    button=app.button(key=key) if key else next(b for b in app.button if b.label==label)
    assert not button.disabled
    button.click().run()
    assert not app.exception,[e.message for e in app.exception]


def page(app,name):
    app.radio(key='page').set_value(name).run()
    assert not app.exception,[e.message for e in app.exception]


def save(app,name):
    page(app,'Saved experiments')
    app.text_input(key='experiment_name').set_value(name).run()
    click(app,key='save_snapshot')
    assert app.success


def test_default_page_and_all_navigation(app):
    assert not app.exception
    initial=app.session_state.active
    assert initial['config'].symbols==('AAPL','MSFT','GOOGL')
    for name in ('Risk analysis','Strategy comparison','Saved experiments','Overview'):
        page(app,name)
        assert app.session_state.active['calculated_at']==initial['calculated_at']
    click(app,'Compare strategies →')
    assert app.session_state.page=='Strategy comparison'


def test_invalid_weights_disable_apply_and_preserve_result(app):
    before=app.session_state.active['calculated_at']
    app.number_input(key='weight_AAPL').set_value(10.).run()
    assert app.button(key='analyze').disabled
    assert app.button(key='header_save').disabled
    assert any('total 100%' in x.value for x in app.error)
    assert any('Unapplied changes' in x.value for x in app.warning)
    assert app.session_state.active['calculated_at']==before
    app.number_input(key='weight_AAPL').set_value(40.).run()
    click(app,key='analyze')
    assert not app.error


def test_save_compare_and_restore_exact_snapshot(app):
    page(app,'Saved experiments')
    click(app,key='save_snapshot')
    assert any('Experiment name' in x.value for x in app.error)
    save(app,'First analysis')
    first=next(iter(app.session_state.session_records.values()))
    app.number_input(key='capital').set_value(200000.).run()
    assert app.button(key='save_snapshot').disabled
    click(app,key='analyze')
    save(app,'Double capital')
    ids=list(app.session_state.session_records)
    app.multiselect(key='compare_records').set_value(ids).run()
    assert not app.exception
    assert any('Initial capital' in x.value for x in app.warning)
    app.selectbox(key='open_record').set_value(first['id']).run()
    click(app,'Open full results')
    assert app.session_state.page=='Overview'
    assert app.session_state.active['config'].capital==100000
    assert app.session_state.active['calculated_at']==first['calculated_at']
    assert app.number_input(key='capital').value==100000
    assert not any('Unapplied' in x.value for x in app.warning)


def test_session_records_isolated_between_visitors(app):
    save(app,'My experiment')
    other=AppTest.from_file(Path(__file__).resolve().parents[1]/'app.py',default_timeout=30).run()
    assert len(app.session_state.session_records)==1
    assert other.session_state.session_records=={}


def test_source_switch_does_not_request_yahoo(app,monkeypatch):
    import market_data
    monkeypatch.setattr(market_data,'yahoo_prices',lambda *a,**k:pytest.fail('Source selection must not fetch prices'))
    app.selectbox(key='source').set_value('yahoo').run()
    assert not app.exception
    assert app.session_state.active['config'].source=='demo'
    assert any('Unapplied changes' in x.value for x in app.warning)


def test_empty_trade_page_and_import_disabled(app):
    app.date_input(key='start').set_value(date(2023,1,2)).run()
    app.date_input(key='end').set_value(date(2023,1,4)).run()
    click(app,key='analyze')
    page(app,'Strategy comparison')
    assert any('No executions' in x.value for x in app.info)
    page(app,'Saved experiments')
    assert app.button(key='import_records').disabled


def test_user_facing_content_is_english(app):
    import re
    for name in ('Overview','Risk analysis','Strategy comparison','Saved experiments'):
        page(app,name)
        for kind in ('title','header','subheader','caption','markdown','info','warning','error'):
            for element in getattr(app,kind):
                assert not re.search(r'[\u4e00-\u9fff]',element.value),element.value


def test_local_launcher_storage_saves_and_reopens(app,monkeypatch,tmp_path):
    import storage
    path=tmp_path/'app-test.sqlite3';original=storage.SQLiteStore
    monkeypatch.setattr(storage,'SQLiteStore',lambda:original(path))
    monkeypatch.setenv('PORTFOLIO_STORAGE','sqlite')
    save(app,'Persistent UI test')
    restarted=AppTest.from_file(Path(__file__).resolve().parents[1]/'app.py',default_timeout=30).run()
    page(restarted,'Saved experiments')
    assert original(path).list_records()[0]['name']=='Persistent UI test'
    click(restarted,'Open full results')
    assert restarted.session_state.active['name']=='Persistent UI test'


def test_progress_keeps_checks_and_correct_highlight_after_save(app):
    page(app,'Risk analysis');page(app,'Strategy comparison')
    save(app,'Complete workflow')
    page(app,'Overview')
    assert app.session_state.completed==set(('Overview','Risk analysis','Strategy comparison','Saved experiments'))
    workflow=next(x.value for x in app.markdown if 'aria-label="Experiment progress"' in x.value)
    assert 'class="workflow-step current" aria-current="step">✓ Configure portfolio' in workflow
    assert '✓ Analyze risk' in workflow and '✓ Compare strategies' in workflow and '✓ Save experiment' in workflow
    app.selectbox(key='view_choice').set_value('stop').run()
    assert app.session_state.page=='Overview'
    assert app.session_state.viewed_strategy=='stop'
    workflow=next(x.value for x in app.markdown if 'aria-label="Experiment progress"' in x.value)
    assert 'aria-current="step">✓ Configure portfolio' in workflow


def test_edit_invalidates_completion_blocks_save_and_does_not_change_results(app):
    page(app,'Risk analysis');page(app,'Strategy comparison');save(app,'Before edit')
    before=app.session_state.active['calculated_at']
    app.number_input(key='fee').set_value(.5).run()
    assert app.session_state.completed==set()
    assert app.button(key='save_snapshot').disabled
    assert app.session_state.active['calculated_at']==before
    click(app,key='analyze')
    assert app.session_state.active['config'].fee==.005
    assert app.session_state.completed=={'Overview'}
    assert not app.button(key='save_snapshot').disabled


def test_stock_update_equal_weights_and_validation(app):
    app.text_input(key='symbols').set_value('aapl, msft').run()
    assert app.button(key='analyze').disabled
    click(app,'Update list')
    assert app.number_input(key='weight_AAPL').value==50.
    assert app.number_input(key='weight_MSFT').value==50.
    app.number_input(key='weight_AAPL').set_value(70.).run()
    click(app,'Equal weight')
    click(app,key='analyze')
    assert app.session_state.active['config'].symbols==('AAPL','MSFT')
    app.text_input(key='symbols').set_value('AAPL, AAPL').run()
    click(app,'Update list')
    assert app.session_state.configured_symbols==('AAPL','MSFT')
    assert any('unique' in x.value for x in app.error)


def test_strategy_selection_survives_page_switches(app):
    app.selectbox(key='view_choice').set_value('golden').run()
    page(app,'Strategy comparison');page(app,'Risk analysis')
    assert app.selectbox(key='view_choice').value=='golden'
    page(app,'Overview')
    assert app.selectbox(key='view_choice').value=='golden'


def test_failed_analysis_keeps_old_snapshot_and_blocks_save(app,monkeypatch):
    import market_data
    from models import ValidationError
    before=app.session_state.active['calculated_at']
    def fail(*a,**k):raise ValidationError('Network unavailable for test')
    monkeypatch.setattr(market_data,'yahoo_prices',fail)
    app.selectbox(key='source').set_value('yahoo').run()
    click(app,key='analyze')
    assert app.session_state.active['calculated_at']==before
    assert any('last successful' in x.value for x in app.warning)
    assert app.button(key='header_save').disabled
    page(app,'Saved experiments')
    assert app.button(key='save_snapshot').disabled


def test_open_saved_snapshot_never_downloads_prices(app,monkeypatch):
    import market_data
    save(app,'Stored snapshot')
    monkeypatch.setattr(market_data,'load_prices',lambda *a:pytest.fail('Opening stored results must not fetch data'))
    click(app,'Open full results')
    assert app.session_state.active['name']=='Stored snapshot'


def test_confirmed_removal_preserves_active_analysis(app):
    save(app,'Remove this record')
    before=app.session_state.active['calculated_at']
    assert app.button(key='remove_record').disabled
    app.checkbox(key='confirm_remove').set_value(True).run()
    click(app,key='remove_record')
    assert app.session_state.session_records=={}
    assert app.session_state.active['calculated_at']==before
    assert any('removed' in x.value for x in app.success)
