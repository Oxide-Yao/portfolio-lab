"""Opt-in extensions; the website's original three-strategy contract is intact."""
from dataclasses import asdict
from hashlib import sha256
import json

import pandas as pd

from analytics_core import CALCULATION_VERSION, MACDParameters, macd
from models import AnalysisConfig, ValidationError
from price_validation import validate_prices
from trading_strategy import analyze, run_signal_strategy


def run_macd(prices, config, parameters=MACDParameters(), *, scope=None):
    parameters.validate(); config.validate()
    prices = validate_prices(prices, config)
    scope = tuple(config.symbols) if scope is None else tuple(scope)
    if not scope or len(scope) != len(set(scope)) or not set(scope).issubset(config.symbols):
        raise ValidationError("Choose one or more unique portfolio symbols for MACD scope.")
    visible = prices.loc[config.start:config.end]
    required = parameters.slow + parameters.signal - 1
    if (prices.index < visible.index[0]).sum() < required:
        raise ValidationError(f"Insufficient history: MACD requires {required} prior trading dates for a seeded crossover.")
    entries = pd.DataFrame(False, index=visible.index, columns=config.symbols)
    exits = entries.copy()
    for symbol in scope:
        signals = macd(prices[symbol], parameters).loc[visible.index]
        entries[symbol], exits[symbol] = signals.entry, signals.exit
    return run_signal_strategy(prices, config, entries, exits, "MACD")


def compare_macd_parameters(prices, config, candidates, *, selection_note, scope=None):
    """Predeclared candidates on the exact same snapshot, no automatic winner.

    Exploratory in-sample comparison, not an out-of-sample effectiveness claim.
    Invalid/insufficient history aborts rather than changing one candidate's dates.
    """
    if not isinstance(selection_note, str) or not selection_note.strip():
        raise ValidationError("Explain how parameter candidates were chosen before comparing them.")
    candidates = tuple(candidates)
    scope = tuple(config.symbols) if scope is None else tuple(scope)
    if any(not isinstance(p, MACDParameters) for p in candidates):
        raise ValidationError("Use MACDParameters for every candidate.")
    if not 1 <= len(candidates) <= 30 or len(set(candidates)) != len(candidates):
        raise ValidationError("Provide 1–30 distinct parameter candidates.")
    prices = validate_prices(prices, config)
    results = analyze(prices, config)
    rows = [{"strategy": key, **result.metrics} for key, result in results.items()]
    for parameters in candidates:
        key = f"macd_{parameters.fast}_{parameters.slow}_{parameters.signal}"
        result = run_macd(prices, config, parameters, scope=scope)
        results[key] = result
        rows.append({"strategy": key, **result.metrics,
                     "return_difference_vs_hold_pp": 100 * (result.metrics["total_return"] - results["hold"].metrics["total_return"])})
    snapshot = prices.to_csv(index_label="Date", float_format="%.17g")
    return {"results": results, "comparison": pd.DataFrame(rows).set_index("strategy"),
            "selection_note": selection_note.strip(), "selection_method": "Predeclared exploratory candidates; no best-parameter claim or automatic selection.",
            "config": config.to_dict(), "parameters": [asdict(x) for x in candidates],
            "scope": list(config.symbols if scope is None else scope), "price_sha256": sha256(snapshot.encode()).hexdigest(),
            "execution": "Signal at close; next common close; same sleeve allocations and fee on both executed sides. MACD exits only on downward crossover.",
            "calculation_version": CALCULATION_VERSION}


def export_feature_experiment(prices, config, candidates, *, selection_note, scope=None):
    """Separate v1 extension archive; does not break existing three-strategy JSON."""
    from storage import encode_results
    run = compare_macd_parameters(prices, config, candidates, selection_note=selection_note, scope=scope)
    payload = {key: run[key] for key in ("config", "parameters", "scope", "selection_note", "calculation_version")}
    payload.update(schema="portfolio-lab-features-1", prices={"dates": [d.date().isoformat() for d in prices.index],
                    "columns": list(prices.columns), "values": prices.to_numpy().tolist()}, results=encode_results(run["results"]))
    return json.dumps(payload, allow_nan=False, ensure_ascii=False).encode()


def restore_feature_experiment(raw):
    from storage import _same
    if not isinstance(raw, bytes) or len(raw) > 8 * 1024 * 1024:
        raise ValidationError("Feature experiment must be JSON bytes no larger than 8 MB.")
    def unique(pairs):
        data = {}
        for key, value in pairs:
            if key in data:
                raise ValidationError("Duplicate JSON key.")
            data[key] = value
        return data
    try:
        data = json.loads(raw, object_pairs_hook=unique)
        required = {"schema", "config", "parameters", "scope", "selection_note", "calculation_version", "prices", "results"}
        if not isinstance(data, dict) or set(data) != required or data["schema"] != "portfolio-lab-features-1" or data["calculation_version"] != CALCULATION_VERSION:
            raise ValidationError("Unsupported feature archive schema or calculation version.")
        config = AnalysisConfig.from_dict(data["config"])
        snapshot = data["prices"]
        if set(snapshot) != {"dates", "columns", "values"}:
            raise ValidationError("Invalid price snapshot fields.")
        prices = pd.DataFrame(snapshot["values"], columns=snapshot["columns"], index=pd.to_datetime(snapshot["dates"]))
        candidates = [MACDParameters(**x).validate() for x in data["parameters"]]
        replay = export_feature_experiment(prices, config, candidates, selection_note=data["selection_note"], scope=data["scope"])
        if not _same(data, json.loads(replay)):
            raise ValidationError("Stored feature results differ from replay.")
        return prices, config, compare_macd_parameters(prices, config, candidates, selection_note=data["selection_note"], scope=data["scope"])
    except (TypeError, KeyError, ValueError, OverflowError) as exc:
        raise ValidationError(f"Cannot restore feature experiment: {exc}") from exc
