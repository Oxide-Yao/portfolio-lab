from pathlib import Path
from datetime import date

import pytest
from streamlit.testing.v1 import AppTest


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("PORTFOLIO_STORAGE", "session")
    return AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30).run()


def click(app, label):
    next(b for b in app.button if b.label == label).click().run()
    assert not app.exception, [e.message for e in app.exception]


def test_default_page_and_all_navigation(app):
    assert not app.exception
    initial = app.session_state.active
    assert initial["config"].symbols == ("AAPL", "MSFT", "GOOGL")
    for page in ("Strategy lab", "Experiments", "Methodology", "Overview"):
        app.radio(key="page").set_value(page).run()
        assert not app.exception
        assert app.session_state.active["calculated_at"] == initial["calculated_at"]
    click(app, "Explore strategies →")
    assert app.session_state.page == "Strategy lab"


def test_invalid_weights_preserve_old_result_and_dirty_warning(app):
    before = app.session_state.active["calculated_at"]
    app.text_input(key="weights").set_value("10, 10, 10").run()
    assert any("Settings changed" in x.value for x in app.warning)
    click(app, "Run analysis")
    assert any("total 100%" in x.value for x in app.error)
    assert any("last successful" in x.value for x in app.warning)
    assert app.session_state.active["calculated_at"] == before
    app.text_input(key="weights").set_value("40, 35, 25").run()
    click(app, "Run analysis")
    assert not app.error


def test_save_compare_and_restore_exact_snapshot(app):
    app.radio(key="page").set_value("Experiments").run()
    click(app, "Save experiment")
    assert any("Experiment name" in x.value for x in app.error)
    app.text_input(key="experiment_name").set_value("默认实验").run()
    click(app, "Save experiment")
    assert app.success
    first = next(iter(app.session_state.session_records.values()))
    app.number_input(key="capital").set_value(200000.0).run()
    click(app, "Run analysis")
    app.text_input(key="experiment_name").set_value("双倍资金").run()
    click(app, "Save experiment")
    ids = list(app.session_state.session_records)
    app.multiselect(key="compare_records").set_value(ids).run()
    assert not app.exception
    assert any("Initial capital" in x.value for x in app.warning)
    app.selectbox(key="open_record").set_value(first["id"]).run()
    click(app, "Open full results")
    assert app.session_state.page == "Overview"
    assert app.session_state.active["config"].capital == 100000
    assert app.session_state.active["calculated_at"] == first["calculated_at"]
    assert app.number_input(key="capital").value == 100000
    assert not any("Settings changed" in x.value for x in app.warning)


def test_session_records_isolated_between_visitors(app):
    app.radio(key="page").set_value("Experiments").run()
    app.text_input(key="experiment_name").set_value("仅我的实验").run()
    click(app, "Save experiment")
    other = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30).run()
    assert len(app.session_state.session_records) == 1
    assert other.session_state.session_records == {}


def test_source_switch_does_not_request_yahoo(app, monkeypatch):
    import market_data
    def fail(*a, **k):
        pytest.fail("切换来源不应立即请求 Yahoo")
    monkeypatch.setattr(market_data, "yahoo_prices", fail)
    app.selectbox(key="source").set_value("yahoo").run()
    assert not app.exception
    assert app.session_state.active["config"].source == "demo"
    assert any("Settings changed" in x.value for x in app.warning)


def test_empty_trade_page_and_import_disabled(app):
    app.date_input(key="start").set_value(date(2023, 1, 2)).run()
    app.date_input(key="end").set_value(date(2023, 1, 4)).run()
    click(app, "Run analysis")
    app.radio(key="page").set_value("Strategy lab").run()
    assert not app.exception
    assert any("No executions" in x.value for x in app.info)
    app.radio(key="page").set_value("Experiments").run()
    assert next(b for b in app.button if b.label == "Validate & import").disabled


def test_user_facing_content_is_english(app):
    import re
    for page in ("Overview", "Strategy lab", "Experiments", "Methodology"):
        app.radio(key="page").set_value(page).run()
        assert not app.exception
        for kind in ("title", "header", "subheader", "caption", "markdown", "info", "warning", "error"):
            for element in getattr(app, kind):
                assert not re.search(r"[\u4e00-\u9fff]", element.value), element.value


def test_local_launcher_storage_saves_and_reopens(app, monkeypatch, tmp_path):
    import storage
    path = tmp_path / "app-test.sqlite3"
    original = storage.SQLiteStore
    monkeypatch.setattr(storage, "SQLiteStore", lambda: original(path))
    monkeypatch.setenv("PORTFOLIO_STORAGE", "sqlite")
    app.radio(key="page").set_value("Experiments").run()
    app.text_input(key="experiment_name").set_value("Persistent UI test").run()
    click(app, "Save experiment")
    assert app.success
    restarted = AppTest.from_file(Path(__file__).resolve().parents[1] / "app.py", default_timeout=30).run()
    restarted.radio(key="page").set_value("Experiments").run()
    assert not restarted.exception
    assert original(path).list_records()[0]["name"] == "Persistent UI test"
    click(restarted, "Open full results")
    assert restarted.session_state.active["name"] == "Persistent UI test"
