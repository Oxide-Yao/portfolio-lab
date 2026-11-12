# Portfolio Lab

An English-language stock portfolio strategy workbench built with Python, Streamlit, pandas, NumPy, Plotly, yfinance and SQLite. US equities, USD, daily adjusted closing prices, 1–20 stocks, fractional shares, no leverage or live trading.

## Start locally

Python 3.12 is recommended. Run from this project directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python run.py
```

Open `http://127.0.0.1:8501`. Stop with Ctrl+C. `run.py` binds to localhost and enables persistent **single-user SQLite** storage in `data/experiments.sqlite3`. Restarting reads saved records. Do not use this mode for public multi-user hosting.

For isolated, temporary session records instead:

```bash
PORTFOLIO_STORAGE=session python run.py
```

The default analysis uses reproducible synthetic prices and works offline. No API keys are required. The original environment-check page has been preserved as `app_original.py`; it contained no course trading implementation. The base golden-cross strategy implements the supplied rules and **must still be checked against the original course code**. It is not presented as the teacher's source code.

## What you can do

- **Overview:** weighted buy-and-hold cash accounting, final value, return, drawdown, annual volatility, value curve, allocation and daily-return correlations.
- **Strategy lab:** compare buy-and-hold, golden cross, and golden cross with a configurable stop. Inspect moving averages and actual executions, and download all strategy trades as CSV.
- **Experiments:** save settings, warm-up price snapshots, equity curves, metrics and trades; open saved results; compare two records and their assumptions; export and import validated JSON.
- **Methodology:** plain-English explanations of signal timing, cash accounting, fees, risk metrics, data and storage limits.

Changing the sidebar does not replace displayed results until **Run analysis** is clicked. The header describes the results currently displayed. Failed calculations preserve and clearly label the previous successful results. Switching pages retains settings and results.

## Data and execution conventions

- Demo coverage: **2018-01-01 to 2026-10-30**, with fixed symbol-specific seeds. The analysis start requires sufficient prior warm-up. Demo dates approximate weekdays, not the US holiday calendar. Synthetic returns are not real investment results.
- Yahoo is requested only after **Run analysis**, cached for one hour, with `auto_adjust=True`. No failed stock is omitted and no failed request is silently replaced with demo data. End dates are inclusive; the current New York calendar date is conservatively excluded even after market close. Only complete common trading dates are retained; no future-price fill is used. Late listings and insufficient shared warm-up generate an error.
- Maximum analysis length: 10 years; at most 4,500 daily rows per snapshot. Warm-up includes at least the long-window number of dates before the first displayed date, making the previous long average available for a genuine crossing. Warm-up dates are not counted as performance.
- A golden cross is `short[t] > long[t]` and `short[t-1] <= long[t-1]`. Signal strategies start in cash; earlier signals or positions do not carry into the period. Signals formed at close execute at the **next common trading close**. Final-day orders are not filled. Buy-and-hold enters at the first displayed close.
- Each stock has its own initial cash sleeve. Weights are non-negative and must total 100% within 0.001 percentage points; that tiny tolerance is normalized before allocation. No money is reused between sleeves, no automatic rebalancing, maximum one position per stock.
- Shares bought = cash / `[fill × (1 + fee)]`. Sale proceeds = shares × fill × `(1 − fee)`. Both executed sides pay fees. Cash awaits a new crossing after an exit. Closed-trade profit includes both sides' fees; open positions pay no fictional final exit fee.
- Take profit and stop loss use the price change from the actual entry price. Holding limits use calendar days since entry. Exit priority is stop loss, take profit, holding limit. The threshold is observed at a close, then executed at the following trading close. A stop can fill at a loss greater than its threshold.
- Ending equity includes cash and open positions marked at the last close. Open positions are separate from completed round trips. No forced liquidation, taxes, additional slippage or cash interest. Adjusted-price effects are included; no separate dividend cash credit.
- Drawdown uses a running maximum **including initial capital**. Volatility is the sample standard deviation (`ddof=1`) of daily portfolio returns × √252; day one compares equity to initial capital. Correlations use displayed-period stock returns only and are undefined for constant-price series.

## Persistence and import safety

`app.py` defaults to isolated **session storage**, suitable for public hosting. The local launcher explicitly opts into SQLite. Public hosting does not provide permanent storage, authentication or a hosted database. Session records can be lost on refresh, disconnect or restart; use JSON exports to keep them. Yahoo/demo market data caches contain no user experiment records.

