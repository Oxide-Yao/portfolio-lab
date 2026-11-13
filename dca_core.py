"""Pure, buy-only USD planning and append-only manual ledger; never places orders.

Amounts use Decimal cents, actual quantities <=2 decimal places, suggestions
whole shares. Actual and simulated lanes each have independent funding/cash.
"""
from calendar import monthrange
from copy import deepcopy
from datetime import date, timedelta, datetime
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP
import csv
import io
import json
from uuid import uuid4

from analytics_core import symbols_checked
from models import ValidationError

CENT = Decimal('0.01')
SCHEMA = 'portfolio-lab-dca-1'


def number(value, *, positive=False, cents=False):
    if isinstance(value, bool):
        raise ValidationError('Use a finite number.')
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValidationError('Use a finite number.') from exc
    if not result.is_finite() or abs(result) > Decimal('1e15') or result < 0 or (positive and result == 0):
        raise ValidationError('Use a finite non-negative amount (positive where required).')
    if cents and result != result.quantize(CENT):
        raise ValidationError('Use no more than two decimal places.')
    return result


def money(value):
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def day(value):
    try:
        if isinstance(value, str) and date.fromisoformat(value).isoformat() == value:
            return date.fromisoformat(value)
    except ValueError:
        pass
    raise ValidationError('Use an ISO date: YYYY-MM-DD.')


def validate_config(config):
    fields = {'name', 'strategy', 'funding', 'symbols', 'weights', 'first_date', 'frequency',
              'total_budget', 'periods', 'reserve_fraction', 'contribution', 'annual_target'}
    if not isinstance(config, dict) or set(config) != fields:
        raise ValidationError('Invalid plan configuration fields.')
    if not isinstance(config['name'], str) or not config['name'].strip():
        raise ValidationError('Enter a plan name.')
    symbols_checked(config['symbols'])
    if not isinstance(config['weights'], list) or len(config['weights']) != len(config['symbols']):
        raise ValidationError('Provide one weight for each stock.')
    weights = [number(x) for x in config['weights']]
    if sum(weights) != 100:
        raise ValidationError('Target weights must total 100%.')
    if config['strategy'] not in ('DCA', 'VA') or config['funding'] not in ('fixed', 'ongoing'):
        raise ValidationError('Choose DCA/VA and fixed/ongoing funding.')
    if config['frequency'] not in ('monthly', 'biweekly'):
        raise ValidationError('Choose monthly or biweekly.')
    day(config['first_date'])
    if type(config['periods']) is not int or not 1 <= config['periods'] <= 1200:
        raise ValidationError('Periods must be an integer from 1 to 1200 (planning horizon for ongoing funding).')
    number(config['total_budget'], positive=config['funding'] == 'fixed', cents=True)
    number(config['contribution'], positive=config['funding'] == 'ongoing', cents=True)
    if number(config['reserve_fraction']) >= 1:
        raise ValidationError('Reserve must be from 0% to less than 100%.')
    try:
        rate = Decimal(str(config['annual_target']))
        if isinstance(config['annual_target'], bool) or not rate.is_finite() or not -1 < rate <= 10:
            raise ValueError
    except (InvalidOperation, ValueError):
        raise ValidationError('Annual target must be greater than -100% and no more than 1000%.')
    return config


def schedule(config, period):
    validate_config(config)
    if type(period) is not int or not 1 <= period <= config['periods']:
        raise ValidationError('Period is outside the configured planning horizon.')
    first = day(config['first_date'])
    if config['frequency'] == 'biweekly':
        return first + timedelta(days=14 * (period - 1))
    serial = first.year * 12 + first.month - 1 + period - 1
    year, month = divmod(serial, 12)
    month += 1
    return date(year, month, min(first.day, monthrange(year, month)[1]))


def reserve(config):
    return money(number(config['total_budget']) * number(config['reserve_fraction'])) if config['funding'] == 'fixed' else Decimal(0)


def period_amount(config, period):
    schedule(config, period)
    if config['funding'] == 'ongoing':
        return number(config['contribution'])
    investable = number(config['total_budget']) - reserve(config)
    base = (investable / config['periods']).quantize(CENT, rounding=ROUND_DOWN)
    return investable - base * (period - 1) if period == config['periods'] else base


