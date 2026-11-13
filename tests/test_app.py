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
    assert any('Weights total 70%. Allocate the remaining 30 percentage points.' in x.value for x in app.error)
    assert any('Unapplied changes' in x.value for x in app.warning)
    assert app.session_state.active['calculated_at']==before
    app.number_input(key='weight_AAPL').set_value(40.).run()
    click(app,key='analyze')
    assert not app.error


def test_save_compare_and_restore_exact_snapshot(app):
    page(app,'Saved experiments')
    assert app.text_input(key='experiment_name').value
    app.text_input(key='experiment_name').set_value('').run()
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


def test_edit_retains_completion_blocks_save_and_does_not_change_results(app):
    page(app,'Risk analysis');page(app,'Strategy comparison');save(app,'Before edit')
    before=app.session_state.active['calculated_at']
    app.number_input(key='fee').set_value(.5).run()
    assert app.session_state.completed=={'Overview','Risk analysis','Strategy comparison','Saved experiments'}
    assert app.button(key='save_snapshot').disabled
    assert app.session_state.active['calculated_at']==before
    click(app,key='analyze')
    assert app.session_state.active['config'].fee==.005
    assert app.session_state.completed=={'Overview'}
    page(app,'Saved experiments')
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


def amount_mode(app):
    app.radio(key='allocation_mode').set_value('amount').run()
    assert not app.exception,[e.message for e in app.exception]


def test_amount_inputs_drive_applied_config_without_early_recalculation(app):
    before=app.session_state.active['calculated_at']
    amount_mode(app)
    assert app.number_input(key='capital').disabled
    for symbol,value in [('AAPL',10000.),('MSFT',20000.),('GOOGL',30000.)]:
        app.number_input(key='amount_'+symbol).set_value(value).run()
    assert not app.exception
    assert app.number_input(key='capital').value==60000.
    assert app.session_state.active['calculated_at']==before
    assert app.button(key='header_save').disabled
    assert any('Unapplied changes' in x.value for x in app.warning)
    click(app,key='analyze')
    config=app.session_state.active['config']
    assert config.capital==60000.
    assert config.weights==pytest.approx((100/6,100/3,50.))
    assert not app.button(key='header_save').disabled


def test_amounts_survive_mode_and_page_switches_and_capital_scaling(app):
    amount_mode(app)
    app.number_input(key='amount_AAPL').set_value(12000.).run()
    page(app,'Risk analysis');page(app,'Overview')
    for _ in range(3):
        app.radio(key='allocation_mode').set_value('weight').run()
        assert app.number_input(key='capital').value==72000.
        assert not app.number_input(key='capital').disabled
        assert app.number_input(key='weight_AAPL').value==pytest.approx(100/6)
        amount_mode(app)
        assert app.number_input(key='amount_AAPL').value==12000.
        assert app.number_input(key='amount_MSFT').value==35000.
    app.radio(key='allocation_mode').set_value('weight').run()
    app.number_input(key='capital').set_value(144000.).run()
    amount_mode(app)
    assert [app.number_input(key='amount_'+s).value for s in ('AAPL','MSFT','GOOGL')]==[24000.,70000.,50000.]


def test_blank_zero_and_oversized_amounts_block_apply_without_crashing(app):
    amount_mode(app)
    before=app.session_state.active['calculated_at']
    app.number_input(key='amount_AAPL').set_value(None).run()
    assert not app.exception
    assert app.number_input(key='amount_AAPL').value is None
    assert app.button(key='analyze').disabled
    assert any('Enter every stock amount' in x.value for x in app.error)
    app.radio(key='allocation_mode').set_value('weight').run()
    assert app.radio(key='allocation_mode').value=='amount'
    for s in ('AAPL','MSFT','GOOGL'):
        app.number_input(key='amount_'+s).set_value(0.).run()
    assert not app.exception
    assert app.number_input(key='capital').value==0.
    assert app.button(key='analyze').disabled
    app.number_input(key='amount_AAPL').set_value(1e12).run()
    app.number_input(key='amount_MSFT').set_value(1e12).run()
    assert not app.exception
    assert app.number_input(key='capital').value==2e12
    assert app.button(key='analyze').disabled
    assert any('1 trillion' in x.value for x in app.error)
    assert app.session_state.active['calculated_at']==before


