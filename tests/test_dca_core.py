from copy import deepcopy
from decimal import Decimal as D
import json

import pytest
from models import ValidationError
from dca_core import (add_version, correct_batch, create_plan, export_backup, history_csv, import_backup,
                      period_amount, record_purchase, replay, schedule, suggest, summarize, target_value, validate_config)


def config(**changes):
    return dict(name='Hand calculation', strategy='DCA', funding='fixed', symbols=['AAA', 'BBB'],
                weights=[60, 40], first_date='2024-01-31', frequency='monthly', total_budget='1000',
                periods=2, reserve_fraction='0.2', contribution='100', annual_target='0', **{}) | changes


def quotes(aaa=100, bbb=30, date='2024-01-31'):
    return {s: dict(price=str(price), date=date, updated_at=date+'T21:00:00+00:00', source='manual fixture', manual=True)
            for s, price in [('AAA', aaa), ('BBB', bbb)]}


def trades(shares='2', price='100', fee='0', symbol='AAA'):
    return [dict(symbol=symbol, shares=shares, price=price, fee=fee)]


def buy(book, request_id='first', **changes):
    args = dict(request_id=request_id, period=1, actual_date='2024-01-31', trades=trades())
    args.update(changes)
    return record_purchase(book, **args)


def test_schedule_anchor_and_final_cent_remainder():
    cfg = config(periods=3, total_budget='100', reserve_fraction='0')
    assert [schedule(cfg, p).isoformat() for p in (1, 2, 3)] == ['2024-01-31', '2024-02-29', '2024-03-31']
    assert [period_amount(cfg, p) for p in (1, 2, 3)] == [D('33.33'), D('33.33'), D('33.34')]
    assert schedule(config(frequency='biweekly'), 2).isoformat() == '2024-02-14'


@pytest.mark.parametrize('changes', [dict(weights=[60, 45]), dict(symbols=['AAA', 'AAA']), dict(periods=0),
    dict(reserve_fraction=1), dict(first_date='2024-02-30'), dict(annual_target=-1), dict(total_budget=-1)])
def test_invalid_config(changes):
    with pytest.raises(ValidationError):
        create_plan(config(**changes))


def test_fixed_dca_hand_cash_and_reserve_suggestion_does_not_record():
    book = create_plan(config()); original = deepcopy(book)
    suggestion = suggest(book, quotes(), as_of='2024-01-31')
    assert [r['shares'] for r in suggestion['rows']] == [2, 5]
    assert suggestion['estimated_spend'] == 350
    assert suggestion['remaining_available_cash'] == 450
    assert book == original
    batch = trades() + trades('5', '30', symbol='BBB')
    saved = buy(book, trades=batch)
    state = summarize(saved, quotes(), as_of='2024-01-31')
    assert state['portfolio_value'] == 350
    assert state['cash'] == 650 and state['reserve'] == 200 and state['available_cash'] == 450
    assert state['contributed'] == 1000 and state['investment_gain'] == 0
    assert state['next_period'] == 2


def test_ongoing_fees_cash_and_real_simulated_lanes():
    book = create_plan(config(funding='ongoing', weights=[100, 0]))
    saved = buy(book, trades=trades('3', '30', fee='1'), deposit='100')
    state = summarize(saved, quotes(aaa=40), as_of='2024-01-31')
    assert state['cash'] == 9
    assert state['portfolio_value'] == 120 and state['investment_gain'] == 29
    assert state['fees'] == 1 and state['contributed'] == 100
    assert replay(saved, 'simulated')['cash'] == 0
    again = buy(saved, request_id='simulation', lane='simulated', trades=trades('1', '30'), deposit='100')
    assert replay(again, 'simulated')['cash'] == 70
    assert replay(again)['cash'] == 9
    with pytest.raises(ValidationError, match='additional'):
        buy(book, deposit=200)
    assert replay(buy(book, deposit=200, allow_extra=True))['contributed'] == 200


def test_purchase_duplicate_idempotency_and_reserve_checks():
    book = create_plan(config())
    saved = buy(book)
    assert buy(saved) == saved
    with pytest.raises(ValidationError, match='different action'):
        buy(saved, trades=trades('3'))
    with pytest.raises(ValidationError, match='reserve'):
        buy(book, trades=trades('8', fee='1'))
    with pytest.raises(ValidationError, match='decimal'):
        buy(book, trades=trades('1.001'))
    with pytest.raises(ValidationError, match='sequentially'):
        buy(book, period=2, actual_date='2024-02-29')


def test_missing_future_quotes_and_old_valuation_dates():
    book = create_plan(config())
    with pytest.raises(ValidationError, match='BBB'):
        suggest(book, {'AAA': quotes()['AAA']}, as_of='2024-01-31')
    with pytest.raises(ValidationError, match='later'):
        suggest(book, quotes(date='2024-02-01'), as_of='2024-01-31')
    saved = buy(book)
    with pytest.raises(ValidationError, match='precedes'):
        summarize(saved, quotes(date='2024-01-30'), as_of='2024-01-30')


def test_va_no_selling_positive_gap_proportional_cap():
    book = create_plan(config(strategy='VA', funding='ongoing', weights=[100, 0]))
    saved = buy(book, trades=trades('1', '100'), deposit='100')
    above = suggest(saved, quotes(aaa=250), as_of='2024-02-29')
    assert above['target_value'] == 200
    assert above['estimated_spend'] == 0 and above['rows'][0]['shares'] == 0
    # Two equal gaps: target200, initial holdings zero, only100 deposited.
    book = create_plan(config(strategy='VA', funding='ongoing', weights=[50, 50]))
    skipped = buy(book, trades=[], timing='skipped')
    capped = suggest(skipped, quotes(aaa=10, bbb=10), as_of='2024-02-29')
    assert capped['scaled_for_cash']
    assert [r['shares'] for r in capped['rows']] == [5, 5]
    assert capped['unfilled_gap'] == 100
    assert capped['remaining_available_cash'] == 0


