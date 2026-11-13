"""Presentational helpers; user text is rendered by native components."""
import pandas as pd
import streamlit as st

from charts import allocation_chart, correlation_chart, drawdown_chart, equity_chart, price_chart
from trading_strategy import STRATEGIES
from strategy_labels import strategy_name

CSS = """
<style>
:root { --ink:#283140; --muted:#526174; --line:#e2e7ee; --blue:#456ca3; --paper:#fbfcfd; }
.stApp, [data-testid="stHeader"] { background:var(--paper); color:var(--ink); }
.stMain .block-container { max-width:1600px; padding:3.4rem 2.4rem 2rem; }
[data-testid="stSidebar"] { background:#f1f4f9; border-right:1px solid var(--line); min-width:300px; max-width:340px; }
[data-testid="stSidebar"] > div:first-child { padding-top:.6rem; }
[data-testid="stSidebar"] [data-testid="stVerticalBlock"] { gap:.65rem; }
[data-testid="stSidebar"] h3 { font-family:inherit; font-size:17px; font-weight:550; }
[data-testid="stSidebar"] [data-testid="stNumberInputStepDown"],
[data-testid="stSidebar"] [data-testid="stNumberInputStepUp"] { display:none; }
.stMain [data-testid="stVerticalBlock"] { gap:1rem; }
h1,h2,h3 { color:var(--ink); }
h1 { font-family:Georgia,"Times New Roman",serif !important; font-size:2rem !important; font-weight:400 !important; letter-spacing:-.7px; padding-top:.2rem !important; }
h2,h3 { font-family:Georgia,"Times New Roman",serif !important; font-weight:400 !important; }
h2 { font-size:1.5rem !important; } h3 { font-size:1.22rem !important; }
p,li { font-size:14px; } [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { font-size:12px !important; color:var(--muted) !important; opacity:1 !important; }
hr { margin:.5rem 0 1rem; border-color:var(--line); }
input, [data-baseweb="select"] > div { background:white !important; border-radius:5px !important; }
input:disabled { background:#e9edf4 !important; -webkit-text-fill-color:var(--ink) !important; }
button { border-radius:6px !important; min-height:40px; }
button[kind="primary"] { background:var(--blue); border-color:var(--blue); color:white; }
button:focus-visible,input:focus-visible { outline:2px solid var(--blue) !important; outline-offset:2px; }
[class*="st-key-card_"] { border-color:var(--line) !important; border-radius:7px !important; background:transparent; box-shadow:none; }
.brand { display:flex; align-items:center; gap:12px; }
.brand-mark { display:grid; place-items:center; width:39px; height:43px; border:1px solid var(--line); border-radius:8px; color:var(--blue); }
.brand-name { font-family:Georgia,"Times New Roman",serif; font-size:27px; line-height:1.2; color:var(--ink); }
.brand-sub { color:var(--muted); font-size:13px; margin-top:5px; }
.source-badge { display:inline-block; background:#eaf0f8; color:var(--blue); padding:5px 9px; border-radius:4px; font-size:12px; margin-top:9px; }
.workflow { display:flex; align-items:center; gap:11px; flex-wrap:wrap; color:var(--muted); font-size:12px; margin:10px 0 1px; }
.workflow-item { display:inline-flex; align-items:center; gap:9px; white-space:nowrap; }
.workflow-step.current { color:#315b95; font-weight:750; } .workflow-arrow { color:var(--muted); }
.context-line { display:flex; gap:10px 24px; flex-wrap:wrap; font-size:14px; margin:2px 0 8px; }
.context-meta { color:var(--muted); font-size:13px; margin-bottom:14px; }
.st-key-strategy_picker { width:min(340px,100%); margin-left:auto; }
.st-key-workspace_navigation { border-bottom:1px solid var(--line); margin-bottom:10px; }
.st-key-workspace_navigation [role="radiogroup"] { gap:8px 18px; flex-wrap:wrap; }
.st-key-workspace_navigation label { padding:10px 4px; border-bottom:2px solid transparent; margin:0 !important; }
.st-key-workspace_navigation label > div > div:first-child { display:none; }
.st-key-workspace_navigation label:has(input:checked) { border-color:var(--blue); }
.st-key-workspace_navigation label:has(input:checked) p { color:#315b95; font-weight:700; }
.st-key-workspace_navigation label p { color:var(--muted); font-size:14px; }
.st-key-workspace_navigation label:focus-within { outline:2px solid var(--blue); outline-offset:3px; }
.metric-label { color:var(--muted); font-size:12px; margin-bottom:7px; }
.metric-value { color:var(--ink); font-size:clamp(21px,2.2vw,31px); line-height:1.25; font-weight:500; letter-spacing:-.6px; overflow-wrap:anywhere; font-variant-numeric:tabular-nums; }
.metric-help { color:var(--muted); font-size:12px; line-height:1.5; margin-top:8px; }
.st-key-metric_grid [data-testid="stColumn"] { border-right:1px solid var(--line); padding-right:12px; }
.st-key-metric_grid [data-testid="stColumn"]:last-child { border:0; }
.metric-positive { color:var(--ink); } .metric-negative { color:var(--ink); }
.sidebar-heading { display:flex; justify-content:space-between; align-items:center; font-size:16px; margin:8px 0 10px; }
.sidebar-step { font-family:Georgia,serif; color:var(--muted); font-size:12px; letter-spacing:1px; }
.holding-label { font-size:13px; padding-top:10px; overflow-wrap:anywhere; }
.holding-amount { text-align:right; color:var(--muted); font-size:12px; padding-top:10px; font-variant-numeric:tabular-nums; }
.holding-header { display:grid; grid-template-columns:.8fr 1fr 1.4fr; gap:8px; color:var(--muted); font-size:12px; }
.holding-header span:not(:first-child) { text-align:right; }
.capital-label { display:flex; align-items:center; justify-content:space-between; gap:8px; font-size:14px; }
.capital-label span { background:#e2e9f4; color:var(--blue); font-size:12px; padding:2px 5px; border-radius:4px; }
.st-key-holdings_rows input { padding-left:6px; padding-right:6px; text-align:right; font-variant-numeric:tabular-nums; font-size:13px; }
.st-key-holdings_rows [data-testid="stHorizontalBlock"] { flex-wrap:nowrap !important; gap:8px; }
.st-key-holdings_rows [data-testid="stColumn"] { min-width:0 !important; flex:.8 1 0 !important; }
.st-key-holdings_rows [data-testid="stColumn"]:nth-child(2) { flex:1 1 0 !important; }
.st-key-holdings_rows [data-testid="stColumn"]:nth-child(3) { flex:1.4 1 0 !important; }
.footer { font-size:12px; color:var(--muted); border-top:1px solid var(--line); margin-top:22px; padding-top:16px; }
[data-testid="stAlert"] { border-radius:5px; }
.stApp { overflow-wrap:break-word; }
.stMain .block-container, [data-testid="stColumn"] { min-width:0; }
[data-testid="stPlotlyChart"], [data-testid="stDataFrame"] { max-width:100%; }
[data-testid="stPopoverBody"] { width:min(440px,calc(100vw - 24px)); max-height:82dvh; overflow:auto; padding:16px; }
[data-testid="stPopoverBody"] [data-testid="stVerticalBlock"] { gap:.7rem; }
[data-testid="stPopoverBody"] [data-testid="stNumberInputStepDown"],
[data-testid="stPopoverBody"] [data-testid="stNumberInputStepUp"] { display:none; }
/* Streamlit wraps containers: stick the wrapper so the action stays visible
   throughout the editor, including expanded strategy settings. */
div:has(> .st-key-editor_apply_top) { position:sticky; top:-16px; z-index:5; background:#fbfcfd; }
.st-key-editor_apply_top { background:#fbfcfd; padding:8px 0 12px; border-bottom:1px solid var(--line); }
.comparison-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:12px; }
.strategy-summary { padding:16px; border:1px solid var(--line); border-radius:7px; background:#fff; }
.strategy-summary h3 { margin:0 0 12px; font-family:inherit !important; font-size:16px !important; font-weight:600 !important; }
.summary-values { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
.summary-values span { display:block; color:var(--muted); font-size:12px; }
.summary-values strong { display:block; font-size:24px; font-weight:550; color:var(--ink); font-variant-numeric:tabular-nums; }
.summary-fees { margin-top:12px; color:var(--muted); font-size:13px; }
@media(max-width:760px) {
 .comparison-grid { grid-template-columns:1fr; gap:9px; }
 .strategy-summary { padding:12px; }
 .summary-fees { display:none; }
 .brand-mark { width:32px; height:35px; }
 .brand-name { font-size:24px; }
 .brand-sub { margin-top:2px; }
 .stMain [data-testid="stVerticalBlock"] { gap:.7rem; }
 .st-key-workspace_navigation [role="radiogroup"] { display:grid; grid-template-columns:1fr 1fr; gap:2px 8px; }
 .st-key-workspace_navigation label { min-height:44px; padding:8px 2px; }
 .st-key-holdings_rows [data-testid="stColumn"] { min-width:0 !important; }
}
@media (max-width:1200px) and (min-width:761px) {
 .stMain .block-container { padding-left:1.5rem; padding-right:1.5rem; }
 .st-key-metric_grid [data-testid="stHorizontalBlock"] { flex-wrap:wrap; }
 .st-key-metric_grid [data-testid="stColumn"] { flex:1 1 calc(50% - 1rem) !important; min-width:calc(50% - 1rem); margin-bottom:12px; }
 .st-key-metric_grid [data-testid="stColumn"]:nth-child(2) { border:0; }
}
@media (max-width:760px) {
 .stMain .block-container { padding:3rem .8rem 1.2rem; }
 h1 { font-size:1.75rem !important; }
 .stMain [data-testid="stHorizontalBlock"] { flex-wrap:wrap; }
 .stMain [data-testid="stColumn"] { min-width:100% !important; flex:1 1 100% !important; }
 .st-key-app_header [data-testid="stHorizontalBlock"] { gap:8px; }
 .st-key-app_header [data-testid="stColumn"]:not(:first-child) { min-width:0 !important; flex:1 1 calc(50% - 8px) !important; }
 .st-key-app_header [data-testid="stColumn"]:first-child { padding-bottom:12px; }
 .st-key-app_header button { padding-left:8px; padding-right:8px; }
 .st-key-strategy_picker { width:100%; }
 .stMain .st-key-holdings_rows [data-testid="stColumn"] { min-width:0 !important; flex:.8 1 0 !important; }
 .stMain .st-key-holdings_rows [data-testid="stColumn"]:nth-child(2) { flex:1 1 0 !important; }
 .stMain .st-key-holdings_rows [data-testid="stColumn"]:nth-child(3) { flex:1.4 1 0 !important; }
 .st-key-metric_grid [data-testid="stColumn"] { border:0; border-bottom:1px solid var(--line); padding-bottom:12px; }
 .workflow { gap:8px 14px; font-size:12px; margin:3px 0; }
 .st-key-workspace_navigation [role="radiogroup"] { gap:12px; }
 [data-testid="stSidebar"] { min-width:280px; max-width:320px; }
}
</style>
"""
PLOT_CONFIG = {"displaylogo": False, "responsive": True, "modeBarButtonsToRemove": ["lasso2d", "select2d"]}