def test_amount_equal_split_and_stock_update_preserve_total(app):
    amount_mode(app)
    click(app,'Equal amounts')
    assert [app.number_input(key='amount_'+s).value for s in ('AAPL','MSFT','GOOGL')]==[33333.34,33333.33,33333.33]
    assert app.number_input(key='capital').value==100000.
    click(app,key='analyze')
    assert sum(app.session_state.active['config'].weights)==pytest.approx(100.)
    app.text_input(key='symbols').set_value('AAPL, NVDA').run()
    click(app,'Update list')
    assert app.number_input(key='amount_AAPL').value==50000.
    assert app.number_input(key='amount_NVDA').value==50000.
    click(app,key='analyze')
    assert app.session_state.active['config'].symbols==('AAPL','NVDA')
    assert app.session_state.active['config'].capital==100000.


def test_amount_snapshot_restores_exact_config_and_then_converts_back(app):
    amount_mode(app)
    app.number_input(key='amount_AAPL').set_value(12345.67).run()
    app.number_input(key='amount_MSFT').set_value(0.).run()
    click(app,key='analyze')
    saved_config=app.session_state.active['config']
    save(app,'Amount allocation')
    app.number_input(key='amount_AAPL').set_value(20000.).run()
    click(app,'Open full results')
    assert app.radio(key='allocation_mode').value=='weight'
    assert app.session_state.active['config']==saved_config
    assert not any('Unapplied' in x.value for x in app.warning)
    amount_mode(app)
    assert app.number_input(key='amount_AAPL').value==12345.67
    assert app.number_input(key='amount_MSFT').value==0.
    assert app.number_input(key='amount_GOOGL').value==25000.


def test_invalid_weight_or_empty_capital_cannot_be_hidden_by_mode_switch(app):
    app.number_input(key='weight_AAPL').set_value(None).run()
    assert not app.exception
    assert app.button(key='analyze').disabled
    amount_mode(app)
    assert app.radio(key='allocation_mode').value=='weight'
    click(app,'Equal weight')
    app.number_input(key='capital').set_value(None).run()
    assert not app.exception
    assert app.button(key='analyze').disabled
    app.number_input(key='capital').set_value(100000.).run()
    amount_mode(app)
    assert app.number_input(key='capital').value==100000.


def test_money_entry_rounds_cents_before_deriving_weights(app):
    amount_mode(app)
    app.number_input(key='amount_AAPL').set_value(1.005).run()
    assert app.number_input(key='amount_AAPL').value==1.01
    assert app.number_input(key='capital').value==60001.01
    click(app,key='analyze')
    config=app.session_state.active['config']
    assert config.capital*config.weights[0]/100==pytest.approx(1.01)


def test_hot_reload_migrates_existing_draft_with_a_changed_stock_list(app):
    app.text_input(key='symbols').set_value('AAPL, MSFT, GOOGL, NVDA').run()
    click(app,'Update list')
    del app.session_state['allocation_draft']
    app.run()
    assert not app.exception
    assert len(app.session_state.allocation_draft['weights'])==4
    assert app.number_input(key='weight_NVDA').value==25.
    amount_mode(app)
    assert app.number_input(key='amount_NVDA').value==25000.


def test_40_45_40_restores_clean_draft_and_all_completion(app):
    page(app,'Risk analysis');page(app,'Strategy comparison');save(app,'Original run')
    before=app.session_state.active
    completed=set(app.session_state.completed)
    page(app,'Overview')
    app.number_input(key='weight_AAPL').set_value(45.).run()
    assert app.session_state.completed==completed
    assert any('Weights total 105%. Reduce 5 percentage points' in x.value for x in app.error)
    assert app.button(key='main_apply').disabled
    assert app.session_state.active['calculated_at']==before['calculated_at']
    app.number_input(key='weight_AAPL').set_value(40.).run()
    assert app.session_state.completed==completed
    assert not any('Unapplied changes' in x.value for x in app.warning)
    assert not app.button(key='header_save').disabled
    assert 'aria-current="step">✓ Configure portfolio' in next(x.value for x in app.markdown if 'Experiment progress' in x.value)


def test_library_visit_is_not_a_save_and_dirty_page_highlight_is_independent(app):
    page(app,'Saved experiments')
    assert app.session_state.completed=={'Overview'}
    page(app,'Risk analysis')
    app.number_input(key='capital').set_value(150000.).run()
    html=next(x.value for x in app.markdown if 'Experiment progress' in x.value)
    assert 'aria-current="step">✓ Analyze risk' in html
    assert app.session_state.active['config'].capital==100000.