def create_plan(config):
    validate_config(config)
    return {'schema': SCHEMA, 'plan_id': str(uuid4()), 'origin_id': None,
            'versions': [{'effective_period': 1, 'config': deepcopy(config)}],
            'events': [], 'corporate_actions': []}


def config_for(book, period):
    return next(v['config'] for v in reversed(book['versions']) if v['effective_period'] <= period)


def lane_checked(lane):
    if lane not in ('actual', 'simulated'):
        raise ValidationError('Choose actual or simulated records.')


def effective_batches(book, lane):
    lane_checked(lane)
    batches = []
    for event in book['events']:
        if event['lane'] != lane:
            continue
        if event['kind'] == 'record':
            batches.append(deepcopy(event['batch']))
        else:
            target = next((b for b in batches if b['period'] == event['period']), None)
            if target is None:
                raise ValidationError('Correction must reference an earlier recorded period.')
            if event['kind'] == 'correct':
                target.clear(); target.update(deepcopy(event['batch']))
            elif event['kind'] == 'void':
                target['trades'] = []; target['deposit'] = '0'; target['timing'] = 'skipped'; target['voided'] = True
            else:
                raise ValidationError('Unsupported ledger action.')
    return batches


def replay(book, lane='actual'):
    lane_checked(lane)
    first = config_for(book, 1)
    cash = number(first['total_budget']) if first['funding'] == 'fixed' else Decimal(0)
    contributed, fees = cash, Decimal(0)
    quantities = dict.fromkeys(first['symbols'], Decimal(0))
    last_date = None
    batches = effective_batches(book, lane)
    for expected, batch in enumerate(batches, 1):
        if batch['period'] != expected:
            raise ValidationError('Record periods sequentially; explicitly skip an unused period.')
        config = config_for(book, expected)
        scheduled, actual = schedule(config, expected), day(batch['date'])
        timing = 'early' if actual < scheduled else 'late' if actual > scheduled else 'on_schedule'
        if batch['timing'] not in (timing, 'skipped') or (batch['timing'] == 'skipped' and batch['trades']):
            raise ValidationError('Explicitly mark early, late, on_schedule or skipped records.')
        if last_date is not None and actual < last_date:
            raise ValidationError('Record dates must be chronological.')
        last_date = actual
        deposit = number(batch['deposit'], cents=True)
        if config['funding'] == 'fixed' and deposit:
            raise ValidationError('Fixed budgets cannot receive additional contributions.')
        if type(batch['allow_extra']) is not bool:
            raise ValidationError('Additional funding requires an explicit choice.')
        if config['funding'] == 'ongoing' and deposit > period_amount(config, expected) and not batch['allow_extra']:
            raise ValidationError('Explicitly allow the additional contribution.')
        cash += deposit; contributed += deposit
        seen = set()
        for trade in batch['trades']:
            if set(trade) != {'symbol', 'shares', 'price', 'fee'} or trade['symbol'] not in quantities or trade['symbol'] in seen:
                raise ValidationError('Use one purchase per configured stock in each batch.')
            seen.add(trade['symbol'])
            shares = number(trade['shares'], positive=True, cents=True)
            price = number(trade['price'], positive=True)
            fee = number(trade['fee'], cents=True)
            cash -= money(shares * price) + fee
            fees += fee; quantities[trade['symbol']] += shares
        if cash < reserve(config):
            raise ValidationError('Purchases and fees exceed available cash or spend the protected reserve.')
    return {'cash': cash, 'available_cash': cash - reserve(first), 'reserve': reserve(first),
            'contributed': contributed, 'fees': fees, 'holdings': quantities,
            'completed_periods': len(batches), 'next_period': len(batches) + 1, 'batches': batches}


def quotes_checked(quotes, symbols, as_of):
    as_of = day(as_of)
    if not isinstance(quotes, dict) or set(quotes) != set(symbols):
        missing = sorted(set(symbols) - set(quotes or {}))
        raise ValidationError('Provide prices for every asset. Missing: ' + ', '.join(missing))
    values = {}
    for symbol, quote in quotes.items():
        if set(quote) != {'price', 'date', 'updated_at', 'source', 'manual'}:
            raise ValidationError('Each quote needs price, date, updated_at, source and manual status.')
        if day(quote['date']) > as_of:
            raise ValidationError('Quote dates cannot be later than the valuation date.')
        try:
            stamp = datetime.fromisoformat(quote['updated_at'])
            if stamp.tzinfo is None:
                raise ValueError
        except (TypeError, ValueError):
            raise ValidationError('Quote update time must be an ISO timestamp with timezone.')
        if type(quote['manual']) is not bool or not isinstance(quote['source'], str) or not quote['source'].strip():
            raise ValidationError('Specify quote source and manual status.')
        values[symbol] = number(quote['price'], positive=True)
    return values