def plot(fig, key=None):
    st.plotly_chart(fig, width="stretch", config=PLOT_CONFIG, key=key)


def metric_cards(metrics):
    items = [
        ("Ending value", f"${metrics['final_value']:,.2f}", "Cash + marked-to-market positions", ""),
        ("Total return", f"{metrics['total_return']:+.2%}", "Since inception · incurred fees included", "metric-positive" if metrics["total_return"] >= 0 else "metric-negative"),
        ("Maximum drawdown", f"{metrics['max_drawdown']:.2%}", "Largest decline from a prior peak", "metric-negative" if metrics["max_drawdown"] < 0 else ""),
        ("Annualized volatility", f"{metrics['volatility']:.2%}", "Daily return sample deviation × √252", ""),
    ]
    with st.container(key="metric_grid"):
        for i, (column, (label, value, help_text, color)) in enumerate(zip(st.columns(4, gap="small"), items)):
            with column:
                st.markdown(f'<div class="metric-label">{label}</div><div class="metric-value {color}">{value}</div><div class="metric-help">{help_text}</div>', unsafe_allow_html=True)


def comparison_table(results):
    rows = []
    for key, name in ((k,strategy_name(k)) for k in results):
        m = results[key].metrics
        rows.append({"Strategy": name, "Ending value (USD)": m["final_value"], "Total return": m["total_return"],
                     "Max drawdown": m["max_drawdown"], "Annual volatility": m["volatility"],
                     "Closed trades": m["completed_trades"], "Open positions": m["open_positions"], "Fees paid (USD)": m["fees"]})
    table = pd.DataFrame(rows).style.format({
        "Ending value (USD)": "${:,.2f}", "Fees paid (USD)": "${:,.2f}",
        "Total return": "{:+.2%}", "Max drawdown": "{:.2%}",
        "Annual volatility": "{:.2%}", "Closed trades": "{:d}", "Open positions": "{:d}",
    })
    st.caption("Swipe or scroll horizontally → for all metrics. Use the table fullscreen control to expand.")
    st.dataframe(table, hide_index=True, width="stretch")
    return pd.DataFrame(rows)