def test_failure_preserves_version_progress_and_reverting_clears_failure(app,monkeypatch):
    import market_data
    from models import ValidationError
    page(app,'Risk analysis');page(app,'Strategy comparison');save(app,'Before failure')
    completed=set(app.session_state.completed)
    before=app.session_state.active
    def fail(*a,**k):raise ValidationError('Test connection failure: retry later.')
    monkeypatch.setattr(market_data,'yahoo_prices',fail)
    app.selectbox(key='source').set_value('yahoo').run()
    click(app,key='main_apply')
    assert app.session_state.completed==completed
    assert app.session_state.active['calculated_at']==before['calculated_at']
    assert any('Test connection failure' in x.value for x in app.error)
    app.selectbox(key='source').set_value('demo').run()
    assert not app.session_state.analysis_error
    assert not app.button(key='header_save').disabled
    assert app.session_state.completed==completed


def test_inline_dates_and_symbols_are_actionable(app):
    app.date_input(key='end').set_value(date(2022,12,31)).run()
    assert app.button(key='analyze').disabled
    assert any('The end date must be later than the start date.' in x.value for x in app.error)
    app.date_input(key='end').set_value(date(2025,12,31)).run()
    app.text_input(key='symbols').set_value('AAPL, AAPL').run()
    assert app.button(key='analyze').disabled
    assert any('Select Update list' in x.value for x in app.warning)
    click(app,'Update list')
    assert any('Remove repeated symbols' in x.value for x in app.error)


def test_header_opens_naming_directly_and_save_failure_keeps_name(app,monkeypatch):
    import experiments
    page(app,'Risk analysis')
    click(app,key='header_save')
    assert app.text_input(key='experiment_name').value
    app.text_input(key='experiment_name').set_value('Keep my name').run()
    original=experiments.save_batch
    def fail(*a,**k):raise OSError('Disk is full')
    monkeypatch.setattr(experiments,'save_batch',fail)
    click(app,key='save_snapshot')
    assert app.text_input(key='experiment_name').value=='Keep my name'
    assert any('Disk is full' in x.value for x in app.error)
    assert 'Saved experiments' not in app.session_state.completed
    monkeypatch.setattr(experiments,'save_batch',original)
    click(app,key='save_snapshot')
    assert any('Keep my name' in x.value for x in app.success)
    assert any(b.label=='Download JSON' for b in app.get('download_button'))
    click(app,'View saved experiments')
    assert app.session_state.page=='Saved experiments'
    assert not app.session_state.show_save
    page(app,'Overview');click(app,key='header_save')
    assert app.text_input(key='experiment_name').value=='Keep my name'


def test_applied_source_context_updates_only_on_success(app,monkeypatch):
    import market_data
    from storage import export_records, import_records, make_record, restore_record
    original=app.session_state.active
    prices=original['prices'].copy()*1.1
    monkeypatch.setattr(market_data,'yahoo_prices',lambda *a,**k:(prices, ['Controlled Yahoo fixture']))
    app.selectbox(key='source').set_value('yahoo').run()
    assert any('still use Synthetic data (Demo)' in x.value for x in app.warning)
    assert any('Synthetic data · Demo' in x.value for x in app.markdown)
    click(app,key='main_apply')
    assert app.session_state.active['config'].source=='yahoo'
    assert app.session_state.completed=={'Overview'}
    assert any('Yahoo · Historical data' in x.value for x in app.markdown)
    assert any('Historical simulation' in x.value for x in app.markdown)
    pd=pytest.importorskip('pandas')
    pd.testing.assert_frame_equal(app.session_state.active['prices'],prices)
    save(app,'Yahoo fixture archive')
    record=next(iter(app.session_state.session_records.values()))
    imported=import_records(export_records([record]))[0]
    c,p,r=restore_record(imported)
    assert c==app.session_state.active['config']
    pd.testing.assert_frame_equal(p,prices,check_freq=False)
    for key in r:
        pd.testing.assert_series_equal(r[key].equity,app.session_state.active['results'][key].equity,check_freq=False)
        pd.testing.assert_frame_equal(r[key].trades,app.session_state.active['results'][key].trades)
    app.selectbox(key='source').set_value('demo').run()
    assert any('still use Yahoo Historical data' in x.value for x in app.warning)
    click(app,key='main_apply')
    assert app.session_state.active['config'].source=='demo'
    pd.testing.assert_frame_equal(app.session_state.active['prices'],original['prices'])
