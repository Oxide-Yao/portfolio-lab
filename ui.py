"""Presentational helpers; user text is rendered by native components."""
import pandas as pd
import streamlit as st

from charts import allocation_chart, correlation_chart, equity_chart, price_chart
from trading_strategy import STRATEGIES

CSS = """
<style>
:root { --ink:#142033; --muted:#64748B; --line:#E4EAF1; }
.stApp { background:#F4F7FB; }
.block-container { max-width:1320px; padding-top:2.1rem; padding-bottom:2rem; }
[data-testid="stSidebar"] { background:#FFFFFF; border-right:1px solid var(--line); }
[data-testid="stSidebar"] .block-container { padding-top:1.3rem; }
h1 { font-size:2.05rem !important; font-weight:720 !important; letter-spacing:-.045em; }
h2 { font-size:1.25rem !important; font-weight:650 !important; letter-spacing:-.02em; }
h3 { font-size:1.05rem !important; font-weight:650 !important; }
[class*="st-key-card_"] { border-color:var(--line) !important; border-radius:14px !important; background:#FFFFFF; box-shadow:0 2px 8px rgba(20,32,51,.025); }
[data-testid="stMetricValue"] { font-size:1.8rem; letter-spacing:-.04em; }
.brand { display:flex; align-items:center; gap:11px; margin-bottom:12px; }
.brand-mark { width:38px; height:38px; display:flex; align-items:center; justify-content:center; border-radius:11px; background:#127C68; color:white; font-weight:750; font-size:17px; }
.brand-name { font-size:20px; font-weight:750; color:var(--ink); letter-spacing:-.6px; }
.brand-sub { font-size:12px; color:var(--muted); letter-spacing:.05em; margin-top:1px; }
.eyebrow { color:#127C68; font-size:12px; font-weight:650; letter-spacing:2px; margin:12px 0 4px; }
.metric-label { color:var(--muted); font-size:14px; margin-bottom:9px; }
.metric-value { color:var(--ink); font-size:clamp(22px,2.15vw,29px); line-height:1.2; font-weight:700; letter-spacing:-.9px; overflow-wrap:anywhere; }
.metric-help { color:var(--muted); font-size:12px; line-height:1.5; margin-top:11px; }
.metric-positive { color:#16866A; } .metric-negative { color:#D65A63; }
.footer { font-size:12px; color:var(--muted); border-top:1px solid var(--line); margin-top:22px; padding-top:16px; }
button[kind="primary"] { border-radius:8px; font-weight:600; }
[data-testid="stRadio"] > div { gap:1.15rem; }
[data-testid="stAlert"] { border-radius:10px; }
@media (max-width:1250px) {
 .st-key-metric_grid [data-testid="stHorizontalBlock"] { flex-wrap:wrap; }
 .st-key-metric_grid [data-testid="stColumn"] { flex:1 1 calc(50% - 1rem) !important; min-width:calc(50% - 1rem); }
}
@media (max-width:760px) {
 .block-container { padding:1.2rem 1rem; }
 h1 { font-size:1.7rem !important; }
 [data-testid="stHorizontalBlock"] { flex-direction:column; }
 [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] { width:100% !important; flex:1 1 100% !important; }
 .metric-value { font-size:28px; }
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
        ("Max drawdown", f"{metrics['max_drawdown']:.2%}", "Largest decline from a prior peak", "metric-negative" if metrics["max_drawdown"] < 0 else ""),
        ("Annual volatility", f"{metrics['volatility']:.2%}", "Daily return sample deviation × √252", ""),
    ]
    with st.container(key="metric_grid"):
        for i, (column, (label, value, help_text, color)) in enumerate(zip(st.columns(4, gap="small"), items)):
            with column, st.container(border=True, key=f"card_metric{i}"):
                st.markdown(f'<div class="metric-label">{label}</div><div class="metric-value {color}">{value}</div><div class="metric-help">{help_text}</div>', unsafe_allow_html=True)


def comparison_table(results):
    rows = []
    for key, name in STRATEGIES.items():
        m = results[key].metrics
        rows.append({"Strategy": name, "Ending value (USD)": m["final_value"], "Total return": m["total_return"],
                     "Max drawdown": m["max_drawdown"], "Annual volatility": m["volatility"],
                     "Closed trades": m["completed_trades"], "Open positions": m["open_positions"], "Fees paid (USD)": m["fees"]})
    table = pd.DataFrame(rows).style.format({
        "Ending value (USD)": "${:,.2f}", "Fees paid (USD)": "${:,.2f}",
        "Total return": "{:+.2%}", "Max drawdown": "{:.2%}",
        "Annual volatility": "{:.2%}", "Closed trades": "{:d}", "Open positions": "{:d}",
    })
    st.dataframe(table, hide_index=True, width="stretch")
    st.caption("Scroll the table horizontally or use its fullscreen control to inspect all metrics.")


def trade_table(trades):
    return trades.rename(columns={"symbol": "Stock", "side": "Side", "signal_date": "Signal date", "date": "Execution date",
                                  "price": "Fill price (USD)", "shares": "Shares", "gross": "Trade value (USD)", "fee": "Fee (USD)",
                                  "reason": "Reason", "pnl": "Net P&L (USD)", "return": "Net return", "holding_days": "Calendar days held"}).replace({"Side": {"buy": "Buy", "sell": "Sell"}})


def overview(config, prices, results):
    metric_cards(results["hold"].metrics)
    with st.container(border=True, key="card_equity"):
        left, right = st.columns([3, 2])
        with left:
            st.subheader("Portfolio value over time")
            st.caption("Buy & hold · No rebalancing after initial allocation")
        with right:
            st.caption(f"Initial capital ${config.capital:,.2f}  ·  {len(config.symbols)} stocks")
        plot(equity_chart(results, config.capital), "overview_equity")
    left, right = st.columns(2, gap="medium")
    with left, st.container(border=True, key="card_allocation"):
        st.subheader("Initial allocation")
        st.caption("Independent cash sleeves · fractional shares")
        plot(allocation_chart(config), "allocation")
        weights = [w / sum(config.weights) for w in config.weights]
        allocation = pd.DataFrame({"Stock": config.symbols, "Initial weight": weights,
                                   "Allocation (USD)": [w * config.capital for w in weights]})
        st.dataframe(allocation.style.format({"Initial weight": "{:.2%}", "Allocation (USD)": "${:,.2f}"}),
                     hide_index=True, width="stretch")
    with right, st.container(border=True, key="card_correlation"):
        st.subheader("Return correlations")
        st.caption("Daily returns in the analysis period · scale −1 to +1")
        plot(correlation_chart(prices.loc[config.start:config.end]), "correlation")
        st.caption("+1 indicates moves in the same direction; −1 indicates opposite moves. Historical correlations do not guarantee future diversification. Constant-price series have undefined correlations, shown blank.")
    with st.container(border=True, key="card_next_step"):
        st.subheader("Explore what different rules change")
        st.write("Keep capital and weights fixed. See how entry signals and exit rules affect return and risk.")
        st.button("Explore strategies →", on_click=lambda: st.session_state.update(page="Strategy lab"), key="to_strategy")


def strategy_page(config, prices, results):
    with st.container(border=True, key="card_parameters"):
        st.caption("EXPERIMENT SETTINGS · Parameters used for the displayed results")
        st.write(f"**MA {config.short_window} / {config.long_window}** · Take profit **{config.take_profit:.1%}** · Stop loss **{config.stop_loss:.1%}** · Holding limit **{config.max_hold_days} calendar days** · One-way fee **{config.fee:.2%}**")
    with st.container(border=True, key="card_strategy_equity"):
        st.subheader("Three strategies. One starting point.")
        st.caption("Independent cash sleeves · signal strategies start in cash · open positions marked at the last close")
        plot(equity_chart(results, config.capital, compare=True), "strategy_equity")
    with st.container(border=True, key="card_strategy_metrics"):
        st.subheader("Performance comparison")
        comparison_table(results)
        st.caption("A closed trade is one completed buy–sell round trip. Fees include executed orders only; open positions are not liquidated at period end.")
    st.info("Signals form at close and execute at the next common trading close. A stop is a trigger: the realized loss can exceed its threshold. Final-day signals remain unfilled.")
    with st.container(border=True, key="card_trade_inspector"):
        st.subheader("Inspect signals and executions")
        c1, c2 = st.columns(2)
        key = c1.selectbox("Strategy to inspect", list(STRATEGIES), format_func=STRATEGIES.get, index=2, key="detail_strategy")
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
    st.warning("Demo prices are generated with fixed seeds and are not real stock history or evidence of real returns. The base strategy implements the supplied rules and still needs to be checked against the original course code.")