def trade_table(trades):
    return trades.rename(columns={"symbol": "Stock", "side": "Side", "signal_date": "Signal date", "date": "Execution date",
                                  "price": "Fill price (USD)", "shares": "Shares", "gross": "Trade value (USD)", "fee": "Fee (USD)",
                                  "reason": "Reason", "pnl": "Net P&L (USD)", "return": "Net return", "holding_days": "Calendar days held"}).replace({"Side": {"buy": "Buy", "sell": "Sell"}})


def overview(config, prices, results, selected="hold"):
    metric_cards(results[selected].metrics)
    st.subheader("Portfolio value")
    st.caption(f"{strategy_name(selected)} · Hover or tap to inspect · USD")
    plot(equity_chart(results, config.capital, selected=selected), "overview_equity")
    st.divider()
    left, right = st.columns([1.2, 1], gap="large")
    with left:
        st.subheader("Drawdown over time")
        st.caption("Below the previous peak · includes initial capital")
        plot(drawdown_chart(results, config.capital, selected), "overview_drawdown")
    with right:
        st.subheader("Initial allocation")
        st.caption("Applied target weights · independent cash sleeves")
        plot(allocation_chart(config), "allocation")
        weights = [w / sum(config.weights) for w in config.weights]
        allocation = pd.DataFrame({"Stock": config.symbols, "Initial weight": weights,
            "Allocation (USD)": [w * config.capital for w in weights]})
        st.dataframe(allocation.style.format({"Initial weight":"{:.2%}","Allocation (USD)":"${:,.2f}"}),
                     hide_index=True, width="stretch")
    st.button("Compare strategies →", on_click=lambda: st.session_state.update(page="Strategy comparison"), key="to_strategy")