def target_value(book, period):
    schedule(config_for(book, period), period)
    target = Decimal(0)
    for p in range(1, period + 1):
        config = config_for(book, p)
        if p > 1:
            previous = config_for(book, p - 1)
            elapsed = (schedule(config, p) - schedule(previous, p - 1)).days
            factor = (1 + Decimal(str(config['annual_target']))) ** (Decimal(elapsed) / 365)
            target *= factor
        target += period_amount(config, p)
    return money(target)


def suggest(book, quotes, *, as_of, lane='actual', deposit=None, allow_extra=False, fee_rate='0'):
    if type(allow_extra) is not bool:
        raise ValidationError('Additional funding requires an explicit boolean choice.')
    state = replay(book, lane)
    period = state['next_period']; config = config_for(book, period)
    base = period_amount(config, period)
    prices = quotes_checked(quotes, config['symbols'], as_of)
    if state['batches'] and day(as_of) < day(state['batches'][-1]['date']):
        raise ValidationError('Valuation date precedes the latest purchase. Supply a current valuation date.')
    funding = base if deposit is None and config['funding'] == 'ongoing' else number(deposit or 0, cents=True)
    if (config['funding'] == 'fixed' and funding) or (config['funding'] == 'ongoing' and funding > base and not allow_extra):
        raise ValidationError('Additional funding must be explicitly allowed and is only supported for ongoing plans.')
    fee = number(fee_rate)
    if fee > 1:
        raise ValidationError('Fee rate cannot exceed 100%.')
    available = state['available_cash'] + funding
    target = target_value(book, period) if config['strategy'] == 'VA' else base
    gaps = {}
    for symbol, weight in zip(config['symbols'], config['weights']):
        allocation = target * number(weight) / 100
        gaps[symbol] = max(Decimal(0), allocation - state['holdings'][symbol] * prices[symbol]) if config['strategy'] == 'VA' else allocation
    total_gap = sum(gaps.values())
    cap = available if config['strategy'] == 'VA' else min(base, available)
    scale = min(Decimal(1), cap / (total_gap * (1 + fee))) if total_gap else Decimal(1)
    rows = []
    for symbol, gap in gaps.items():
        allocation = gap * scale
        shares = int(allocation / prices[symbol])
        cost = money(shares * prices[symbol]); charge = money(cost * fee)
        rows.append({'symbol': symbol, 'target_gap': gap, 'allocation': allocation, 'shares': shares,
                     'price': prices[symbol], 'cost': cost, 'estimated_fee': charge})
    # Per-asset cent rounding must never take the combined cost above the cap.
    while sum(r['cost'] + r['estimated_fee'] for r in rows) > cap:
        row = next(r for r in reversed(rows) if r['shares'])
        row['shares'] -= 1; row['cost'] = money(row['shares'] * row['price']); row['estimated_fee'] = money(row['cost'] * fee)
    spend = sum(r['cost'] + r['estimated_fee'] for r in rows)
    return {'period': period, 'scheduled_date': schedule(config, period).isoformat(), 'rows': rows,
            'planned_deposit': funding, 'target_value': target, 'estimated_spend': spend,
            'remaining_available_cash': available - spend, 'unfilled_gap': total_gap - sum(r['cost'] for r in rows),
            'scaled_for_cash': scale < 1, 'quotes': deepcopy(quotes), 'as_of': as_of,
            'note': 'Whole-share suggestion only; no transaction recorded or order placed. Fees are estimates.'}


