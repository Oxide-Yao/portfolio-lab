"""Portfolio Lab: template-inspired interface over the verified calculation engine."""
from datetime import date, datetime, timezone
from html import escape
import json
import os
from zoneinfo import ZoneInfo

import streamlit as st

from allocation import MAX_CAPITAL, amount_total, amounts_from_weights, money, resolve_allocation
from experiments import experiment_page
from market_data import DEMO_END, DEMO_START, load_prices
from models import AnalysisConfig, ValidationError, parse_inputs
from storage import SQLiteStore, restore_record
from trading_strategy import STRATEGIES, analyze
from ui import CSS, method_page, overview, risk_page, strategy_page
from workflow import PAGES, progress_html, update_progress

st.set_page_config(page_title="Portfolio Lab · Stock portfolio strategy lab", page_icon="⚗", layout="wide", initial_sidebar_state="expanded")
st.markdown(CSS, unsafe_allow_html=True)


def compute(config):
    prices, notes = load_prices(config)
    return {"config": config, "prices": prices, "results": analyze(prices, config), "notes": notes,
            "calculated_at": datetime.now(timezone.utc).isoformat(), "name": None}


def set_draft(config):
    st.session_state.update(symbols=", ".join(config.symbols), configured_symbols=tuple(config.symbols),
        capital=float(config.capital), start=date.fromisoformat(config.start), end=date.fromisoformat(config.end),
        source=config.source, short=config.short_window, long=config.long_window,
        take_profit=config.take_profit * 100, stop_loss=config.stop_loss * 100,
        hold_days=config.max_hold_days, fee=config.fee * 100, symbol_error=None,
        allocation_mode='weight', allocation_switch_error=None,
        allocation_draft={'mode':'weight', 'capital':float(config.capital),
            'weights':list(config.weights),
            'amounts':list(amounts_from_weights(config.capital, config.weights))})


def allocation_edited(kind, index=None):
    allocation = st.session_state.allocation_draft
    if kind == 'capital':
        allocation['capital'] = money(st.session_state.capital)
        st.session_state.capital = allocation['capital']
    else:
        symbol = st.session_state.configured_symbols[index]
        value = st.session_state[kind + '_' + symbol]
        if kind == 'amount':
            value = money(value)
            st.session_state['amount_' + symbol] = value
        allocation[kind + 's'][index] = value
    st.session_state.allocation_switch_error = None


def allocation_mode_changed():
    allocation = st.session_state.allocation_draft
    old_mode, new_mode = allocation['mode'], st.session_state.allocation_mode
    try:
        capital, weights = resolve_allocation(old_mode, allocation[old_mode + 's'], allocation['capital'])
    except ValidationError as exc:
        st.session_state.allocation_mode = old_mode
        st.session_state.allocation_switch_error = 'Complete the current allocation before switching modes. ' + str(exc)
        return
    if new_mode == 'amount':
        allocation['amounts'] = list(amounts_from_weights(capital, weights))
    else:
        allocation['weights'] = list(weights)
        allocation['capital'] = capital
    allocation['mode'] = new_mode
    st.session_state.allocation_switch_error = None


def update_symbols():
    try:
        symbols = tuple(s.strip().upper() for s in st.session_state.symbols.replace('，', ',').split(','))
        weights = tuple(100 / len(symbols) for _ in symbols)
        AnalysisConfig(symbols=symbols, weights=weights).validate()
        st.session_state.configured_symbols = symbols
        st.session_state.symbols = ', '.join(symbols)
        allocation = st.session_state.allocation_draft
        allocation['weights'] = list(weights)
        total = amount_total(allocation['amounts']) if allocation['mode'] == 'amount' else allocation['capital']
        allocation['amounts'] = list(amounts_from_weights(total or 0, weights))
        st.session_state.allocation_switch_error = None
        st.session_state.symbol_error = None
    except ValidationError as exc:
        st.session_state.symbol_error = str(exc)


def equal_allocation():
    allocation = st.session_state.allocation_draft
    count = len(st.session_state.configured_symbols)
    if allocation['mode'] == 'amount':
        allocation['amounts'] = list(amounts_from_weights(amount_total(allocation['amounts']), [1] * count))
    else:
        allocation['weights'] = [100 / count] * count
    st.session_state.allocation_switch_error = None


