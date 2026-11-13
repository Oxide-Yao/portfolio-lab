# Website integration — 2026-11-13

This release connects the independently verified core to the existing English Portfolio Lab app. It retains the blue visual style, original three strategies, draft/applied state, fees, execution records and legacy archives.

## Available in the website

- Overview: same-source SPY/QQQ comparison, CSV download and links to Stock insights and DCA Planner.
- Risk analysis: historical beta from the selected strategy and optional CAPM assumptions, alongside existing drawdown and correlations.
- Stock insights: price and moving averages, RSI, MACD, dated crossings and plain-language explanations. Display ranges do not rerun analysis.
- Edit portfolio: one shared place for benchmark, indicator and optional MACD parameters. Compare up to six explicitly chosen MACD candidates on the same data and execution assumptions. Record the selection reason; no automatic best-parameter recommendation.
- Saved experiments: full research snapshots include settings, prices, benchmark, indicator parameters, results and executions. Imports replay calculations and reject tampering. Old snapshots remain supported.
- DCA Planner: fixed-budget or ongoing DCA/VA plans, manual or Yahoo reference prices, editable purchase records, separate actual/simulation balances, skips, corrections, future settings, CSV and validated JSON backups.

Public hosting uses isolated session storage. Refresh, disconnect or restart can lose records. Download JSON to keep them. The planner does not send brokerage orders. Manual/reference prices show their date and source; Yahoo failure never substitutes synthetic prices.

## Validation

- Existing/core suite: 183 tests passed.
- New integration checks: 4 tests passed, including MACD archive replay, benchmark failure, feature draft reversal, page navigation, save/reopen, DCA record/replay and visitor isolation.
- The standalone verifier supplies 18 hand-calculated checks and runs without Streamlit, Plotly or yfinance imports.
- Desktop and 390px browser smoke checks cover the new navigation and pages; these are not exhaustive device or live-market validation.

## Remaining scope

Fundamental statements/history, OHLC/candlesticks, DMI/ADX, RSI trading strategies, automatic VA target estimates, XIRR, selling, A-shares and split processing are not implemented. No accounts or permanent cloud database were added. Planner valuations are based on supplied snapshots, not an invented daily price history. Yahoo availability is external and may vary.

Normalized market-comparison returns start at the first observed close and exclude the entry fee already embedded in that first point. Headline portfolio returns include all incurred fees. The website explains this distinction.