def append_event(book, event):
    lane_checked(event['lane'])
    if event['kind'] not in ('record', 'correct', 'void'):
        raise ValidationError('Unsupported ledger action.')
    if 'batch' in event:
        batch = event['batch']
        if (not isinstance(batch, dict) or set(batch) != {'period', 'date', 'trades', 'deposit', 'timing', 'allow_extra'}
                or type(batch['period']) is not int or batch['period'] < 1 or not isinstance(batch['trades'], list)):
            raise ValidationError('Invalid purchase batch.')
    if event['kind'] != 'record' and (type(event['period']) is not int or event['period'] < 1):
        raise ValidationError('Correction period must be a positive integer.')
    request_id = event['request_id']
    if not isinstance(request_id, str) or not request_id.strip():
        raise ValidationError('Provide a unique request ID.')
    existing = next((e for e in book['events'] if e['request_id'] == request_id), None)
    if existing:
        if existing != event:
            raise ValidationError('Request ID already belongs to a different action.')
        return deepcopy(book)
    result = deepcopy(book); result['events'].append(deepcopy(event))
    replay(result, event['lane'])
    return result


def record_purchase(book, *, request_id, period, actual_date, trades, deposit='0',
                    timing='on_schedule', lane='actual', allow_extra=False):
    lane_checked(lane)
    batch = {'period': period, 'date': actual_date, 'trades': deepcopy(trades), 'deposit': str(deposit),
             'timing': timing, 'allow_extra': allow_extra}
    return append_event(book, {'kind': 'record', 'request_id': request_id, 'lane': lane, 'batch': batch})


def correct_batch(book, *, request_id, period, reason, replacement=None, lane='actual'):
    if not isinstance(reason, str) or not reason.strip():
        raise ValidationError('Explain the correction or void.')
    event = {'kind': 'void' if replacement is None else 'correct', 'request_id': request_id,
             'lane': lane, 'period': period, 'reason': reason}
    if replacement is not None:
        if replacement.get('period') != period:
            raise ValidationError('A correction must retain its original period.')
        event['batch'] = deepcopy(replacement)
    return append_event(book, event)


def add_version(book, config, *, effective_period):
    validate_config(config)
    latest = book['versions'][-1]
    completed = max(replay(book, lane)['completed_periods'] for lane in ('actual', 'simulated'))
    if type(effective_period) is not int or effective_period <= max(completed, latest['effective_period']):
        raise ValidationError('New versions must start in an unrecorded future period.')
    schedule(config, effective_period)
    allowed = {'name', 'weights', 'annual_target', 'strategy'}
    if any(config[k] != latest['config'][k] for k in set(config) - allowed):
        raise ValidationError('Create a new plan to change funding, schedule or assets.')
    result = deepcopy(book)
    result['versions'].append({'effective_period': effective_period, 'config': deepcopy(config)})
    return result


def summarize(book, quotes, *, as_of, lane='actual'):
    state = replay(book, lane)
    prices = quotes_checked(quotes, list(state['holdings']), as_of)
    if state['batches'] and day(as_of) < day(state['batches'][-1]['date']):
        raise ValidationError('Valuation date precedes the latest purchase.')
    values = {s: q * prices[s] for s, q in state['holdings'].items()}
    value = sum(values.values())
    return {**state, 'portfolio_value': value, 'asset_values': values,
            'investment_gain': value + state['cash'] - state['contributed'],
            'as_of': as_of, 'quotes': deepcopy(quotes), 'lane': lane,
            'note': 'Point-in-time valuation; fees are already deducted from cash. No annualized return.'}


def export_backup(book):
    validate_book(book)
    return json.dumps(book, ensure_ascii=False, allow_nan=False).encode()