if 'initialized' not in st.session_state:
    set_draft(AnalysisConfig())
    st.session_state.update(initialized=True, page='Overview', session_records={}, analysis_error=None,
        completed={'Overview'}, viewed_strategy='hold', last_draft_signature=None)
    # A reproducible offline example is calculated once; page navigation does not fetch prices.
    st.session_state.active = compute(AnalysisConfig())

# Keep existing browser sessions usable after this version is deployed.
if 'allocation_draft' not in st.session_state:
    config = st.session_state.active['config']
    previous_weights = dict(zip(config.symbols, config.weights))
    weights = [st.session_state.get('weight_' + s, previous_weights.get(s, 100 / len(st.session_state.configured_symbols)))
               for s in st.session_state.configured_symbols]
    st.session_state.update(allocation_mode='weight', allocation_switch_error=None,
        allocation_draft={'mode':'weight', 'capital':st.session_state.capital,
            'weights':weights, 'amounts':[0.] * len(weights)})

if 'pending_record' in st.session_state:
    record = st.session_state.pop('pending_record')
    restored_config, restored_prices, restored_results = restore_record(record)
    set_draft(restored_config)
    st.session_state.active = {'config':restored_config, 'prices':restored_prices, 'results':restored_results,
        'notes':record['notes'], 'calculated_at':record['calculated_at'], 'name':record['name']}
    st.session_state.update(analysis_error=None, completed={'Overview'}, last_draft_signature=None,
                            viewed_strategy='hold')

store = None
storage_error = None
if os.environ.get('PORTFOLIO_STORAGE', 'session') == 'sqlite':
    try:
        store = SQLiteStore()
    except Exception:
        storage_error = 'Cannot open local storage. Session records are available; check access to the data directory.'

