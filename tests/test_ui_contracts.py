"""Semantic chart/ledger and archive checks independent of browser styling."""
from copy import deepcopy
from dataclasses import replace
from io import StringIO

import numpy as np
import pandas as pd
import pytest

from charts import drawdown_chart, equity_chart, price_chart
from conftest import sample
from experiments import import_batch
from models import ValidationError
from storage import SQLiteStore, export_records, make_record
from trading_strategy import analyze
from ui import trade_table


def test_chart_selection_and_drawdown_match_verified_metrics():
    prices,config=sample();results=analyze(prices,config)
    for key,result in results.items():
        fig=equity_chart(results,config.capital,selected=key)
        assert list(fig.data[0].y)==result.equity.tolist()
        draw=drawdown_chart(results,config.capital,selected=key)
        assert min(draw.data[0].y)==pytest.approx(result.metrics['max_drawdown'])
    fig=equity_chart(results,config.capital,compare=True)
    assert len(fig.data)==3
    assert len({trace.line.dash for trace in fig.data})==3


def test_execution_markers_table_and_export_use_same_ledger():
    prices,config=sample();results=analyze(prices,config)
    for key,result in results.items():
        fig=price_chart(prices,config,'AAA',result)
        if not result.trades.empty:
            for side,label in [('buy','Buy execution'),('sell','Sell execution')]:
                trace=next(t for t in fig.data if t.name==label)
                rows=result.trades[result.trades.side==side]
                assert list(trace.x)==rows.date.tolist()
                assert list(trace.y)==rows.price.tolist()
                assert list(trace.customdata[:,0])==rows.signal_date.tolist()
        table=trade_table(result.trades)
        exported=pd.read_csv(StringIO(table.to_csv(index=False)))
        # CSV has one empty representation for both None and NaN. Normalize
        # that representation before comparing every exported column.
        normalized=table.copy()
        for column in normalized:
            if normalized[column].isna().all():
                normalized[column]=np.nan
        pd.testing.assert_frame_equal(exported,normalized,check_dtype=False,check_exact=False)


def test_import_is_atomic_replayed_and_deduplicated_in_session_and_sqlite(tmp_path):
    prices,config=sample();results=analyze(prices,config)
    first=make_record('First',config,prices,results,[], '2026-11-13T00:00:00+00:00')
    config2=replace(config,fee=.005)
    second=make_record('Different fee',config2,prices,analyze(prices,config2),[], '2026-11-13T00:00:00+00:00')
    raw=export_records([first,second])
    session={};assert import_batch(raw,None,session)==2
    import_batch(raw,None,session);assert len(session)==2
    store=SQLiteStore(tmp_path/'records.sqlite3')
    import_batch(raw,store,{});import_batch(raw,store,{})
    assert len(SQLiteStore(store.path).list_records())==2
    forged=deepcopy(second);forged['results']['hold']['metrics']['final_value']+=1
    for db,dest in [(None,{}),(SQLiteStore(tmp_path/'empty.sqlite3'),{})]:
        with pytest.raises(ValidationError,match='replay'):
            import_batch(export_records([first,forged]),db,dest)
        assert not dest
        if db:assert not db.list_records()
    store.delete(first['id'])
    assert len(store.list_records())==1
    assert store.get(second['id'])['name']=='Different fee'
    store.delete("' OR 1=1 --")
    assert len(store.list_records())==1