def risk_page(config, prices, results, selected="hold"):
    metric_cards(results[selected].metrics)
    st.subheader("Where the portfolio takes risk")
    st.caption(f"{strategy_name(selected)} · full-period historical measures")
    plot(drawdown_chart(results, config.capital, selected), "risk_drawdown")
    left, right = st.columns([1.25,1], gap="large")
    with left:
        st.subheader("Return correlations")
        st.caption("Daily stock returns · analysis period only · −1 to +1")
        plot(correlation_chart(prices.loc[config.start:config.end]), "correlation")
    with right:
        st.subheader("Read the risk measures")
        st.write("**Maximum drawdown** is the deepest drop from a previous portfolio peak, including the starting capital.")
        st.write("**Annualized volatility** measures how much daily portfolio returns vary, scaled by √252. It does not predict the next year's loss.")
        st.write("**Correlation** compares stock return movements. Values near +1 mean similar movement; values near −1 mean opposite movement. Constant series are undefined and shown blank.")
        st.info("A lower historical risk measure does not guarantee safety. Signal strategies may spend long periods in cash.")
    st.caption("A stop is an exit trigger, not a guaranteed fill price. The next trading close can realize a larger loss than the configured stop.")


def strategy_page(config, prices, results):
    st.subheader("Returns, risk and cost")
    st.caption("All strategies use the same applied stocks, period and price snapshot shown above. Compare return alongside drawdown and fees; a higher ending value alone does not identify the best strategy for you.")
    cards=[]
    for key,name in ((k,strategy_name(k)) for k in results):
        m=results[key].metrics
        cards.append(f'<article class="strategy-summary"><h3>{name}</h3><div class="summary-values"><div><span>Total return</span><strong>{m["total_return"]:+.2%}</strong></div><div><span>Maximum drawdown</span><strong>{m["max_drawdown"]:.2%}</strong></div></div><div class="summary-fees">Fees paid: ${m["fees"]:,.2f}</div></article>')
    st.markdown('<div class="comparison-grid">'+''.join(cards)+'</div>',unsafe_allow_html=True)
    with st.expander("Fees, trades & complete comparison"):
        table=comparison_table(results)
        st.download_button('Download comparison · CSV',table.to_csv(index=False).encode('utf-8-sig'),file_name='portfolio-lab-comparison.csv',mime='text/csv')
        st.caption("A closed trade is a completed buy–sell round trip. Fees include executed orders; open positions are not liquidated at period end.")
    with st.container(border=True, key="card_strategy_equity"):
        st.subheader("Portfolio value by strategy")
        st.caption("USD · Solid: Buy & hold · Dashed: Golden cross · Dotted: Golden cross + stop")
        plot(equity_chart(results, config.capital, compare=True), "strategy_equity")
    with st.container(border=True, key="card_parameters"):
        st.subheader("How the strategies work")
        st.write("**Buy & hold** buys at the first trading close and keeps the stocks through the period.")
        st.write("**Golden cross** buys after the short moving average crosses above the long average. It exits at the profit target or holding limit, and waits in cash for a new crossing.")
        st.write("**Golden cross + stop** follows the same rules and also exits when the price falls to the stop threshold. Execution happens at the next close, so the loss can exceed that threshold.")
        st.caption("APPLIED PARAMETERS · Change these together in Edit portfolio, then apply.")
        st.write(f"**MA {config.short_window} / {config.long_window}** · Take profit **{config.take_profit:.1%}** · Stop loss **{config.stop_loss:.1%}** · Holding limit **{config.max_hold_days} calendar days** · One-way fee **{config.fee:.2%}**")
    if any(k.startswith('macd_') for k in results):
        st.write('**MACD** buys after an upward MACD/signal crossing and exits after a downward crossing. It uses its selected holdings only; other sleeves remain in cash. Profit targets, stop thresholds and holding limits from the Golden cross strategies do not apply.')
        st.caption('MACD parameters appear in each strategy label. Candidates are compared on the same snapshot without selecting a winner.')
    st.info("Signals form at close and execute at the next common trading close. A stop is a trigger: the realized loss can exceed its threshold. Final-day signals remain unfilled.")
    with st.expander("Inspect signals & individual execution records"):
        st.subheader("Inspect signals and executions")
        c1, c2 = st.columns(2)
        key = c1.selectbox("Strategy to inspect", list(results), format_func=strategy_name, index=2, key="detail_strategy")
        symbol = c2.selectbox("Stock to inspect", config.symbols, key="detail_symbol")
        plot(price_chart(prices, config, symbol, results[key]), "price_detail")
        trades = results[key].trades
        st.caption("The chart shows the selected stock. The table and CSV include all stocks for this strategy. Triangles mark actual executions; hover to inspect signal dates.")
        if trades.empty:
            st.info("No executions in this period. Signal strategies stay in cash until a crossing. Extend the period or adjust the moving averages and run again.")
        else:
            table = trade_table(trades)
            formats = {name: "${:,.2f}" for name in ["Fill price (USD)", "Trade value (USD)", "Fee (USD)", "Net P&L (USD)"]}
            formats.update({"Shares": "{:,.4f}", "Net return": "{:+.2%}", "Calendar days held": "{:.0f}"})
            st.caption("Swipe or scroll horizontally → to inspect every execution field, or expand the table to fullscreen.")
            st.dataframe(table.style.format(formats, na_rep="—"), hide_index=True, width="stretch")
        st.download_button("Download strategy trades · CSV", trade_table(trades).to_csv(index=False).encode("utf-8-sig"),
                           file_name=f"portfolio-lab-{key}-trades.csv", mime="text/csv")


