"""Portfolio Lab — an educational portfolio research workbench."""
from datetime import date, datetime, timezone
import os
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from market_data import DEMO_END, DEMO_START, load_prices
from models import AnalysisConfig, ValidationError, parse_inputs
from storage import SQLiteStore, export_records, import_records, make_record, restore_record
from trading_strategy import analyze
from ui import CSS, comparison_table, method_page, overview, strategy_page

st.set_page_config(page_title="Portfolio Lab · Portfolio Strategy Workbench", page_icon="◫", layout="wide", initial_sidebar_state="expanded")
st.markdown(CSS, unsafe_allow_html=True)


def compute(config):
    prices, notes = load_prices(config)
    return {"config": config, "prices": prices, "results": analyze(prices, config), "notes": notes,
            "calculated_at": datetime.now(timezone.utc).isoformat(), "name": None}


def set_draft(config):
    st.session_state.update(symbols=", ".join(config.symbols), weights=", ".join(f"{w:g}" for w in config.weights),
                            capital=float(config.capital), start=date.fromisoformat(config.start), end=date.fromisoformat(config.end),
                            source=config.source, short=config.short_window, long=config.long_window,
                            take_profit=config.take_profit * 100, stop_loss=config.stop_loss * 100,
                            hold_days=config.max_hold_days, fee=config.fee * 100)


if "initialized" not in st.session_state:
    set_draft(AnalysisConfig())
    st.session_state.update(initialized=True, page="Overview", session_records={}, analysis_error=None)
    # Offline preview only. Yahoo is fetched only following a user click.
    st.session_state.active = compute(AnalysisConfig())

if "pending_record" in st.session_state:
    record = st.session_state.pop("pending_record")
    config, prices, results = restore_record(record)
    set_draft(config)
    st.session_state.active = {"config": config, "prices": prices, "results": results, "notes": record["notes"],
                               "calculated_at": record["calculated_at"], "name": record["name"]}
    st.session_state.analysis_error = None

STORAGE_MODE = os.environ.get("PORTFOLIO_STORAGE", "session")
store = None
storage_error = None
if STORAGE_MODE == "sqlite":
    try:
        store = SQLiteStore()
    except Exception:
        storage_error = "Cannot open the local database. Using session records instead; check write access to the data directory."


def all_records():
    if store:
        return [store.get(r["id"]) for r in store.list_records()]
    return sorted(st.session_state.session_records.values(), key=lambda r: r["created_at"], reverse=True)


def save_records(records):
    if store:
        store.save_many(records)
    else:
        existing = st.session_state.session_records
        for record in records:
            existing.setdefault(record["id"], record)


with st.sidebar:
    st.markdown('<div class="brand"><div class="brand-mark">PL</div><div><div class="brand-name">Portfolio Lab</div><div class="brand-sub">Portfolio Strategy Workbench</div></div></div>', unsafe_allow_html=True)
    st.divider()
    st.subheader("Build your portfolio")
    st.selectbox("Data source", ["demo", "yahoo"], format_func=lambda x: {"demo": "Demo · offline & reproducible", "yahoo": "Yahoo history · network required"}[x], key="source")
    if st.session_state.source == "demo":
        st.caption(f"Demo coverage: {DEMO_START} — {DEMO_END}. Allow history for MA warm-up.")
    else:
        st.caption("Adjusted daily close · excludes current New York date · fetched only on analysis.")
    st.text_input("Stock symbols", key="symbols", help="1–20 unique US stock symbols, e.g. AAPL, MSFT, GOOGL.")
    st.caption("Example: AAPL, MSFT, GOOGL")
    st.text_input("Initial weights (%)", key="weights", help="Non-negative, totaling 100%, in the same order as the symbols.")
    st.caption("Example: 40, 35, 25")
    st.number_input("Initial capital (USD)", min_value=1.0, max_value=1_000_000_000_000.0, step=1000.0, format="%.2f", key="capital")
    st.date_input("Start date", min_value=date(1990, 1, 1), max_value=date(2100, 1, 1), key="start")
    st.date_input("End date", min_value=date(1990, 1, 1), max_value=date(2100, 1, 1), key="end")
    with st.expander("Strategy & fees", expanded=False):
        st.number_input("Short MA (trading days)", 2, 499, key="short")
        st.number_input("Long MA (trading days)", 3, 500, key="long")
        st.number_input("Take profit (%)", 0.1, 1000.0, step=1.0, key="take_profit")
        st.number_input("Stop loss (%)", 0.1, 99.9, step=1.0, key="stop_loss")
        st.number_input("Max holding (calendar days)", 1, 1095, key="hold_days")
        st.number_input("One-way fee (%)", 0.0, 5.0, step=0.05, format="%.2f", key="fee")
    analyze_clicked = st.button("Run analysis", type="primary", width="stretch")
    st.caption("Simulation only · no brokerage connection\n\nUSD / Daily / No leverage")