JSON is versioned and limited to 8 MB and 20 records per file. The importer rejects unknown/missing fields, wrong types, duplicate keys/IDs, invalid dates, unsupported versions, NaN/Infinity and invalid prices. It replays every snapshot and checks **all** stored metrics, trades and curves before accepting it. No imported code is executed. SQLite uses parameterized SQL and atomic import batches; repeated IDs are skipped. Local databases, virtual environments, personal records and exports are ignored by Git.

## Tests

```bash
source .venv/bin/activate
python -m pytest -q
python -m pip check
```

The suite covers hand-calculated two-stock weights and cash, initial-capital drawdown, both-side fees, next-close fills, take-profit/stop/holding exits, gaps, no signals, final-day orders, open valuation, future-price independence, warm-up, deterministic demo data, mocked Yahoo alignment/failure/end-date behavior, JSON validation/replay, SQLite restart/deduplication/atomicity, page navigation, invalid weights, saving/comparing/reopening, and visitor isolation.

`pytest.ini` disables pytest output capture because the Python 3.12 Anaconda installation on this machine segfaults when pytest imports its native `readline` module. This changes output handling only. Tests also run with `python -m pytest -p no:capture -q`.

Local verification on 2026-11-12: **78 tests passed**, including a rerun with `-W error::DeprecationWarning -W error::FutureWarning`; `pip check` reported no broken requirements. A real Yahoo smoke test downloaded 63 adjusted AAPL daily rows (2023-10-31 through 2024-01-31, including warm-up), without deprecation warnings. Desktop Chrome screenshots of the English overview, strategy and experiment pages were inspected; this exposed and led to fixes for metric-card overflow and table formatting. Saving, comparing and reopening records were verified by Streamlit AppTest, including SQLite persistence and separate-session isolation. A physical mobile browser was not tested; use the narrow-width checklist below.

Browser checks to repeat after UI changes:

1. Open the default overview; confirm data source, effective dates, USD amounts and readable metrics.
2. In Strategy lab, check three distinct curves, the legend, currency axes, trade markers, table formats and CSV download.
3. Enter weights `10, 10, 10`; confirm the changed-settings notice, then the validation error after Run analysis. Restore `40, 35, 25` and run again.
4. Save two named experiments, compare them, open one, export JSON and import it; confirm its exact snapshot and settings are restored. Try malformed JSON and an oversized file.
5. At a narrow browser width, confirm cards stack, the sidebar can be reopened and all buttons remain reachable.

## GitHub and Streamlit Community Cloud

Uploading this repository to GitHub stores the source code; it does not start a hosted Streamlit application. Follow the steps below to deploy a running website when needed.

1. Review `.gitignore`. Do not upload `.venv`, `data/`, databases, exports, `.env`, logs or `.streamlit/secrets.toml`.
2. Create your own GitHub repository. Commit this project's source files, tests, `.streamlit/config.toml`, `requirements.txt`, `pytest.ini` and README, then push to your repository. Use explicit file selection or inspect `git status` before committing.
3. In Streamlit Community Cloud, create an app from that repository, select the branch and **`app.py`** as the entrypoint. Choose Python 3.12 in the deployment settings. Keep `PORTFOLIO_STORAGE` unset (or set it to `session`). **Do not deploy `run.py` or set SQLite mode for a public app.**
4. Install dependencies from `requirements.txt`; check build/runtime logs and smoke-test the offline demo, archive import/export and Yahoo failure states.
5. Verify two separate browser sessions cannot see one another's saved experiments. Persistent multi-user records require a separately designed authenticated hosted database; this version does not claim that capability.

Deployment reference: Streamlit's official documentation, “Prep and deploy your app on Community Cloud” and “Managing dependencies when deploying your app”. Data reference: yfinance's official `download` API (inclusive start, exclusive end, adjusted prices).

## File map

```text
app.py                 App state, sidebar, navigation and archive workflows
ui.py / charts.py      English presentation and Plotly charts
models.py              Input parsing and strict configuration validation
market_data.py         Demo prices and cached Yahoo acquisition
trading_strategy.py    Cash accounting, fills, trade ledger and risk metrics
storage.py             Snapshot format, replay validation and SQLite
run.py                 Local-only persistent single-user launcher
app_original.py        Preserved original environment check
tests/                 Domain, storage, market-data and Streamlit flow tests
.streamlit/config.toml Light theme and bounded uploads
```

For education and historical simulation. Past performance does not predict future returns.
