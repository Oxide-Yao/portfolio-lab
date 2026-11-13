"""Streamlit caching facade. Pure acquisition/cleaning lives in data_core."""
import streamlit as st
import data_core
from data_core import DEMO_START, DEMO_END, last_completed_us_date
from price_validation import validate_prices

demo_prices = st.cache_data(show_spinner=False, max_entries=32)(data_core.demo_prices)
yahoo_prices = st.cache_data(ttl=3600, max_entries=24, show_spinner=False)(data_core.yahoo_prices)


def load_prices(config):
    return data_core.load_prices(config, demo_provider=demo_prices,
                                 yahoo_provider=yahoo_prices, completed_date=last_completed_us_date)
