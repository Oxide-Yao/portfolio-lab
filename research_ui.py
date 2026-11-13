"""English research views; inputs live in the shared portfolio editor."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from analytics_core import benchmark_comparison, historical_beta, capm_required_return, stock_insights
from charts import style
from models import ValidationError
from ui import plot
from website_features import basis_for, feature_options
from strategy_labels import strategy_name


def feature_editor(symbols):
    options=feature_options(st.session_state.get('feature_draft'))
    with st.expander('Market benchmark, indicators & MACD'):
        options['benchmark']=st.selectbox('Market benchmark',['SPY','QQQ'],index=['SPY','QQQ'].index(options['benchmark']),key='feature_benchmark')
        st.caption('SPY tracks the S&P 500; QQQ tracks the Nasdaq-100. Demo uses synthetic benchmark prices, not real index returns.')
        options['rsi_period']=st.number_input('RSI period',2,100,value=options['rsi_period'],key='feature_rsi')
        options['macd_enabled']=st.checkbox('Include MACD in strategy comparison',value=options['macd_enabled'],key='feature_macd_enabled')
        st.caption('MACD buys after its line crosses above its signal line and exits after a downward cross, at the next common close. Unselected holdings remain in cash.')
        # Render every setting on every rerun so drafts survive navigation and toggles.
        values=options['insight_macd']
        fast=st.number_input('MACD fast EMA',2,200,value=values['fast'],key='feature_fast')
        slow=st.number_input('MACD slow EMA',3,300,value=values['slow'],key='feature_slow')
        signal=st.number_input('MACD signal EMA',2,100,value=values['signal'],key='feature_signal')
        options['insight_macd']={'fast':fast,'slow':slow,'signal':signal}
        scope=options['scope'][0] if options['scope'] and options['scope'][0] in symbols else 'All holdings'
        scopes=['All holdings',*symbols]
        choice=st.selectbox('Apply MACD to',scopes,index=scopes.index(scope),key='feature_scope')
        options['scope']=None if choice=='All holdings' else [choice]
        extra=st.text_input('Additional MACD candidates (optional)',value=st.session_state.get('feature_extra_draft',''),
                            placeholder='8/21/5; 16/35/9',key='feature_extra')
        st.session_state.feature_extra_draft=extra
        options['selection_note']=st.text_area('Why these parameters?',value=options['selection_note'],key='feature_reason',max_chars=600)
        options['candidates']=[options['insight_macd']]
        parse_error=None
        if extra.strip():
            try:
                for candidate in extra.split(';'):
                    a,b,c=map(int,candidate.strip().split('/'))
                    options['candidates'].append({'fast':a,'slow':b,'signal':c})
            except ValueError:
                parse_error='Use fast/slow/signal separated by semicolons, for example 8/21/5; 16/35/9.'
        st.caption('All candidates share data, dates, allocations and fees. This is an exploratory in-sample comparison; no automatic best-parameter selection.')
    st.session_state.feature_draft=options
    return options, parse_error if options['macd_enabled'] else None


def set_feature_draft(options=None):
    options=feature_options(options)
    st.session_state.feature_draft=options
    st.session_state.feature_extra_draft='; '.join(f"{p['fast']}/{p['slow']}/{p['signal']}" for p in options['candidates'][1:])
    for key in list(st.session_state):
        if key.startswith('feature_') and key not in ('feature_draft','feature_extra_draft'):
            del st.session_state[key]


def market_view(active, selected, risk=False):
    st.subheader('Historical market sensitivity' if risk else 'Portfolio vs. market')
    if active.get('benchmark') is None:
        st.info(active.get('benchmark_error') or 'This older snapshot has no benchmark. Apply & reanalyze to fetch one with the same source.')
        return
    options=active['features']; equity=active['results'][selected].equity
    benchmark=active['benchmark']; basis=basis_for(active['config'])
    try:
        comparison=benchmark_comparison(equity,benchmark,portfolio_basis=basis,benchmark_basis=basis,benchmark_symbol=options['benchmark'])
        if risk:
            beta=historical_beta(equity,benchmark.loc[equity.index])
            st.metric(f"Historical beta vs. {options['benchmark']}",f"{beta['beta']:.2f}")
            st.caption(f"{strategy_name(selected)} · {beta['observations']} paired daily returns · {beta['start']} → {beta['end']}. Calculated from actual portfolio returns, including cash periods.")
            st.write('Beta describes past sensitivity to the benchmark. Around 1 means similar sensitivity; above 1 means stronger movement. It can change over time and does not measure every kind of risk.')
            with st.expander('Advanced analysis · CAPM assumptions'):
                st.caption('Illustrative annual assumptions, not live rates. Changing these does not change historical returns.')
                rf=st.number_input('Annual risk-free rate (%)',-10.,50.,4.,step=.5,key='capm_rf')
                premium=st.number_input('Annual market risk premium (%)',-50.,100.,5.,step=.5,key='capm_premium')
                value=capm_required_return(beta['beta'],rf/100,premium/100)
                st.metric('CAPM required return',f"{value['required_return']:.2%}")
                st.caption(f"{rf:.2f}% + {beta['beta']:.2f} × {premium:.2f}%. A model requirement, not a return forecast or valuation verdict.")
        else:
            cols=st.columns(3)
            for col,label,value in zip(cols,['Portfolio interval return',f"{options['benchmark']} interval return",'Difference'],
                                       [f"{comparison['portfolio_return']:+.2%}",f"{comparison['benchmark_return']:+.2%}",f"{comparison['difference_percentage_points']:+.2f} pp"]):
                col.metric(label,value)
            fig=go.Figure()
            for column,label,color,dash in [('portfolio',strategy_name(selected),'#456ca3','solid'),('benchmark',options['benchmark'],'#7f93ad','dash')]:
                curve=comparison['curves'][column]
                fig.add_trace(go.Scatter(x=curve.index,y=curve,name=label,line=dict(color=color,dash=dash)))
            plot(style(fig,ytitle='First observed close = 100'),'market_comparison')
            st.caption('Same dates and source · USD · Benchmark has no trading fees. Curves start at the first observed close; interval returns exclude the entry fee already in that first portfolio point. Total return above includes that fee.')
            st.download_button('Download market comparison · CSV',comparison['csv'],file_name='market-comparison.csv',mime='text/csv')
    except ValidationError as exc:
        st.info(str(exc))


def stock_insights_page(active):
    config=active['config']
    st.subheader('Stock insights')
    st.button('← Back to overview',on_click=lambda:st.session_state.update(page='Overview'))
    symbol=st.selectbox('Holding',config.symbols,key='insight_symbol')
    options=active.get('features',feature_options())
    item=active.get('research',{}).get('insights',{}).get(symbol)
    if item is None:
        item=stock_insights(active['prices'][symbol],short=config.short_window,long=config.long_window)
    data=item['data'].loc[config.start:config.end]
    st.caption(f"{symbol} · {'Synthetic data' if config.source=='demo' else 'Yahoo adjusted close'} · As of {item['as_of']} · USD")
    st.write(f"**Trend:** {item['states']['sma']}. **Momentum:** {item['states']['macd']}.")
    period=st.radio('Chart range',['Full period','Last 3 months','Last year'],horizontal=True,key='insight_range')
    if period!='Full period':
        data=data.loc[data.index[-1]-pd.Timedelta(days=93 if period=='Last 3 months' else 365):]
    st.caption('Chart range changes only the display. Indicators use all available prior history; this does not rerun the strategy.')
    fig=go.Figure()
    for key,label,color,dash in [('close','Close','#456ca3','solid'),('short_sma',f'SMA {config.short_window}','#b18a46','dash'),('long_sma',f'SMA {config.long_window}','#7f93ad','dot')]:
        fig.add_trace(go.Scatter(x=data.index,y=data[key],name=label,line=dict(color=color,dash=dash)))
    plot(style(fig,ytitle='Price · USD'),'insight_price')
    st.subheader(f"RSI · {options['rsi_period']} trading days")
    fig=go.Figure(go.Scatter(x=data.index,y=data.rsi,name='RSI',line_color='#456ca3'))
    for value in (30,70):fig.add_hline(y=value,line_dash='dash',line_color='#7f93ad')
    fig.update_yaxes(range=[0,100]);plot(style(fig,height=260,ytitle='RSI'),'insight_rsi')
    st.write(item['states']['rsi'])
    st.subheader('MACD · trend and momentum')
    fig=go.Figure(go.Bar(x=data.index,y=data.macd_histogram,name='Histogram',marker_color='#b2c3db'))
    for key,label,dash in [('macd_macd','MACD','solid'),('macd_signal','Signal','dash')]:
        fig.add_trace(go.Scatter(x=data.index,y=data[key],name=label,line=dict(color='#456ca3' if dash=='solid' else '#7f93ad',dash=dash)))
    plot(style(fig,height=290,ytitle='MACD'),'insight_macd')
    st.caption('MACD compares fast and slow exponential averages. A crossing is an observed event, not an executed trade or a prediction. Indicator warm-up is shown as gaps.')
    events=[{'Event':k.replace('_',' ').upper(),'Most recent date':v or 'No crossing in available history'} for k,v in item['recent_events'].items()]
    with st.expander('Recent crossings & calculation details'):
        st.dataframe(pd.DataFrame(events),hide_index=True,width='stretch')
        st.write(item['parameters']);st.caption(item['convention'])
    st.info('Fundamental financial statements are not connected in this release. No synthetic P/E, revenue or valuation scores are shown.')
