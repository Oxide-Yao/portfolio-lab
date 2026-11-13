# Phase 2 — independent core implementation

Status: the verified independent core is now connected to the Streamlit website. See [WEBSITE_RELEASE.md](WEBSITE_RELEASE.md) for integration scope. No accounts or persistent shared storage were added.

## Run without opening a webpage

Python 3.12 recommended. From this directory:

```bash
python -m pip install -r requirements-core.txt
python verify_features.py --output-dir ../evidence
python -m pytest -q tests/test_analytics_features.py tests/test_dca_core.py
```

The verifier deliberately blocks imports of Streamlit, Plotly and yfinance. It runs the original eight arithmetic checks plus ten new checks, and writes expected/actual JSON, sample research/planner backups and a parameter comparison CSV. `requirements.txt` is still needed for the complete existing UI regression suite (`python -m pytest -q`). Core functions never import Streamlit; Yahoo remains an optional, explicit online adapter.

## Modules and integration contracts

| Module | Pure entry points / responsibility |
| --- | --- |
| `data_core.py` | `demo_prices`, `load_prices`, optional `yahoo_prices`; deterministic demo, injectable providers, Yahoo only on request |
| `market_data.py` | Existing website cache wrapper around the extracted data functions |
| `analytics_core.py` | `clean_price_records`, `read_price_csv`, `sma`, `ema`, `rsi`, `macd`, `stock_insights`, `benchmark_comparison`, `historical_beta`, `capm_required_return`, `fundamental_value` |
| `trading_strategy.py` | Original strategies plus `run_signal_strategy`; each result now exposes daily per-stock cash and holdings for accounting checks |
| `feature_backtest.py` | `run_macd`, `compare_macd_parameters`; separate minimal MACD experiment JSON, leaving old three-strategy archives compatible |
| `research_core.py` | `analyze_experiment`, `export_research_snapshot`, `restore_research_snapshot`; recommended complete research archive including benchmark, provenance, insight parameters, prices, results and executions |
| `dca_core.py` | Plans, schedules, suggestions, purchase batches, corrections, cash/holdings replay, future versions, valuation history, CSV, validated full JSON |

The research entry point accepts supplied price snapshots and explicit `PriceBasis`; it does not fetch benchmarks or fundamentals. It returns a new result without mutating its input or any web state. Website integration should compute into a temporary result and replace the applied result only on success. A failed standalone benchmark call therefore cannot mutate the old portfolio result. The web archive importer accepts legacy records and the new research records, validating both by replay. Planner backups use their own importer.

### Data, indicators and backtests

- Long CSV schema: `Date,Symbol,Price`. Normalize symbol casing/whitespace, sort daily dates, reject duplicate normalized symbol/date pairs and invalid prices. Missing values are rejected by default; `missing="common_dates"` is an explicit opt-in and returns removed-date metadata. No interpolation, forward fill or backfill. US-symbol validation is syntactic, not an exchange-listing verification.
- Source, currency, adjustment basis and synthetic environment/version must agree for a benchmark comparison. It must cover every existing portfolio date. Extra benchmark dates are ignored; missing dates fail rather than shorten the original strategy run.
- Benchmark curves both start at 100 at their first observed close. This **excludes any initial entry fee already embedded in the first portfolio point** from the normalized interval return. The strategy's original total return remains measured from initial capital and includes that fee. Benchmark is frictionless. Yahoo uses adjusted close; no additional dividend credit. Use `price_return` for synthetic fixtures.
- SMA: full window required. EMA: mean of the first full window, then alpha `2/(n+1)`. RSI: first n price changes seed average gains/losses, then Wilder `1/n`; flat history produces50. MACD signal is a seeded EMA of MACD. Warm-up values are missing, never zero. Last-state text, crossing events and executions remain distinct.
- Original hold/golden/stop rules remain intact. MACD buys on upward and sells on downward crossing; no additional take-profit/stop rule is silently applied to MACD. Signals at close fill at the **next common trading close**. No final-day fictional fill, shorting, duplicate entry or forced final liquidation.
- Each stock retains its initial cash sleeve. For single-stock MACD scope, other sleeves remain cash; weights are not redistributed. Both executed sides pay the same configured proportional fee. Backtest quantities remain fractional.
- Inputs must contain adequate history for every candidate. MACD requires `slow + signal - 1` prior observations to confirm the previous signal-line value. The existing loader's history is based on the long SMA: callers experimenting with larger MACD windows must fetch/provide additional history. Insufficient history fails explicitly.
- Comparisons use one snapshot, dates, capital, allocations and fees. Candidates and a selection rationale are supplied **before comparison**; no automatic winner. These are exploratory in-sample comparisons, not proof of predictive performance or out-of-sample optimization.
- Historical beta is sample covariance of actual portfolio daily returns with benchmark returns divided by sample benchmark variance. At least two paired returns; zero variance gives unavailable/error. CAPM is only the formula using explicit annual decimal assumptions. Fundamentals are metadata-normalized display observations; there is no online fundamental downloader and no use of current financial data in past trades.

### Planner contracts