def method_page():
    st.write("Understand the rules before interpreting results. These historical simulations are not investment recommendations.")
    left, right = st.columns(2)
    sections = [
        ("01 / Golden cross & entry", "A golden cross occurs when the short moving average crosses above the long average: short ≤ long on the previous day, short > long today. Signal strategies start in cash. Pre-period prices warm up the averages only; no earlier positions or signals carry forward."),
        ("02 / Cash accounting & fees", "Capital is split into independent stock sleeves using the initial weights. Fractional shares are allowed; no shorting, leverage or rebalancing. Shares bought = sleeve cash / [fill price × (1 + fee)]. Sale proceeds = shares × fill price × (1 − fee). No cash interest, tax or additional slippage."),
        ("03 / Maximum drawdown", "Drawdown is the decline from the portfolio's previous highest value. Maximum drawdown is its most negative observation. Initial capital is included in the running peak, so first-day fees and losses are captured."),
        ("04 / Volatility & correlation", "Annual volatility = sample standard deviation of daily portfolio returns × √252. The first return compares day-one value with initial capital. Correlations use adjusted daily stock returns within the displayed period, excluding warm-up data, on a −1 to +1 scale."),
        ("05 / Signals & execution", "Signals are evaluated at each close and execute at the next common trading close. Take-profit and stop-loss thresholds use price changes from the actual entry fill. Holding periods use calendar days since entry. A threshold observed at close executes at the next trading close."),
        ("06 / Exits & end-of-period positions", "The base strategy exits on take profit or the holding limit. The stop variant also checks stop loss (priority: stop, profit, holding limit). Proceeds stay in the same stock sleeve until a new crossing. Open positions are valued at the final close, without a fictional sale or unincurred exit fee."),
        ("07 / Data & alignment", "Yahoo uses daily adjusted closes from yfinance with auto_adjust=True. Adjustment effects are included; dividends are not credited separately. Dates missing any stock are removed. All strategies calculate and execute on shared dates. The current New York date is conservatively excluded. The requested end date is inclusive. Prices are cached for one hour; failed requests never fall back to demo data."),
        ("08 / Archives & limits", "Archives include settings, warm-up price snapshots, equity curves, metrics and trades. JSON limits: 8 MB, 20 records, 4,500 price rows per record. Imports validate schema, values and a fresh replay. Public deployment defaults to isolated session records, which can be lost on refresh, disconnect or restart. Download JSON to keep your work. A hosted database and permanent cloud storage are not configured."),
    ]
    for i, (title, text) in enumerate(sections):
        with (left if i % 2 == 0 else right), st.container(border=True, key=f"card_method{i}"):
            st.subheader(title)
            st.write(text)
    st.caption("Demo prices use fixed seeds and are not real stock history. Supplied-CSV verification is available through the separate verification command; the web selector offers Demo and Yahoo.")
