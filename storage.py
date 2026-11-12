"""Bounded JSON snapshots and parameterized, local-only SQLite persistence."""
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3
from uuid import UUID, uuid4

import pandas as pd

from price_validation import validate_prices
from models import AnalysisConfig, ValidationError
from trading_strategy import TRADE_COLUMNS, StrategyResult, analyze

SCHEMA_VERSION = 1
MAX_BYTES = 8 * 1024 * 1024
MAX_RECORDS = 20


def encode_results(results: dict[str, StrategyResult]) -> dict:
    return {key: {
        "dates": [d.date().isoformat() for d in result.equity.index],
        "equity": result.equity.tolist(),
        "metrics": result.metrics,
        "trades": json.loads(result.trades.to_json(orient="records", double_precision=15)),
    } for key, result in results.items()}


def make_record(name: str, config: AnalysisConfig, prices: pd.DataFrame,
                results: dict[str, StrategyResult], notes: list[str], calculated_at: str) -> dict:
    name = name.strip()
    if not 1 <= len(name) <= 80:
        raise ValidationError("Experiment name must contain 1–80 characters.")
    return {
        "version": SCHEMA_VERSION,
        "id": str(uuid4()),
        "name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "calculated_at": calculated_at,
        "config": config.to_dict(),
        "notes": list(notes),
        "prices": {"dates": [d.date().isoformat() for d in prices.index],
                   "columns": list(prices.columns), "values": prices.to_numpy().tolist()},
        "results": encode_results(results),
    }


def restore_record(record: dict):
    config = AnalysisConfig.from_dict(record["config"])
    snapshot = record["prices"]
    prices = pd.DataFrame(snapshot["values"], columns=snapshot["columns"], index=pd.to_datetime(snapshot["dates"]))
    results = {}
    for key, result in record["results"].items():
        results[key] = StrategyResult(pd.Series(result["equity"], index=pd.to_datetime(result["dates"]), name=key),
                                     pd.DataFrame(result["trades"], columns=TRADE_COLUMNS), result["metrics"])
    return config, prices, results


def _same(actual, expected):
    """Validate all stored computed fields against a bounded independent replay."""
    if isinstance(expected, dict):
        return isinstance(actual, dict) and set(actual) == set(expected) and all(_same(actual[k], v) for k, v in expected.items())
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(_same(a, b) for a, b in zip(actual, expected))
    if type(expected) in (int, float):
        return type(actual) in (int, float) and math.isfinite(actual) and math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-9)
    return type(actual) is type(expected) and actual == expected


def validate_record(record: dict) -> dict:
    keys = {"version", "id", "name", "created_at", "calculated_at", "config", "notes", "prices", "results"}
    if not isinstance(record, dict) or set(record) != keys:
        raise ValidationError("Experiment fields are incomplete or contain unknown entries.")
    if type(record["version"]) is not int or record["version"] != SCHEMA_VERSION:
        raise ValidationError("Unsupported experiment version. Only version 1 is supported.")
    if not isinstance(record["name"], str) or not 1 <= len(record["name"].strip()) <= 80:
        raise ValidationError("Experiment name must contain 1–80 characters.")
    try:
        if not isinstance(record["id"], str) or str(UUID(record["id"])) != record["id"]:
            raise ValueError
        for key in ("created_at", "calculated_at"):
            stamp = record[key]
            if not isinstance(stamp, str) or len(stamp) > 50 or datetime.fromisoformat(stamp).tzinfo is None:
                raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise ValidationError("Invalid experiment ID or timestamp format.") from None
    notes = record["notes"]
    if not isinstance(notes, list) or len(notes) > 20 or any(not isinstance(n, str) or len(n) > 1000 for n in notes):
        raise ValidationError("Invalid data notes.")
    config = AnalysisConfig.from_dict(record["config"])
    snap = record["prices"]
    if not isinstance(snap, dict) or set(snap) != {"dates", "columns", "values"}:
        raise ValidationError("Invalid price snapshot structure.")
    dates, columns, values = snap["dates"], snap["columns"], snap["values"]
    if not isinstance(dates, list) or not 2 <= len(dates) <= 4500 or columns != list(config.symbols):
        raise ValidationError("Invalid snapshot symbols or row count (maximum: 4,500 rows, 20 stocks).")
    if not isinstance(values, list) or len(values) != len(dates):
        raise ValidationError("Snapshot dates and prices have different lengths.")
    if any(not isinstance(row, list) or len(row) != len(columns) or any(type(v) not in (int, float) or not math.isfinite(v) or v <= 0 for v in row) for row in values):
        raise ValidationError("Invalid snapshot prices. All prices must be finite positive numbers.")
    try:
        if any(not isinstance(d, str) or len(d) != 10 or pd.Timestamp(d).date().isoformat() != d for d in dates):
            raise ValueError
        prices = pd.DataFrame(values, columns=columns, index=pd.to_datetime(dates))
    except (ValueError, TypeError, OverflowError):
        raise ValidationError("Invalid snapshot date format.") from None
    prices = validate_prices(prices, config)
    # Never trust imported statistics or trades. Recompute before admitting a record.
    if not _same(record["results"], encode_results(analyze(prices, config))):
        raise ValidationError("Import rejected: metrics, equity curves or trades do not match a replay of the price snapshot.")
    return record