with st.sidebar:
    st.markdown('<div class="sidebar-heading">Build your portfolio <span class="sidebar-step">STEP 01</span></div>', unsafe_allow_html=True)
    st.selectbox('Data source', ['demo','yahoo'], format_func=lambda x: {'demo':'Demo · synthetic prices','yahoo':'Yahoo · historical prices'}[x], key='source')
    st.text_input('Stock symbols · up to 20', key='symbols', help='Separate unique US stock symbols with commas. Click Update list to reset an equal allocation across the validated stocks.')
    st.button('Update list', on_click=update_symbols, width='stretch')
    if st.session_state.symbol_error:
        st.error(st.session_state.symbol_error)
    allocation = st.session_state.allocation_draft
    st.radio('Enter allocation by', ['weight','amount'], key='allocation_mode', horizontal=True,
             format_func=lambda mode: {'weight':'Weight (%)','amount':'Amount (USD)'}[mode],
             on_change=allocation_mode_changed)
    mode = allocation['mode']
    amount_mode = mode == 'amount'
    if st.session_state.allocation_switch_error:
        st.warning(st.session_state.allocation_switch_error)
    st.caption('Enter amounts. Weights and starting capital update automatically.' if amount_mode
               else 'Enter weights and starting capital. Amounts update automatically.')
    allocation_error = None
    capital = amount_total(allocation['amounts']) if amount_mode else allocation['capital']
    try:
        capital, weights = resolve_allocation(mode, allocation[mode + 's'], capital)
        amounts = tuple(allocation['amounts']) if amount_mode else amounts_from_weights(capital, weights)
    except ValidationError as exc:
        allocation_error = str(exc)
        weights, amounts = (None,) * len(st.session_state.configured_symbols), (None,) * len(st.session_state.configured_symbols)
    st.markdown('<div class="holding-header"><span>Stock</span><span>Weight %</span><span>Amount $</span></div>', unsafe_allow_html=True)
    with st.container(key='holdings_rows'):
        for index, symbol in enumerate(st.session_state.configured_symbols):
            c1,c2,c3 = st.columns([.8,1,1.4], gap='small')
            c1.markdown(f'<div class="holding-label">{escape(symbol)}</div>', unsafe_allow_html=True)
            if amount_mode:
                weight_text = '—' if weights[index] is None else f'{weights[index]:.2f}'
                c2.markdown(f'<div class="holding-amount">{weight_text}</div>', unsafe_allow_html=True)
                st.session_state['amount_' + symbol] = allocation['amounts'][index]
                c3.number_input(f'{symbol} amount (USD)', min_value=0., max_value=MAX_CAPITAL, value=None, step=100., format='%.2f',
                                key='amount_'+symbol, label_visibility='collapsed', on_change=allocation_edited, args=('amount',index))
            else:
                st.session_state['weight_' + symbol] = allocation['weights'][index]
                c2.number_input(f'{symbol} weight (%)', min_value=0., max_value=100., value=None, step=1., format='%.2f',
                                key='weight_'+symbol, label_visibility='collapsed', on_change=allocation_edited, args=('weight',index))
                amount_text = '—' if amounts[index] is None else f'{amounts[index]:,.2f}'
                c3.markdown(f'<div class="holding-amount">{amount_text}</div>', unsafe_allow_html=True)
    c1,c2=st.columns([1,1])
    if amount_mode:
        c1.caption(f'Total ${capital:,.2f}' + (' · 100%' if not allocation_error else ' · Incomplete'))
    else:
        c1.caption(f'Total {sum(w for w in allocation["weights"] if w is not None):.2f}%')
    c2.button('Equal amounts' if amount_mode else 'Equal weight', on_click=equal_allocation, width='stretch')
    if amount_mode:
        st.markdown('<div class="capital-label">Starting capital · USD <span>Calculated</span></div>', unsafe_allow_html=True)
    st.session_state.capital = capital
    st.number_input('Starting capital · USD', min_value=0., max_value=None if amount_mode else MAX_CAPITAL, value=None, step=1000., format='%.2f', key='capital',
                    disabled=amount_mode, label_visibility='collapsed' if amount_mode else 'visible',
                    on_change=allocation_edited, args=('capital',))
    st.caption('Sum of allocation amounts. Amounts use cents; derived weights retain full precision.' if amount_mode
               else 'Budget to allocate across the selected stocks. Amounts are rounded to cents.')
    st.date_input('Start date', min_value=date(1990,1,1), max_value=date(2100,1,1), key='start')
    st.date_input('End date', min_value=date(1990,1,1), max_value=date(2100,1,1), key='end')
    with st.expander('Strategy settings & fees'):
        st.number_input('Short MA (trading days)',2,499,key='short')
        st.number_input('Long MA (trading days)',3,500,key='long')
        st.number_input('Take profit (%)',.1,1000.,step=1.,key='take_profit')
        st.number_input('Stop loss (%)',.1,99.9,step=1.,key='stop_loss')
        st.number_input('Max holding (calendar days)',1,1095,key='hold_days')
        st.number_input('One-way fee (%)',0.,5.,step=.05,format='%.2f',key='fee')

    draft, draft_error = None, None
    try:
        if allocation_error:
            raise ValidationError(allocation_error)
        entered=tuple(s.strip().upper() for s in st.session_state.symbols.replace('，',',').split(','))
        if entered != st.session_state.configured_symbols:
            raise ValidationError('Stock list changed. Click Update list to validate stocks and reset an equal allocation.')
        draft=parse_inputs(','.join(st.session_state.configured_symbols),
            ','.join(str(w) for w in weights),
            capital=capital,start=st.session_state.start.isoformat(),end=st.session_state.end.isoformat(),
            source=st.session_state.source,short_window=st.session_state.short,long_window=st.session_state.long,
            take_profit=st.session_state.take_profit/100,stop_loss=st.session_state.stop_loss/100,
            max_hold_days=st.session_state.hold_days,fee=st.session_state.fee/100)
    except ValidationError as exc:
        draft_error=str(exc)
    signature=json.dumps({'symbols':st.session_state.symbols,'configured':st.session_state.configured_symbols,
        'weights':weights, 'allocation_values':allocation[mode + 's'] if allocation_error else None,
        **{k:str(st.session_state[k]) for k in ('capital','start','end','source','short','long','take_profit','stop_loss','hold_days','fee')}},sort_keys=True)
    changed=st.session_state.last_draft_signature is not None and signature != st.session_state.last_draft_signature
    st.session_state.last_draft_signature=signature
    if changed:
        st.session_state.completed=set()
    dirty=draft_error is not None or draft.to_dict()!=st.session_state.active['config'].to_dict()
    if draft_error:
        st.error(draft_error)
    analyze_clicked=st.button('Apply & reanalyze →' if dirty else 'Analyze portfolio →', type='primary',
                              disabled=draft_error is not None, width='stretch', key='analyze')
    if analyze_clicked:
        try:
            with st.spinner('Aligning prices and calculating portfolio accounts…'):
                st.session_state.active=compute(draft)
            st.session_state.update(analysis_error=None,completed={'Overview'})
            dirty=False
        except ValidationError as exc:
            st.session_state.analysis_error=str(exc)
        except Exception:
            st.session_state.analysis_error='Analysis could not complete. Check your inputs and network, then retry. Offline Demo remains available.'
    st.caption('US stocks · USD · Daily view\n\nLong only · No leverage or live trading.')
    if st.session_state.source=='demo':
        st.caption(f'Synthetic coverage {DEMO_START}–{DEMO_END}; allow history for MA warm-up.')
    else:
        st.caption('Adjusted daily close · fetches only when you analyze · excludes current New York date.')