def validate_book(book):
    if not isinstance(book, dict) or set(book) != {'schema', 'plan_id', 'origin_id', 'versions', 'events', 'corporate_actions'} or book['schema'] != SCHEMA:
        raise ValidationError('Unsupported planner backup schema.')
    if not isinstance(book['plan_id'], str) or not book['plan_id'] or (book['origin_id'] is not None and not isinstance(book['origin_id'], str)):
        raise ValidationError('Invalid plan identity.')
    if not isinstance(book['versions'], list) or not book['versions'] or not isinstance(book['events'], list) or len(book['events']) > 10000:
        raise ValidationError('Invalid versions or too many ledger events.')
    if book['corporate_actions'] != []:
        raise ValidationError('Corporate actions are reserved for a later schema; adjusted-price double processing is not supported.')
    first = book['versions'][0]
    if set(first) != {'effective_period', 'config'} or type(first['effective_period']) is not int or first['effective_period'] != 1:
        raise ValidationError('First version must start at period 1.')
    rebuilt = create_plan(first['config'])
    for version in book['versions'][1:]:
        if set(version) != {'effective_period', 'config'}:
            raise ValidationError('Invalid version fields.')
        rebuilt = add_version(rebuilt, version['config'], effective_period=version['effective_period'])
    ids = set()
    for event in book['events']:
        kind = event.get('kind')
        required = {'kind', 'request_id', 'lane', 'batch'} if kind == 'record' else {'kind', 'request_id', 'lane', 'period', 'reason'} | ({'batch'} if kind == 'correct' else set())
        if kind not in ('record', 'correct', 'void') or set(event) != required or event['request_id'] in ids:
            raise ValidationError('Invalid or duplicate ledger event.')
        ids.add(event['request_id'])
        if kind != 'record' and (not isinstance(event['reason'], str) or not event['reason'].strip()):
            raise ValidationError('Corrections require a reason.')
        if 'batch' in event:
            batch = event['batch']
            if set(batch) != {'period', 'date', 'trades', 'deposit', 'timing', 'allow_extra'} or type(batch['period']) is not int or not isinstance(batch['trades'], list):
                raise ValidationError('Invalid batch fields.')
            if kind == 'correct' and batch['period'] != event['period']:
                raise ValidationError('Correction period mismatch.')
        rebuilt = append_event(rebuilt, event)
    for lane in ('actual', 'simulated'):
        replay(rebuilt, lane)
    return book


def import_backup(raw, *, mode, existing_id=None):
    if not isinstance(raw, bytes) or len(raw) > 8 * 1024 * 1024:
        raise ValidationError('Provide a JSON backup of at most 8 MB.')
    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValidationError('Duplicate JSON key.')
            result[k] = v
        return result
    try:
        book = json.loads(raw, object_pairs_hook=unique)
        validate_book(book)
        if mode == 'new':
            book['origin_id'] = book['plan_id']; book['plan_id'] = str(uuid4())
        elif mode != 'replace' or existing_id != book['plan_id']:
            raise ValidationError('Select new or explicitly replace the matching plan ID.')
        return book
    except (ValueError, TypeError, KeyError, AttributeError, InvalidOperation) as exc:
        raise ValidationError(f'Cannot import planner backup: {exc}') from exc


def history_csv(book, lane='actual'):
    output = io.StringIO()
    fields = ['period', 'scheduled_date', 'actual_date', 'lane', 'timing', 'deposit', 'symbol', 'shares', 'price', 'fee']
    writer = csv.DictWriter(output, fieldnames=fields); writer.writeheader()
    for batch in replay(book, lane)['batches']:
        base = {'period': batch['period'], 'scheduled_date': schedule(config_for(book, batch['period']), batch['period']).isoformat(),
                'actual_date': batch['date'], 'lane': lane, 'timing': batch['timing'], 'deposit': batch['deposit']}
        for i, trade in enumerate(batch['trades'] or [{}]):
            writer.writerow({**base, 'deposit': base['deposit'] if i == 0 else '', **trade})
    return output.getvalue()


def valuation_history(book, quotes_by_date, *, lane='actual'):
    """Revised-ledger valuations only on explicitly supplied quote dates.

    No daily interpolation or invented prices. Includes corrections in the
    current audit view; the original event log remains available separately.
    Caller supplies all asset quotes for every desired daily/record-date point.
    """
    if not isinstance(quotes_by_date, dict) or not quotes_by_date:
        raise ValidationError('Provide explicit dated quote snapshots for historical valuations.')
    batches = replay(book, lane)['batches']
    history = []
    for as_of in sorted(quotes_by_date):
        day(as_of)
        historical = deepcopy(book); historical['events'] = []
        for batch in batches:
            if batch['date'] <= as_of:
                effective = {k: v for k, v in batch.items() if k != 'voided'}
                historical['events'].append({'kind': 'record', 'request_id': f"history-{batch['period']}",
                                             'lane': lane, 'batch': effective})
        state = summarize(historical, quotes_by_date[as_of], as_of=as_of, lane=lane)
        history.append({'date': as_of, 'portfolio_value': state['portfolio_value'], 'cash': state['cash'],
                        'contributed': state['contributed'], 'investment_gain': state['investment_gain'],
                        'fees': state['fees'], 'quote_basis': 'Explicit quote snapshot; no interpolation'})
    return history