draft = None
draft_error = None
try:
    draft = parse_inputs(st.session_state.symbols, st.session_state.weights,
                         capital=st.session_state.capital, start=st.session_state.start.isoformat(), end=st.session_state.end.isoformat(),
                         source=st.session_state.source, short_window=st.session_state.short, long_window=st.session_state.long,
                         take_profit=st.session_state.take_profit / 100, stop_loss=st.session_state.stop_loss / 100,
                         max_hold_days=st.session_state.hold_days, fee=st.session_state.fee / 100)
except ValidationError as exc:
    draft_error = str(exc)

if analyze_clicked:
    if draft_error:
        st.session_state.analysis_error = draft_error
    else:
        try:
            with st.spinner("Aligning prices and calculating portfolio accounts…"):
                st.session_state.active = compute(draft)
            st.session_state.analysis_error = None
        except ValidationError as exc:
            st.session_state.analysis_error = str(exc)
        except Exception:
            st.session_state.analysis_error = "Analysis could not complete. Check your inputs and network, then retry. Use offline Demo mode if Yahoo is rate limited."

active = st.session_state.active
config, prices, results = active["config"], active["prices"], active["results"]

st.markdown('<div class="eyebrow">PORTFOLIO LAB / RESEARCH WORKSPACE</div>', unsafe_allow_html=True)
st.radio("Workspace page", ["Overview", "Strategy lab", "Experiments", "Methodology"], horizontal=True, key="page", label_visibility="collapsed")
page = st.session_state.page
title, subtitle = {
    "Overview": ("Your portfolio, in perspective.", "Understand historical performance, portfolio risk and the role of diversification."),
    "Strategy lab": ("Same portfolio. Different rules.", "Compare entry and exit rules with equal capital, weights and trading costs."),
    "Experiments": ("Keep your next insight within reach.", "Save reproducible snapshots, compare settings and take your experiments with you."),
    "Methodology": ("The rules behind the numbers.", "Transparent assumptions make each result explainable and reproducible."),
}[page]
st.title(title)
st.caption(subtitle)

with st.container(border=True, key="card_context"):
    c1, c2, c3 = st.columns([1.25, 2.8, 2.4])
    with c1:
        st.badge("Demo data" if config.source == "demo" else "Yahoo historical data", color="orange" if config.source == "demo" else "green")
        st.caption("USD · Daily")
    visible = prices.loc[config.start:config.end]
    with c2:
        st.write(" / ".join(config.symbols))
        st.caption(f"Effective period {visible.index[0]:%Y-%m-%d} — {visible.index[-1]:%Y-%m-%d} · {len(visible)} common trading days")
    with c3:
        st.write(f"Initial capital ${config.capital:,.2f}")
        calculated = datetime.fromisoformat(active["calculated_at"]).astimezone(ZoneInfo("Asia/Hong_Kong"))
        st.caption(f"Calculated {calculated:%Y-%m-%d %H:%M:%S} HKT")

if config.source == "demo":
    st.info("SYNTHETIC DEMO DATA · Not real stock history. Fixed seeds; for learning about portfolios and strategies only.")
if active["name"]:
    st.caption("Viewing saved experiment: " + active["name"])
if st.session_state.analysis_error:
    st.error(st.session_state.analysis_error)
    st.warning("This analysis failed. The last successful results are shown below.")
if draft_error or draft.to_dict() != config.to_dict():
    st.warning("Settings changed. Run analysis to update the results.")
    if draft_error:
        st.caption("Input validation: " + draft_error)
if storage_error:
    st.warning(storage_error)

if page == "Overview":
    overview(config, prices, results)
elif page == "Strategy lab":
    strategy_page(config, prices, results)
elif page == "Methodology":
    method_page()