def test_va_actual_day_growth_and_fee_safe_rounding():
    book = create_plan(config(strategy='VA', funding='ongoing', annual_target='.1'))
    expected = D(100) * D('1.1') ** (D(29)/365) + 100
    assert target_value(book, 2) == expected.quantize(D('.01'))
    book = create_plan(config(funding='ongoing', weights=[50, 50], contribution='.03'))
    suggestion = suggest(book, quotes(aaa='.01', bbb='.01'), as_of='2024-01-31', fee_rate='.5')
    assert suggestion['estimated_spend'] <= D('.03')


def test_early_late_and_explicit_skip():
    book = create_plan(config())
    with pytest.raises(ValidationError, match='Explicitly mark'):
        buy(book, actual_date='2024-01-30')
    assert replay(buy(book, actual_date='2024-01-30', timing='early'))['next_period'] == 2
    assert replay(buy(book, actual_date='2024-02-01', timing='late'))['next_period'] == 2
    assert replay(buy(book, trades=[], timing='skipped'))['holdings']['AAA'] == 0


def test_corrections_replay_and_keep_audit_and_reject_downstream_overspend():
    saved = buy(create_plan(config(funding='ongoing')), deposit='100', trades=trades('1', '50'))
    saved = buy(saved, request_id='second', period=2, actual_date='2024-02-29', deposit='100', trades=trades('2', '70'))
    assert replay(saved)['cash'] == 10
    replacement = deepcopy(saved['events'][0]['batch']); replacement['trades'] = trades('1', '60')
    corrected = correct_batch(saved, request_id='fix', period=1, reason='Correct execution price', replacement=replacement)
    assert replay(corrected)['cash'] == 0 and len(corrected['events']) == 3
    assert corrected['events'][0]['batch']['trades'][0]['price'] == '50'
    replacement['trades'] = trades('1', '61')
    with pytest.raises(ValidationError, match='cash'):
        correct_batch(saved, request_id='bad-fix', period=1, reason='Would overspend', replacement=replacement)
    # Voiding first batch also removes its contribution; later purchase then lacks funding.
    with pytest.raises(ValidationError, match='cash'):
        correct_batch(saved, request_id='bad-void', period=1, reason='Void')
    fixed = buy(create_plan(config()))
    voided = correct_batch(fixed, request_id='void', period=1, reason='Duplicate manual trade')
    assert replay(voided)['cash'] == 1000 and replay(voided)['next_period'] == 2
    assert len(voided['events']) == 2


def test_future_version_preserves_past_and_json_full_replay():
    saved = buy(create_plan(config()))
    updated = add_version(saved, config(weights=[40, 60]), effective_period=2)
    assert replay(updated)['holdings'] == replay(saved)['holdings']
    suggestion = suggest(updated, quotes(), as_of='2024-02-29')
    assert [r['allocation'] for r in suggestion['rows']] == [160, 240]
    raw = export_backup(updated)
    restored = import_backup(raw, mode='replace', existing_id=updated['plan_id'])
    assert restored == updated and replay(restored) == replay(updated)
    cloned = import_backup(raw, mode='new')
    assert cloned['plan_id'] != updated['plan_id'] and cloned['origin_id'] == updated['plan_id']
    assert replay(cloned) == replay(updated)
    assert 'AAA,2,100,0' in history_csv(cloned)
    with pytest.raises(ValidationError):
        import_backup(raw, mode='replace', existing_id='wrong')
    with pytest.raises(ValidationError):
        add_version(saved, config(weights=[40, 60]), effective_period=1)
    with pytest.raises(ValidationError):
        add_version(saved, config(total_budget='2000'), effective_period=2)


def test_backup_rejects_bad_ledger_unknown_actions_and_duplicates():
    book = buy(create_plan(config()))
    corrupt = deepcopy(book); corrupt['events'][0]['batch']['trades'][0]['shares'] = '100'
    with pytest.raises(ValidationError, match='reserve'):
        import_backup(json.dumps(corrupt).encode(), mode='new')
    corrupt = deepcopy(book); corrupt['events'].append(deepcopy(corrupt['events'][0]))
    with pytest.raises(ValidationError, match='duplicate'):
        import_backup(json.dumps(corrupt).encode(), mode='new')
    corrupt = deepcopy(book); corrupt['corporate_actions'] = [{'split': 2}]
    with pytest.raises(ValidationError, match='Corporate'):
        import_backup(json.dumps(corrupt).encode(), mode='new')


def test_valuation_history_uses_supplied_dates_and_replayed_holdings():
    from dca_core import valuation_history
    book = buy(create_plan(config(funding='ongoing')), trades=trades('1', '100'), deposit='100')
    book = buy(book, request_id='second', period=2, actual_date='2024-02-29', trades=trades('1', '110'), deposit='110', allow_extra=True)
    history = valuation_history(book, {'2024-01-31': quotes(aaa=100), '2024-02-29': quotes(aaa=110, date='2024-02-29')})
    assert [h['portfolio_value'] for h in history] == [100, 220]
    assert [h['contributed'] for h in history] == [100, 210]
    assert [h['investment_gain'] for h in history] == [0, 10]


@pytest.mark.parametrize('changes', [dict(period=True), dict(period=0), dict(allow_extra='yes')])
def test_record_rejects_ambiguous_input_types(changes):
    with pytest.raises(ValidationError):
        buy(create_plan(config()), **changes)
