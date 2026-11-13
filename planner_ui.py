"""Session-isolated planning UI. Every balance is replayed from the pure ledger."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
from uuid import uuid4

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import dca_core as dca
from charts import style
from models import ValidationError
from ui import plot


def navigate_from_portfolio(config):
    from decimal import Decimal
    weights=[Decimal(str(round(w,6))) for w in config.weights]
    weights[-1]=Decimal(100)-sum(weights[:-1])
    st.session_state.planner_seed={'symbols':list(config.symbols),'weights':[str(w) for w in weights]}
    st.session_state.update(page='DCA Planner',planner_create=True)


def _decimal_frame(rows):
    return pd.DataFrame([{k:float(v) if hasattr(v,'quantize') else v for k,v in row.items()} for row in rows])


def _put(book, message):
    st.session_state.plans[book['plan_id']]=book
    st.session_state.planner_pending_id=book['plan_id']
    st.session_state.planner_notice=message
    st.session_state.pop('planner_suggestion',None)
    st.rerun()


def _weights(text):
    from decimal import Decimal
    try:return [str(Decimal(s.strip())) for s in text.split(',')]
    except Exception:raise ValidationError('Enter numeric weights separated by commas.') from None


def create_form():
    seed=st.session_state.get('planner_seed',{'symbols':['AAPL','MSFT','VOO'],'weights':[40,30,30]})
    st.subheader('Create a plan')
    st.caption('A separate plan copied from the portfolio when requested. Backtest settings and live balances are independent.')
    with st.form('new_plan'):
        name=st.text_input('Plan name','My monthly plan',max_chars=80)
        symbols=st.text_input('Assets · comma-separated US symbols',', '.join(seed['symbols']))
        weights=st.text_input('Target weights (%) · same order',', '.join(str(x) for x in seed['weights']))
        strategy=st.selectbox('Strategy',['DCA','VA'],format_func=lambda x:'DCA · fixed amount' if x=='DCA' else 'Value averaging · buy-only')
        funding=st.selectbox('Funding mode',['fixed','ongoing'],format_func=lambda x:'Fixed budget' if x=='fixed' else 'Ongoing contributions')
        budget=st.number_input('Total budget · fixed funding (USD)',min_value=0.,value=10000.,step=1000.,format='%.2f')
        contribution=st.number_input('Contribution per period · ongoing funding (USD)',min_value=0.,value=500.,step=100.,format='%.2f')
        periods=st.number_input('Number of periods / planning horizon',1,1200,12)
        reserve=st.number_input('Cash reserve · fixed funding (%)',0.,99.99,20.,format='%.2f')
        first=st.date_input('First contribution date',date.today())
        frequency=st.selectbox('Frequency',['monthly','biweekly'],format_func=lambda x:'Monthly' if x=='monthly' else 'Every two weeks')
        rate=st.number_input('Target annual return · VA only (%)',-99.,1000.,6.,step=1.)
        st.caption('The VA rate defines a target path; it is not a forecast. Only the fields for your selected funding mode apply. Ongoing funding uses the period count as its planning horizon.')
        if st.form_submit_button('Create plan in this session',type='primary'):
            try:
                config=dict(name=name,strategy=strategy,funding=funding,symbols=[x.strip().upper() for x in symbols.split(',')],
                            weights=_weights(weights),first_date=first.isoformat(),frequency=frequency,total_budget=f'{budget:.2f}',
                            contribution=f'{contribution:.2f}',periods=periods,reserve_fraction=str(reserve/100),annual_target=str(rate/100))
                book=dca.create_plan(config)
                st.session_state.planner_create=False
                _put(book,'Plan created in this session. Download JSON to keep a backup.')
            except (ValidationError,ValueError) as exc:st.error(str(exc))


@st.cache_data(ttl=900,show_spinner=False,max_entries=32)
def latest_quotes(symbols, as_of):
    """Unadjusted closes are reference prices for recording current purchases."""
    import yfinance as yf
    end=min(date.fromisoformat(as_of),date.today()-timedelta(days=1))
    result={}
    for symbol in symbols:
        frame=yf.download(symbol,start=(end-timedelta(days=14)).isoformat(),end=(end+timedelta(days=1)).isoformat(),
                          auto_adjust=False,progress=False,threads=False,timeout=12)
        if frame.empty or 'Close' not in frame:continue
        close=frame['Close']
        if isinstance(close,pd.DataFrame):close=close.iloc[:,0]
        close=close.dropna()
        if not close.empty:
            result[symbol]={'price':str(float(close.iloc[-1])),'date':close.index[-1].date().isoformat(),
                            'updated_at':datetime.now(timezone.utc).isoformat(),'source':'Yahoo unadjusted daily close','manual':False}
    return result


def quote_panel(book, lane):
    pid=book['plan_id']; config=dca.config_for(book,dca.replay(book,lane)['next_period'])
    key=f'{pid}_{lane}'
    as_of=st.date_input('Valuation / suggestion date',date.today(),key='quote_asof_'+key)
    stored=st.session_state.setdefault('planner_quotes',{}).setdefault(key,{})
    with st.expander('Reference prices · required for every asset',expanded=True):
        st.caption('Enter manual prices or fetch Yahoo closes. Reference prices may be delayed. Actual purchase prices remain editable before recording.')
        if st.button('Fetch Yahoo reference prices',key='fetch_'+key):
            try:
                with st.spinner('Fetching reference prices…'):
                    fetched=latest_quotes(tuple(config['symbols']),as_of.isoformat())
                missing=set(config['symbols'])-set(fetched)
                if missing:
                    st.error('No complete quote update. Enter manual prices for: '+', '.join(sorted(missing)))
                stored.update(fetched)
                for symbol,q in fetched.items():
                    st.session_state['qp_'+key+symbol]=float(q['price'])
                    st.session_state['qd_'+key+symbol]=date.fromisoformat(q['date'])
            except Exception as exc:st.error(f'Quote request failed: {exc}. Enter prices manually or retry.')
        quotes={}
        for symbol in config['symbols']:
            old=stored.get(symbol)
            cols=st.columns([1,1])
            value=cols[0].number_input(f'{symbol} reference price (USD)',min_value=0.,value=float(old['price']) if old else None,
                                      step=.01,format='%.4f',key='qp_'+key+symbol)
            quoted=cols[1].date_input(f'{symbol} price date',date.fromisoformat(old['date']) if old else as_of,key='qd_'+key+symbol)
            if value is not None and value>0:
                unchanged=old and float(old['price'])==value and old['date']==quoted.isoformat()
                quote=deepcopy(old) if unchanged else {'price':str(value),'date':quoted.isoformat(),'updated_at':datetime.now(timezone.utc).isoformat(),'source':'Manual price','manual':True}
                quotes[symbol]=quote
                st.caption(f"{symbol} · {quote['source']} · Price date {quote['date']} · Updated {quote['updated_at']}" )
        stored.clear();stored.update(quotes)
    return quotes,as_of.isoformat()


def overview(book,lane,quotes,as_of):
    state=dca.replay(book,lane);config=dca.config_for(book,state['next_period'])
    try:
        summary=dca.summarize(book,quotes,as_of=as_of,lane=lane)
        cols=st.columns(4)
        for col,label,value in zip(cols,['Total contributed','Holdings market value','Investment gain/loss','Available cash'],
                                   [summary['contributed'],summary['portfolio_value'],summary['investment_gain'],summary['available_cash']]):
            col.metric(label,f'${value:,.2f}')
        st.caption(f"As of {as_of} · Cash ${summary['cash']:,.2f} includes protected reserve ${summary['reserve']:,.2f}. Gain = holdings + cash − contributions; fees are already deducted from cash.")
        total=summary['portfolio_value']
        rows=[{'Stock':s,'Shares':float(state['holdings'][s]),'Market value (USD)':float(summary['asset_values'][s]),
               'Current weight among stocks (%)':float(summary['asset_values'][s]/total*100) if total else 0,
               'Target weight (%)':float(w)} for s,w in zip(config['symbols'],config['weights'])]
        st.dataframe(pd.DataFrame(rows),hide_index=True,width='stretch')
        fig=go.Figure()
        for col,color in [('Current weight among stocks (%)','#456ca3'),('Target weight (%)','#b2c3db')]:
            fig.add_bar(x=[r['Stock'] for r in rows],y=[r[col] for r in rows],name=col,marker_color=color)
        plot(style(fig,height=290,ytitle='Weight %'),'planner_weights')
    except ValidationError as exc:
        st.info(str(exc))
        st.metric('Available cash',f"${state['available_cash']:,.2f}")
        st.metric('Total contributed',f"${state['contributed']:,.2f}")
    if config['funding']=='fixed':
        used=state['contributed']-state['cash']
        st.progress(float(used/state['contributed']),text=f"Budget spent including fees: ${used:,.2f} / ${state['contributed']:,.2f}")
    if state['batches']:
        rows=[{'Period':b['period'],'Purchase amount (USD)':sum(float(t['shares'])*float(t['price']) for t in b['trades'])} for b in state['batches']]
        fig=go.Figure(go.Bar(x=[r['Period'] for r in rows],y=[r['Purchase amount (USD)'] for r in rows],marker_color='#456ca3'))
        plot(style(fig,height=280,ytitle='Purchase amount · USD'),'planner_purchases')
    st.caption('This release shows a point-in-time valuation and recorded purchases. It does not fabricate a daily performance curve from incomplete quotes or label simple gains as annualized returns.')


def this_period(book,lane,quotes,as_of):
    state=dca.replay(book,lane);period=state['next_period'];config=dca.config_for(book,period)
    if period>config['periods']:
        st.success('Planning horizon complete. Review History or create a new plan.');return
    scheduled=dca.schedule(config,period)
    st.subheader(f'Period {period} · scheduled {scheduled}')
    st.caption(f"Base amount ${dca.period_amount(config,period):,.2f} · Available cash ${state['available_cash']:,.2f} · Protected reserve ${state['reserve']:,.2f}")
    key=f"{book['plan_id']}_{lane}_{period}"
    deposit=st.number_input('Contribution for this period (USD)',min_value=0.,value=float(dca.period_amount(config,period)) if config['funding']=='ongoing' else 0.,
                            disabled=config['funding']=='fixed',step=100.,format='%.2f',key='deposit_'+key)
    extra=st.checkbox('Allow an additional contribution above the planned amount',key='extra_'+key,disabled=config['funding']=='fixed')
    fee=st.number_input('Estimated one-way fee (%)',0.,5.,0.,step=.05,key='planner_fee_'+key)
    signature=sha256(json.dumps([book,lane,quotes,as_of,deposit,extra,fee],sort_keys=True).encode()).hexdigest()
    missing=set(config['symbols'])-set(quotes)
    if missing:st.warning('Enter positive reference prices for: '+', '.join(sorted(missing)))
    if st.button('Calculate suggestion',type='primary',disabled=bool(missing),key='calculate_suggestion'):
        try:
            suggestion=dca.suggest(book,quotes,as_of=as_of,lane=lane,deposit=f'{deposit:.2f}',allow_extra=extra,fee_rate=str(fee/100))
            st.session_state.planner_suggestion={'signature':signature,'result':suggestion,'request_id':str(uuid4())}
        except ValidationError as exc:st.error(str(exc))
    saved=st.session_state.get('planner_suggestion')
    if saved and saved['signature']==signature:
        suggestion=saved['result']
        st.dataframe(_decimal_frame(suggestion['rows']),hide_index=True,width='stretch')
        st.caption(f"Estimated spend ${suggestion['estimated_spend']:,.2f}; remaining available cash ${suggestion['remaining_available_cash']:,.2f}. Whole-share rounding leaves cash unspent.")
        if config['strategy']=='VA':
            st.write(f"**Target holdings value:** ${suggestion['target_value']:,.2f} · **Unfilled gap:** ${suggestion['unfilled_gap']:,.2f}")
        if suggestion['scaled_for_cash']:st.warning('Positive gaps were scaled down to available funding. Protected cash is not used.')
        if not any(r['shares'] for r in suggestion['rows']):st.info('No purchase needed or the allocation is too small for a whole share. Review prices and funding; fractional actual purchases can still be recorded.')
        st.info('Record a manual purchase or a simulation below. Portfolio Lab does not send orders to a broker.')
        with st.form('record_'+saved['request_id']):
            actual=st.date_input('Actual purchase date',date.fromisoformat(as_of))
            timing=st.selectbox('Record timing',['on_schedule','early','late'],index=0 if date.fromisoformat(as_of)==scheduled else 1 if date.fromisoformat(as_of)<scheduled else 2)
            trades=[]
            for row in suggestion['rows']:
                st.write('**'+row['symbol']+'**')
                cols=st.columns(3)
                qty=cols[0].number_input('Shares · up to 2 decimals',0.,value=float(row['shares']),step=.01,key='shares_'+key+row['symbol'])
                price=cols[1].number_input('Actual fill price (USD)',0.,value=float(row['price']),step=.01,format='%.4f',key='price_'+key+row['symbol'])
                charge=cols[2].number_input('Actual fee (USD)',0.,value=float(row['estimated_fee']),step=.01,key='fee_'+key+row['symbol'])
                if qty:trades.append({'symbol':row['symbol'],'shares':f'{qty:.2f}','price':str(price),'fee':f'{charge:.2f}'})
            confirm=st.checkbox(f'I confirm this is a {lane} record, not an order.')
            if st.form_submit_button('Record purchase',type='primary'):
                if not confirm:st.error('Confirm the record type before saving.')
                else:
                    try:
                        updated=dca.record_purchase(book,request_id=saved['request_id'],period=period,actual_date=actual.isoformat(),trades=trades,
                                                    deposit=f'{deposit:.2f}',timing=timing,lane=lane,allow_extra=extra)
                        _put(updated,f'Period {period} recorded in the {lane} ledger. Holdings and cash updated. View History or download a backup.')
                    except ValidationError as exc:st.error(str(exc))
    elif saved:st.info('Inputs changed. Calculate a new suggestion before recording.')
    with st.expander('Skip this period'):
        skipped=st.date_input('Skip record date',date.today(),key='skip_date_'+key)
        confirm=st.checkbox('Skip without a purchase or contribution',key='skip_confirm_'+key)
        if st.button('Confirm skip',disabled=not confirm,key='skip_'+key):
            try:_put(dca.record_purchase(book,request_id=str(uuid4()),period=period,actual_date=skipped.isoformat(),trades=[],timing='skipped',lane=lane),'Period skipped; an audit record was saved.')
            except ValidationError as exc:st.error(str(exc))


def history(book,lane):
    state=dca.replay(book,lane)
    st.subheader('Purchase history')
    raw=dca.history_csv(book,lane)
    from io import StringIO
    st.caption('Swipe horizontally → for prices, fees and record timing. Actual and simulated ledgers remain separate.')
    st.dataframe(pd.read_csv(StringIO(raw)),hide_index=True,width='stretch')
    st.download_button('Download history · CSV',raw,file_name=f'planner-{lane}-history.csv',mime='text/csv')
    if not state['batches']:return
    with st.expander('Correct or void a recorded period'):
        batch=st.selectbox('Period to correct',state['batches'],format_func=lambda b:f"Period {b['period']} · {b['date']}")
        mode=st.radio('Correction action',['Correct purchase','Void purchase'],horizontal=True)
        with st.form('correction_'+str(batch['period'])+'_'+book['plan_id']+lane):
            actual=st.date_input('Corrected actual date',date.fromisoformat(batch['date']))
            deposit=st.number_input('Corrected contribution (USD)',0.,value=float(batch['deposit']),format='%.2f')
            timing=st.selectbox('Corrected timing',['on_schedule','early','late','skipped'],index=['on_schedule','early','late','skipped'].index(batch['timing']))
            rows=[]
            for s in dca.config_for(book,batch['period'])['symbols']:
                old=next((t for t in batch['trades'] if t['symbol']==s),{'shares':'0','price':'0','fee':'0'})
                a,b,c=st.columns(3)
                qty=a.number_input(s+' corrected shares',0.,value=float(old['shares']),step=.01)
                price=b.number_input(s+' corrected price',0.,value=float(old['price']),step=.01,format='%.4f')
                fee=c.number_input(s+' corrected fee',0.,value=float(old['fee']),step=.01)
                if qty:rows.append(dict(symbol=s,shares=f'{qty:.2f}',price=str(price),fee=f'{fee:.2f}'))
            reason=st.text_input('Reason for correction / void')
            extra=st.checkbox('Allow corrected contribution above the planned amount',value=batch['allow_extra'])
            confirm=st.checkbox('Confirm this change and replay all later balances')
            if st.form_submit_button('Save correction'):
                if not confirm:st.error('Confirm the correction first.')
                else:
                    replacement=None if mode=='Void purchase' else dict(period=batch['period'],date=actual.isoformat(),trades=rows,deposit=f'{deposit:.2f}',timing=timing,allow_extra=extra)
                    try:_put(dca.correct_batch(book,request_id=str(uuid4()),period=batch['period'],reason=reason,replacement=replacement,lane=lane),'Correction saved. All balances were replayed; the audit history is retained.')
                    except ValidationError as exc:st.error(str(exc))
    with st.expander('Audit events'):
        st.json(book['events'])


def settings(book):
    config=book['versions'][-1]['config']
    st.subheader('Applied plan settings')
    st.write(f"**{config['strategy']}** · {config['funding']} funding · {config['frequency']} · {config['periods']} periods")
    st.write(f"First period amount **${dca.period_amount(config,1):,.2f}** · Reserve **${dca.reserve(config):,.2f}**")
    st.dataframe(pd.DataFrame({'Stock':config['symbols'],'Target weight (%)':config['weights']}),hide_index=True,width='stretch')
    with st.expander('Change future parameters'):
        minimum=max(book['versions'][-1]['effective_period'],*[dca.replay(book,x)['completed_periods'] for x in ('actual','simulated')])+1
        if minimum>config['periods']:st.info('No unrecorded future periods remain. Create a new plan.');return
        with st.form('version_'+book['plan_id']):
            name=st.text_input('Updated plan name',config['name'])
            weights=st.text_input('Updated target weights (%)',', '.join(str(x) for x in config['weights']))
            strategy=st.selectbox('Future strategy',['DCA','VA'],index=['DCA','VA'].index(config['strategy']))
            target=st.number_input('Future VA annual target (%)',-99.,1000.,float(config['annual_target'])*100)
            effective=st.number_input('Effective from period',minimum,config['periods'],minimum)
            st.caption('History stays unchanged. A new funding mode, asset list or schedule requires a new plan.')
            if st.form_submit_button('Save future version'):
                try:
                    updated={**config,'name':name,'weights':_weights(weights),'strategy':strategy,'annual_target':str(target/100)}
                    _put(dca.add_version(book,updated,effective_period=effective),'Future plan version saved; historical periods are unchanged.')
                except ValidationError as exc:st.error(str(exc))


def backups(book=None):
    st.subheader('JSON backup & restore')
    if book:
        st.download_button('Download plan backup · JSON',dca.export_backup(book),file_name=f"portfolio-lab-plan-{book['plan_id'][:8]}.json",mime='application/json',type='primary')
    upload=st.file_uploader('Import a plan backup',type=['json'],key='planner_import')
    if upload:
        try:
            raw=upload.getvalue();preview=dca.import_backup(raw,mode='new')
            config=preview['versions'][-1]['config']
            st.write(f"**Preview:** {config['name']} · {', '.join(config['symbols'])} · {len(preview['events'])} audit events")
            mode=st.radio('Import action',['Create independent copy','Replace matching plan'],horizontal=True)
            confirmed=st.checkbox('I reviewed the preview and confirm the import')
            digest=sha256(raw).hexdigest();receipt=(digest,mode,book['plan_id'] if book and mode=='Replace matching plan' else None)
            already=receipt in st.session_state.setdefault('planner_imported',[])
            if already:st.info('This import was already completed in this session.')
            if st.button('Import validated plan',disabled=not confirmed or already):
                if mode=='Replace matching plan' and book is None:st.error('Select the plan to replace first.')
                else:
                    restored=dca.import_backup(raw,mode='replace' if mode=='Replace matching plan' else 'new',existing_id=book['plan_id'] if book else None)
                    st.session_state.planner_imported.append(receipt)
                    st.session_state.planner_create=False
                    _put(restored,'Plan backup restored and ledger verified.')
        except (ValidationError,ValueError) as exc:st.error(f'Import failed: {exc}')


def planner_page(active):
    st.header('DCA Planner')
    st.info('Personal session only. Plans can disappear after refresh, disconnect or restart. Download JSON regularly; no account or permanent cloud storage is provided.')
    st.caption('US stocks · USD · Buy only · Manual records and simulations · No brokerage orders')
    plans=st.session_state.setdefault('plans',{})
    if 'planner_pending_id' in st.session_state:
        st.session_state.planner_selected=st.session_state.pop('planner_pending_id')
    if st.session_state.get('planner_notice'):st.success(st.session_state.pop('planner_notice'))
    if plans:
        current=st.session_state.get('planner_selected')
        st.selectbox('Current plan',list(plans),index=list(plans).index(current) if current in plans else 0,
                     format_func=lambda k:plans[k]['versions'][-1]['config']['name']+' · '+k[:8],key='planner_selected')
        st.button('Create another plan',on_click=lambda:st.session_state.update(planner_create=True))
    if not plans or st.session_state.get('planner_create'):
        create_form();backups()
        if plans:st.button('Return to selected plan',on_click=lambda:st.session_state.update(planner_create=False))
        return
    book=plans[st.session_state.planner_selected]
    lane=st.radio('Record type',['actual','simulated'],format_func=lambda x:'Actual records' if x=='actual' else 'Simulation',horizontal=True,key='planner_lane')
    state=dca.replay(book,lane);config=dca.config_for(book,state['next_period'])
    next_date=dca.schedule(config,state['next_period']) if state['next_period']<=config['periods'] else 'Complete'
    st.write(f"**{config['name']}** · {config['strategy']} · {config['funding']} funding · USD · Next period {state['next_period']} · {next_date}")
    section=st.radio('Planner page',['Overview','This period','History','Plan settings'],horizontal=True,key='planner_page')
    if section in ('Overview','This period'):
        quotes,as_of=quote_panel(book,lane)
        if section=='Overview':overview(book,lane,quotes,as_of)
        else:this_period(book,lane,quotes,as_of)
    elif section=='History':history(book,lane)
    else:settings(book)
    with st.expander('Backup & import',expanded=section=='Plan settings'):backups(book)
    with st.expander('How this planner works'):
        st.write('DCA splits each fixed contribution by target weights. Whole-share leftovers stay in cash. VA follows a target-value path and buys positive gaps only; funding limits can scale suggestions down. It never sells excess holdings.')
        st.write('Actual and simulated records use independent balances. Recorded fees are deducted once. Skips, corrections and future configuration changes retain an audit trail.')
        st.caption('Splits and reverse splits, automatic VA return estimates, XIRR, selling and A-shares are not supported. Do not use an unadjusted ledger across a stock split without an independently corrected new plan.')