`create_plan(config)` takes a JSON-compatible dictionary. Example configuration and a complete ledger are in `../evidence/dca_example.json`. Decimal amounts should be passed as strings; weights are percentage numbers/strings totaling exactly100. Config fields are fixed and validated.

- `funding`: `fixed` or `ongoing`; `strategy`: `DCA` or `VA`; frequency `monthly` or `biweekly`. Periods1–1200; ongoing plans use periods as a finite planning horizon. Extend by creating a new plan in this version. Monthly dates retain the original anchor day (Jan31 → Feb29 → Mar31); biweekly is14 calendar days.
- Fixed budget is available at plan creation. Reserve is rounded to cents once and protected. Investable budget is split into cent-rounded installments with the remainder in the final installment. Ongoing deposits occur only in explicit recorded batches; a suggestion previews the planned contribution but does not add it. Amounts above the per-period contribution require `allow_extra=True`.
- DCA allocates the current installment by weight. Previous spare cash stays cash rather than automatically increasing the next DCA installment. VA target recursively compounds the previous unrounded target by actual scheduled days/365, adds that period's base amount, and rounds the displayed target to cents. Annual target is constrained to greater than−100% and at most1000% as an input bound.
- VA only buys positive per-stock gaps. Above-target assets never cause sales. Gaps are proportionally reduced to fit available cash including estimated fees. Fixed VA may use remaining investable cash beyond one installment; it can never spend the reserve. Whole-share suggestions round down; actual recorded shares support two decimal places.
- Quotes require each symbol's price, quote date, timezone-aware update timestamp, source and manual flag. Missing assets or future quote dates block a suggestion. Stale dates are retained visibly in returned metadata; no freshness guarantee or invented quote. No OHLC data is fabricated.
- Actual trades have explicit quantity, price and fee. Purchase gross rounds half-up to cents per trade. Fees are charged from cash once. `gain = market value + total cash − contributions`; reserve is part of cash, never a second contribution. There are no sales, leverage, taxes, cash interest, automatic dividend payments or broker orders.
- `actual` and `simulated` are independent ledgers, each with its own initial budget. They must not be summed into one investment performance figure.
- `record_purchase` requires period, actual date, trades, deposit, unique request ID and explicit timing (`early`, `late`, `on_schedule`, `skipped`). Periods advance only on recorded batches, including explicit skips. Repeating the same request ID and exact payload returns the same ledger; conflicting reuse fails. Suggestions never advance periods.
- Corrections/voids append events and replay the full lane. A void removes the purchase and its deposit, leaves the period explicitly skipped, and preserves its audit trail. Changes that make later cash negative are rejected. Corrections are revised-history accounting, not a historical “what was known then” report.
- Future versions support name, strategy, target weights and annual VA target. Funding/schedule/assets changes require a new plan. Existing periods keep their earlier version. Versions must be added before the affected periods are recorded.
- `valuation_history` needs explicit quote snapshots for each desired date. It replays holdings as of those dates, including current corrections. It never invents a daily series from sparse records. CSV exports effective batches; JSON retains original actions, corrections, versions and IDs.
- JSON import validates schema and replays every action. `mode="new"` clones with a new ID and origin ID; `mode="replace"` requires the matching existing ID. Functions return data, not a persistence side effect. Repeated cloning deliberately creates separate plans; the later UI must prevent unintended repeated user confirmations.

## Verified examples

| Check | Independently expected |
| --- | --- |
| 60% at+10%,40% at−5%, no fee | $1,000 → $1,040; +4% |
| Buy at12, sell at16,1% fee each side | shares `1000/(12×1.01)`; cash `shares×16×.99` |
| First-price100, then90/81/99 | maximum drawdown−19% including initial capital |
| Portfolio12%, benchmark9% | +3 percentage points |
| Portfolio returns+20%,−20%; market+10%,−10% | beta2 |
| $1,000 budget,20% reserve,2periods,60/40, prices100/30 | first suggestion2 and5shares; spend350; cash650, protected reserve200 |
| Ongoing deposit100, buy3×30, fee1, later mark40 | cash9; holdings120; gain29 |

Tests additionally cover no-lookahead prefixes, fee/holdings/cash conservation, incomplete dates, symbol mismatches, warm-up, scope, constant-market beta, snapshot tampering, reserve breaches, duplicate requests, quote failures, VA scaling/no-sales, end-of-month dates, early/late/skips, corrections with downstream overspending, independent lanes and historical valuations.

## Deliberately not implemented or verified

No account system, persistent planner database, browser storage or guarantee of live Yahoo/fundamental reliability. New pages and website integration are described in WEBSITE_RELEASE.md. The full regression suite includes existing Streamlit AppTest checks; the new standalone core verifier forbids Streamlit imports.

Deferred specification items: OHLC/candlesticks, DMI/ADX, RSI trading strategy, fundamentals fetching/history, automatic VA target estimation, XIRR, sales, A-shares, corporate-action/split processing and generalized funding/schedule migrations. Corporate actions have an explicit empty schema slot and imports reject non-empty actions, preventing a false claim that splits were applied. Split-aware raw versus adjusted valuation remains future work.
