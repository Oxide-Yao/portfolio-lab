from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import pytest

from models import AnalysisConfig
from storage import make_record
from trading_strategy import analyze


def sample(values=None, **overrides):
    values = values or [10, 9, 8, 9, 11, 12, 15, 16, 16]
    frame = pd.DataFrame({"AAA": values}, index=pd.bdate_range("2024-01-01", periods=len(values)))
    config = AnalysisConfig(symbols=("AAA",), weights=(100.0,), capital=1000.0,
                            short_window=2, long_window=3, start=frame.index[3].date().isoformat(),
                            end=frame.index[-1].date().isoformat(), fee=0.01)
    return frame, replace(config, **overrides)


@pytest.fixture
def record():
    prices, config = sample()
    return make_record("测试实验", config, prices, analyze(prices, config), [], datetime.now(timezone.utc).isoformat())
