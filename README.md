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

The default analysis uses reproducible synthetic prices and works offline. No API keys are required. The original environment-check page has been preserved as `app_original.py`; it contained no course trading implementation. The golden-cross strategy extends the course example with explicit changes to execution timing and cash accounting. The Phase 2 comparison below records these differences; this is not an exact reproduction of the teacher's source code.

## What you can do

- **Overview:** choose a verified strategy to view ending value, return, drawdown, annual volatility, value curve and initial allocation.
- **Risk analysis:** inspect the selected strategy's drawdown and displayed-period daily stock-return correlations, with explanations of each measure.
- **Strategy comparison:** compare buy-and-hold, golden cross, and golden cross with a configurable stop. Inspect moving averages and actual executions, and download all strategy trades as CSV.
- **Saved experiments:** save settings, warm-up price snapshots, all three strategies' curves, metrics and trades; open complete results; compare two records and their assumptions; export and import validated JSON; remove a selected record after confirmation.
- **Methodology & data details:** an expander on every page explains signal timing, cash accounting, fees, risk metrics, data and storage limits.

The blue-and-white layout adapts the supplied Portfolio Lab HTML template to native Streamlit controls and Plotly charts. Template-only monthly rebalancing and benchmark mock values are replaced by the Phase 2 verified strategies. The app uses a light theme, serif headings and distinct solid/dashed/dotted strategy curves.

Edit stock symbols, then click **Update list** to validate them and reset equal weights. Each stock has a weight field and allocation amount; **Equal weight** is available at any time. Invalid drafts disable analysis. Changing the sidebar keeps the last applied results visible until **Apply & reanalyze** succeeds. The header always describes displayed results. Saving is disabled while edits are unapplied or the latest analysis has failed. The header **Save experiment** opens the archive page; provide a name and click **Save snapshot** there.

Workflow highlights track the current page independently of completion checkmarks. Visiting Risk analysis and Strategy comparison marks those steps as viewed; successfully saving checks the last step. Returning to Overview preserves checks and highlights Configure portfolio. These checks describe app navigation, not scientific acceptance or human approval. Any configuration edit invalidates progress. Switching pages or viewing strategies retains settings and results; opening a saved record restores its exact snapshot without downloading data.

## Data and execution conventions

- Demo coverage: **2018-01-01 to 2026-10-30**, with fixed symbol-specific seeds. The analysis start requires sufficient prior warm-up. Demo dates approximate weekdays, not the US holiday calendar. Synthetic returns are not real investment results.
- Yahoo is requested only after an analysis button is clicked, cached for one hour, with `auto_adjust=True`. No failed stock is omitted and no failed request is silently replaced with demo data. End dates are inclusive; the current New York calendar date is conservatively excluded even after market close. Only complete common trading dates are retained; no future-price fill is used. Late listings and insufficient shared warm-up generate an error.
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

Phase 3 verification on 2026-11-13: **124 tests passed, 0 failures/errors/skips**, with deprecation and future warnings treated as errors. This preserves all 106 Phase 2 non-UI cases, updates and extends the original 8 UI cases to 15, and adds 3 chart/export/import contract cases. Core calculations, price validation and data acquisition semantics are unchanged from Phase 2. Test outputs, browser screenshots, download verification and review status are in the separate `pd2_phase3` evidence pack.

Phase 2 verification on 2026-11-13 passed 114 tests and `pip check`. Its 27 core-boundary and 9 CSV-adapter cases remain in this run. The core calculates successfully in a fresh process where importing Streamlit, yfinance and Plotly is blocked. Price validation rejects boolean/complex values, the standalone strategy entry point validates its inputs, and risk calculations reject invalid capital or equity.

Reproduce the separate expected/actual arithmetic checks without a browser:

```bash
python verify_core.py --output-dir artifacts/core-check
```

To include the supplied historical file and the reviewed teacher notebook, use their actual local paths:

```bash
python verify_core.py --output-dir artifacts/core-check \
  --course-csv "/path/to/stock_data.csv" \
  --teacher-notebook "/path/to/course_reference.ipynb"
```

Only use `--teacher-notebook` with the reviewed course reference: it compiles three selected function definitions from the notebook, while excluding top-level notebook commands. The historical file and notebook are external course materials, not bundled with this source archive. Without these optional inputs, the command still runs all eight hand-calculated checks.

