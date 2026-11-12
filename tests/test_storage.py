from copy import deepcopy
import json

import pytest

from models import ValidationError
from storage import MAX_BYTES, SQLiteStore, export_records, import_records, restore_record
from trading_strategy import analyze


def raw_record(record):
    return json.dumps({"version": 1, "records": [record]}, ensure_ascii=False).encode()


def test_json_roundtrip_with_snapshot(record):
    imported = import_records(export_records([record]))
    assert imported == [record]
    config, prices, results = restore_record(imported[0])
    assert results["golden"].metrics == analyze(prices, config)["golden"].metrics


def test_sqlite_roundtrip_restart_dedup_and_parameterization(tmp_path, record):
    path = tmp_path / "experiments.sqlite3"
    record["name"] = "实验'); DROP TABLE experiments; --"
    SQLiteStore(path).save_many([record, record])
    reopened = SQLiteStore(path)
    assert len(reopened.list_records()) == 1
    assert reopened.get(record["id"]) == record
    with pytest.raises(ValidationError):
        reopened.get("' OR 1=1 --")


@pytest.mark.parametrize("mutate", [
    lambda r: r.update(version=2),
    lambda r: r.update(version=True),
    lambda r: r.update(name=123),
    lambda r: r.update(id="broken"),
    lambda r: r.update(calculated_at="yesterday"),
    lambda r: r["config"].update(capital=float("nan")),
    lambda r: r["config"].update(capital=True),
    lambda r: r["config"].update(weights=[-100]),
    lambda r: r["config"].update(short_window=2.5),
    lambda r: r["prices"]["values"][0].__setitem__(0, 0),
    lambda r: r["prices"]["values"][0].__setitem__(0, float("inf")),
    lambda r: r["prices"]["values"][0].__setitem__(0, True),
    lambda r: r["prices"]["dates"].__setitem__(0, "not a date"),
    lambda r: r["prices"]["dates"].__setitem__(1, r["prices"]["dates"][0]),
    lambda r: r["results"]["hold"]["metrics"].update(final_value=999999),
    lambda r: r["results"]["hold"]["equity"].__setitem__(0, -1),
    lambda r: r.update(notes="wrong type"),
    lambda r: r.update(extra="unsupported"),
])
def test_reject_invalid_fields_and_forged_results(record, mutate):
    mutate(record)
    with pytest.raises(ValidationError):
        import_records(raw_record(record))


@pytest.mark.parametrize("raw", [b"", b"not json", b"[]", b'{"version":1,"records":[]}',
    b'{"version":1,"version":1,"records":[]}', b'\xff', b'{"version":1,"records":[NaN]}'])
def test_invalid_json(raw):
    with pytest.raises(ValidationError):
        import_records(raw)


def test_size_record_count_and_duplicate_ids(record):
    for data in [b" " * (MAX_BYTES+1), json.dumps({"version": 1, "records": [record] * 21}).encode()]:
        with pytest.raises(ValidationError):
            import_records(data)
    with pytest.raises(ValidationError):
        import_records(export_records([record, record]))


def test_invalid_import_is_atomic(tmp_path, record):
    bad = deepcopy(record)
    bad["results"]["hold"]["metrics"]["fees"] = -1
    store = SQLiteStore(tmp_path / "test.db")
    with pytest.raises(ValidationError):
        store.save_many([record, bad])
    assert store.list_records() == []