def export_records(records: list[dict]) -> bytes:
    if not 1 <= len(records) <= MAX_RECORDS:
        raise ValidationError("Each file must contain 1–20 experiments.")
    raw = json.dumps({"version": SCHEMA_VERSION, "records": records}, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
    if len(raw) > MAX_BYTES:
        raise ValidationError("Export exceeds 8 MB. Select fewer experiments.")
    return raw


def _unique_pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValidationError("JSON contains duplicate fields.")
        out[key] = value
    return out


def import_records(raw: bytes) -> list[dict]:
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BYTES:
        raise ValidationError("The file must be non-empty and no larger than 8 MB.")
    try:
        data = json.loads(raw.decode("utf-8-sig"), object_pairs_hook=_unique_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(ValidationError("NaN and Infinity are not allowed.")))
    except (UnicodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        if isinstance(exc, ValidationError):
            raise
        raise ValidationError("Cannot read JSON. Upload a UTF-8 file exported by Portfolio Lab.") from None
    if not isinstance(data, dict) or set(data) != {"version", "records"} or type(data["version"]) is not int or data["version"] != SCHEMA_VERSION:
        raise ValidationError("Unsupported JSON structure or version.")
    records = data["records"]
    if not isinstance(records, list) or not 1 <= len(records) <= MAX_RECORDS:
        raise ValidationError("Import 1–20 experiments at a time.")
    validated = [validate_record(record) for record in records]
    if len({r["id"] for r in validated}) != len(validated):
        raise ValidationError("Experiment IDs must be unique within a file.")
    return validated


class SQLiteStore:
    """Explicit opt-in single-user store. Not for a public multi-user service."""
    def __init__(self, path="data/experiments.sqlite3"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS experiments (id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL)")

    def connect(self):
        return sqlite3.connect(self.path, timeout=10)

    def save_many(self, records: list[dict]):
        # Atomic batch: a malformed import cannot partially update the library.
        validated = [validate_record(r) for r in records]
        rows = [(r["id"], r["name"], r["created_at"], json.dumps(r, ensure_ascii=False, allow_nan=False)) for r in validated]
        with self.connect() as conn:
            conn.executemany("INSERT OR IGNORE INTO experiments (id, name, created_at, payload) VALUES (?, ?, ?, ?)", rows)

    def list_records(self) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute("SELECT id, name, created_at FROM experiments ORDER BY created_at DESC").fetchall()
        return [{"id": row[0], "name": row[1], "created_at": row[2]} for row in rows]

    def get(self, record_id: str) -> dict:
        with self.connect() as conn:
            row = conn.execute("SELECT payload FROM experiments WHERE id = ?", (record_id,)).fetchone()
        if not row:
            raise ValidationError("Experiment not found.")
        return validate_record(json.loads(row[0]))

    def delete(self, record_id: str):
        """Remove exactly the user-selected local record; never execute input as SQL."""
        with self.connect() as conn:
            conn.execute("DELETE FROM experiments WHERE id = ?", (record_id,))