The CSV adapter uses `Adj Close`, retains the exchange-local daily date across daylight-saving offsets, rejects invalid or duplicate selected records, and aligns common dates without filling. It is a core verification tool; **CSV is not yet selectable in the Streamlit interface**. The default web demo remains synthetic.

The teacher's example buys at the crossing-day close and sells at the first target close within 60 calendar days, or at the last available close within that interval, including a truncated end-of-data interval. Each crossing produces an independent trade record. This project instead uses next-common-trading-close fills, finite cash sleeves, one position per stock, configurable fees, and marked open positions at the end. On the same supplied adjusted MSFT prices (2021-05-11–2025-07-22, MA50/200, zero fee), the teacher replay records three closed trades; this engine records two closed trades and one open position. Teacher average trade return is not portfolio total return.

The Phase 2 historical portfolio check uses AAPL/MSFT/GOOGL at 40/35/25%, USD 100,000, 2023-01-03–2025-07-22, MA50/200, 15% target, 8% stop, 60 calendar days and 0.1% per executed side. Final values are USD 198,569.41 (hold), 114,110.15 (golden cross) and 114,200.58 (golden cross + stop). These fixed-window findings do not establish general strategy superiority. Detailed records, source fingerprints, ledgers and raw test outputs are in the separate `pd2_phase2` evidence pack. Phase 3 adds local chart/export inspection; independent team review and cloud acceptance remain pending.

The suite covers hand-calculated two-stock weights and cash, initial-capital drawdown, both-side fees, next-close fills, take-profit/stop/holding exits, gaps, no signals, final-day orders, open valuation, future-price independence, warm-up, deterministic demo data, mocked Yahoo alignment/failure/end-date behavior, JSON validation/replay, SQLite restart/deduplication/atomicity, page navigation, invalid weights, saving/comparing/reopening, and visitor isolation.

`pytest.ini` disables pytest output capture because the Python 3.12 Anaconda installation on this machine segfaults when pytest imports its native `readline` module. This changes output handling only. Tests also run with `python -m pytest -p no:capture -q`.

Local verification on 2026-11-12: **78 tests passed**, including a rerun with `-W error::DeprecationWarning -W error::FutureWarning`; `pip check` reported no broken requirements. A real Yahoo smoke test downloaded 63 adjusted AAPL daily rows (2023-10-31 through 2024-01-31, including warm-up), without deprecation warnings. Desktop Chrome screenshots of the English overview, strategy and experiment pages were inspected; this exposed and led to fixes for metric-card overflow and table formatting. Saving, comparing and reopening records were verified by Streamlit AppTest, including SQLite persistence and separate-session isolation. These are earlier Phase 1 checks. Phase 3 adds a 390 × 844 browser viewport check, including sidebar open/close and stacked content; a physical mobile device remains untested.

Browser checks to repeat after UI changes:

1. Open the default overview; confirm data source, effective dates, USD amounts and readable metrics.
2. In Risk analysis, check drawdown and correlations. In Strategy comparison, check three distinct curves, the legend, currency axes, trade markers, table formats and CSV download.
3. Enter weights `10, 10, 10`; confirm the unapplied-changes notice, validation error and disabled analysis/save buttons. Restore `40, 35, 25` and analyze again.
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
app.py                 App state, draft/applied settings, sidebar and navigation
workflow.py            Current step and independent completion checks
experiments.py         Save, restore, compare, import/export and removal workflows
ui.py / charts.py      English presentation and Plotly charts
models.py              Input parsing and strict configuration validation
market_data.py         Demo prices and cached Yahoo acquisition
price_validation.py    Pure price validation without UI/network dependencies
course_data.py         Explicit offline course CSV adapter for verification
trading_strategy.py    Cash accounting, fills, trade ledger and risk metrics
verify_core.py         Hand checks, historical audit and course-rule comparison
storage.py             Snapshot format, replay validation and SQLite
run.py                 Local-only persistent single-user launcher
app_original.py        Preserved original environment check
tests/                 Domain, storage, market-data and Streamlit flow tests
.streamlit/config.toml Light theme and bounded uploads
```

For education and historical simulation. Past performance does not predict future returns.
