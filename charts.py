"""Consistent, responsive Plotly charts without external assets."""
import numpy as np
import plotly.graph_objects as go

from trading_strategy import COLORS, STRATEGIES

FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif'


def style(fig, height=360, ytitle=None):
    fig.update_layout(template="plotly_white", height=height,
                      margin=dict(l=12, r=16, t=20, b=12),
                      paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                      font=dict(family=FONT, size=13, color="#64748B"),
                      hoverlabel=dict(bgcolor="#142033", font_color="white"),
                      legend=dict(orientation="h", y=1.12, x=0, font_size=13),
                      hovermode="x unified")
    fig.update_xaxes(showgrid=False, zeroline=False, title=None)
    fig.update_yaxes(gridcolor="#EDF1F6", zeroline=False, title=ytitle)
    return fig


def equity_chart(results, capital, compare=False):
    fig = go.Figure()
    keys = list(STRATEGIES) if compare else ["hold"]
    for key in keys:
        equity = results[key].equity
        fig.add_trace(go.Scatter(x=equity.index, y=equity, name=STRATEGIES[key], mode="lines",
                                 line=dict(color=COLORS[key] if compare else "#127C68", width=2.5),
                                 fill=None if compare else "tozeroy", fillcolor="rgba(18,124,104,0.07)",
                                 hovertemplate="%{y:$,.2f}<extra>%{fullData.name}</extra>"))
    fig.add_hline(y=capital, line_dash="dot", line_color="#A4AEBE", line_width=1,
                  annotation_text="Initial capital", annotation_position="bottom right")
    all_values = [capital] + [v for k in keys for v in results[k].equity.tolist()]
    lo, hi = min(all_values), max(all_values)
    pad = max((hi - lo) * 0.13, capital * 0.015)
    fig.update_yaxes(range=[max(0, lo - pad), hi + pad], tickprefix="$", tickformat=",.0f")
    return style(fig, height=360 if not compare else 400, ytitle="Portfolio value · USD")


def allocation_chart(config):
    fig = go.Figure(go.Pie(labels=config.symbols, values=config.weights, hole=0.76,
                           sort=False, textinfo="none", marker=dict(colors=["#127C68", "#5277C3", "#A6B8D1", "#9CCBBA", "#D8BA7D", "#9C8FC1"], line=dict(color="white", width=3)),
                           hovertemplate="%{label}<br>Initial weight %{percent}<extra></extra>"))
    fig.update_layout(showlegend=False, annotations=[dict(text=f"<b>{len(config.symbols)}</b><br>stocks", x=.5, y=.5, showarrow=False, font=dict(size=18, color="#142033"))])
    return style(fig, height=245)


def correlation_chart(prices):
    corr = prices.pct_change(fill_method=None).iloc[1:].corr()
    many = len(corr) > 8
    fig = go.Figure(go.Heatmap(z=corr.to_numpy(), x=list(corr.columns), y=list(corr.index),
                              zmin=-1, zmax=1, zmid=0,
                              colorscale=[[0, "#E9ABB1"], [.5, "#F4F7FB"], [1, "#73B6A6"]],
                              text=None if many else np.round(corr.to_numpy(), 2),
                              texttemplate=None if many else "%{text:.2f}",
                              textfont=dict(color="#142033", size=14),
                              hovertemplate="%{y} × %{x}<br>Correlation %{z:.3f}<extra></extra>",
                              colorbar=dict(title="Correlation", thickness=10, len=.85)))
    style(fig, height=max(300, len(corr) * 28))
    fig.update_layout(hovermode="closest")
    fig.update_xaxes(tickangle=-45 if many else 0, side="bottom", automargin=True)
    fig.update_yaxes(autorange="reversed", automargin=True)
    return fig


def price_chart(prices, config, symbol, result):
    full = prices[symbol]
    visible = full.loc[config.start:config.end]
    fig = go.Figure()
    for name, series, color in [
        ("Adjusted close", visible, "#52647E"),
        (f"Short MA · {config.short_window}d", full.rolling(config.short_window).mean().reindex(visible.index), "#D49E42"),
        (f"Long MA · {config.long_window}d", full.rolling(config.long_window).mean().reindex(visible.index), "#5277C3"),
    ]:
        fig.add_trace(go.Scatter(x=visible.index, y=series, name=name, mode="lines", line=dict(color=color, width=1.7), hovertemplate="%{y:$,.2f}<extra>%{fullData.name}</extra>"))
    trades = result.trades
    if not trades.empty:
        for side, name, marker, color in [("buy", "Buy execution", "triangle-up", "#16866A"), ("sell", "Sell execution", "triangle-down", "#D65A63")]:
            rows = trades[(trades["symbol"] == symbol) & (trades["side"] == side)]
            fig.add_trace(go.Scatter(x=rows["date"], y=rows["price"], mode="markers", name=name,
                                     marker=dict(symbol=marker, color=color, size=11, line=dict(color="white", width=1)),
                                     customdata=rows[["signal_date", "reason"]].to_numpy(),
                                     hovertemplate="Fill %{y:$,.2f}<br>Signal date %{customdata[0]}<br>%{customdata[1]}<extra>%{fullData.name}</extra>"))
    return style(fig, height=380, ytitle="Adjusted price · USD")