else:
    if store:
        st.caption("Storage: local single-user SQLite · persists across restarts · do not use this mode for a public multi-user deployment.")
    else:
        st.info("Storage: isolated session records. Data may be lost when the session ends or the app restarts. Download JSON for safekeeping. Permanent cloud storage is not provided.")
    with st.container(border=True, key="card_save"):
        st.subheader("Save this analysis")
        st.caption("Save the displayed results and their settings. Unapplied sidebar edits are not part of this snapshot.")
        name = st.text_input("Experiment name", placeholder="e.g. Tech portfolio · 8% stop-loss study", max_chars=80, key="experiment_name")
        if st.button("Save experiment", type="primary"):
            try:
                record = make_record(name, config, prices, results, active["notes"], active["calculated_at"])
                save_records([record])
                st.success("Experiment saved with its price snapshot, all three strategies and complete trade records.")
            except ValidationError as exc:
                st.error(str(exc))
            except Exception:
                st.error("Save failed. Check disk space and directory permissions, or export the current analysis first.")
        current_export = make_record("Current analysis", config, prices, results, active["notes"], active["calculated_at"])
        st.download_button("Export current analysis · JSON", export_records([current_export]), file_name="portfolio-lab-current.json", mime="application/json")
    try:
        records = all_records()
    except Exception:
        records = []
        st.error("Could not read experiments. Check the database and local permissions. You can still export the current analysis.")
    with st.container(border=True, key="card_archive"):
        st.subheader("Saved experiments")
        if not records:
            st.info("No saved experiments yet. Give this analysis a name and save it, or import an existing JSON file.")
        else:
            rows = [{"Experiment name": r["name"], "Saved at (HKT)": datetime.fromisoformat(r["created_at"]).astimezone(ZoneInfo("Asia/Hong_Kong")).strftime("%Y-%m-%d %H:%M"),
                     "Data source": "Demo data" if r["config"]["source"] == "demo" else "Yahoo historical data",
                     "Stocks": len(r["config"]["symbols"]), "Requested period": r["config"]["start"] + " → " + r["config"]["end"]} for r in records]
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
            by_id = {r["id"]: r for r in records}
            label = lambda rid: by_id[rid]["name"] + " · " + by_id[rid]["created_at"][:19].replace("T", " ") + " UTC · " + rid[:6]
            selected = st.selectbox("Select a saved experiment", list(by_id), format_func=label, key="open_record")
            def open_history():
                st.session_state.pending_record = by_id[selected]
                st.session_state.page = "Overview"
            st.button("Open full results", on_click=open_history)
            st.download_button("Download selected experiment · JSON", export_records([by_id[selected]]), file_name=f"portfolio-lab-{selected[:8]}.json", mime="application/json")
            st.subheader("Compare two experiments")
            compare = st.multiselect("Select two records", list(by_id), format_func=label, max_selections=2, key="compare_records")
            if len(compare) == 2:
                a, b = (by_id[i] for i in compare)
                ca, cb = a["config"], b["config"]
                different = [label for key, label in [("source", "Data source"), ("start", "Start date"), ("end", "End date"), ("symbols", "Stock universe"), ("capital", "Initial capital")] if ca[key] != cb[key]]
                if a["results"]["hold"]["dates"] != b["results"]["hold"]["dates"]:
                    different.append("Effective period")
                if a["prices"] != b["prices"]:
                    different.append("Price snapshot")
                if different:
                    st.warning("The experiments differ in: " + ", ".join(different) + ". These differences affect the results; they do not establish that one strategy is superior.")
                field_names = {"symbols": "Stock", "weights": "Weights (%)", "capital": "Initial capital (USD)", "start": "Start date", "end": "End date", "source": "Data source", "short_window": "Short MA", "long_window": "Long MA", "take_profit": "Take profit", "stop_loss": "Stop loss", "max_hold_days": "Max holding days", "fee": "One-way fee"}
                def display_value(key, value):
                    if key in ("take_profit", "stop_loss", "fee"):
                        return f"{value:.2%}"
                    if key == "source":
                        return "Demo data" if value == "demo" else "Yahoo historical data"
                    return ", ".join(map(str, value)) if isinstance(value, list) else str(value)
                params = [{"Parameter": title, "Experiment A": display_value(k, ca[k]), "Experiment B": display_value(k, cb[k]), "Status": "Same" if ca[k] == cb[k] else "Different"} for k, title in field_names.items()]
                st.dataframe(pd.DataFrame(params), hide_index=True, width="stretch")
                for column, record in zip(st.columns(2), [a, b]):
                    with column:
                        st.write(record["name"])
                        _, _, restored = restore_record(record)
                        comparison_table(restored)
            elif compare:
                st.caption("Select one more experiment to compare settings and metrics for all three strategies.")
            exports = st.multiselect("Batch export (up to 20 records)", list(by_id), format_func=label, max_selections=20)
            if exports:
                try:
                    st.download_button("Download selected archive · JSON", export_records([by_id[i] for i in exports]), file_name="portfolio-lab-archive.json", mime="application/json")
                except ValidationError as exc:
                    st.error(str(exc))
    with st.container(border=True, key="card_import"):
        st.subheader("Import experiments")
        st.caption("Up to 8 MB / 20 records. Imports are validated and replayed; existing experiment IDs are not duplicated.")
        uploaded = st.file_uploader("Choose a Portfolio Lab JSON file", type=["json"], key="import_file")
        if st.button("Validate & import", disabled=uploaded is None):
            try:
                with st.spinner("Validating snapshots and replaying results…"):
                    imported = import_records(uploaded.getvalue())
                    save_records(imported)
                st.session_state.import_notice = f"Processed {len(imported)} valid experiments. Existing IDs were skipped."
                st.rerun()
            except ValidationError as exc:
                st.error("Import failed: " + str(exc))
            except Exception:
                st.error("Import failed: invalid file structure or unavailable storage. Use a JSON file exported by Portfolio Lab.")
        if "import_notice" in st.session_state:
            st.success(st.session_state.pop("import_notice"))

if active["notes"]:
    with st.expander("Data notes & calculation details"):
        for note in active["notes"]:
            st.write(note)
        st.write(f"Requested period: {config.start} to {config.end}. Warm-up snapshot begins {prices.index[0]:%Y-%m-%d}. Warm-up data is excluded from displayed performance.")
        st.write("Volatility and drawdown include the initial-capital baseline. All strategies use the same capital, weights, prices and fees.")
st.markdown('<div class="footer">Portfolio Lab · Portfolio Strategy Workbench　 | 　For education and historical simulation. Past performance does not predict future returns.</div>', unsafe_allow_html=True)