active=st.session_state.active
config,prices,results=active['config'],active['prices'],active['results']
visible=prices.loc[config.start:config.end]
st.session_state.completed=update_progress(st.session_state.completed,st.session_state.page,dirty)

left,middle,right=st.columns([4,2,1.7],vertical_alignment='center')
with left:
    st.markdown('<div class="brand"><div class="brand-mark"><svg width="21" height="25" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><path d="M9 3h6M10 3v6L5 19a1.5 1.5 0 0 0 1.4 2h11.2A1.5 1.5 0 0 0 19 19L14 9V3M8 15h8"/></svg></div><div><div class="brand-name">Portfolio Lab</div><div class="brand-sub">Stock portfolio strategy lab</div></div></div>',unsafe_allow_html=True)
with middle:
    badge='Synthetic data · Demo' if config.source=='demo' else 'Yahoo · Historical data'
    st.markdown(f'<span class="source-badge">{badge}</span>',unsafe_allow_html=True)
with right:
    st.button('Save experiment',key='header_save',disabled=dirty or st.session_state.analysis_error is not None,
              on_click=lambda:st.session_state.update(page='Saved experiments'),width='stretch')
st.divider()
st.markdown(progress_html(st.session_state.page,st.session_state.completed,dirty),unsafe_allow_html=True)
st.title(active['name'] or 'My first portfolio')
st.markdown(f'<div class="context-line"><strong>{" · ".join(escape(s) for s in config.symbols)}</strong><span>Starting capital ${config.capital:,.2f}</span><span>{len(config.symbols)} stocks</span></div>',unsafe_allow_html=True)
source_note='Synthetic prices · Illustrative results' if config.source=='demo' else 'Adjusted daily closes · Historical simulation'
st.markdown(f'<div class="context-meta">{visible.index[0]:%Y-%m-%d} → {visible.index[-1]:%Y-%m-%d} &nbsp; · &nbsp; {source_note} &nbsp; · &nbsp; {len(visible)} common trading dates</div>',unsafe_allow_html=True)
if dirty:
    st.warning('Unapplied changes. Charts still show the last applied configuration. Apply & reanalyze before saving.')
if st.session_state.analysis_error:
    st.error(st.session_state.analysis_error)
    st.warning('This analysis failed. The last successful results are shown below.')
if storage_error:
    st.warning(storage_error)

with st.container(key='workspace_navigation'):
    st.radio('Workspace page',PAGES,horizontal=True,key='page',label_visibility='collapsed')
page=st.session_state.page
if page in ('Overview','Risk analysis'):
    c1,c2=st.columns([2.5,1.4])
    with c2:
        st.session_state.view_choice=st.session_state.viewed_strategy
        st.selectbox('Viewing strategy',list(STRATEGIES),format_func=STRATEGIES.get,key='view_choice',
            on_change=lambda:st.session_state.update(viewed_strategy=st.session_state.view_choice))
    if page=='Overview':overview(config,prices,results,st.session_state.viewed_strategy)
    else:risk_page(config,prices,results,st.session_state.viewed_strategy)
elif page=='Strategy comparison':
    strategy_page(config,prices,results)
else:
    experiment_page(active,store,dirty or st.session_state.analysis_error is not None)

with st.expander('Methodology & data details'):
    method_page()
    for note in active['notes']:st.write(note)
    calculated=datetime.fromisoformat(active['calculated_at']).astimezone(ZoneInfo('Asia/Hong_Kong'))
    st.caption(f'Calculated {calculated:%Y-%m-%d %H:%M:%S} HKT. Requested dates {config.start} to {config.end}. Warm-up begins {prices.index[0]:%Y-%m-%d}; warm-up is excluded from performance.')
st.markdown('<div class="footer">Portfolio Lab · Education and historical simulation only. Past performance does not predict future returns. No investment advice or live trading.</div>',unsafe_allow_html=True)
