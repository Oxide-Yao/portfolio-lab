"""Read the supplied historical CSV as an explicit offline price snapshot.

No network calls, cache, application state or UI code. This adapter is for the
core verification CLI; it is not yet a data-source option in the web interface.
"""
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd

from models import ValidationError


def read_course_prices(path, symbols: tuple[str, ...]):
    """Use Adj Close, preserve the exchange-local calendar date and align stocks.

    Reject invalid selected records; never fill missing prices or silently drop
    a requested symbol. Return a normalized frame plus explicit provenance.
    """
    if not symbols or len(set(symbols)) != len(symbols):
        raise ValidationError('Select unique stock symbols for the CSV snapshot.')
    try:
        raw = Path(path).read_bytes()
        data = pd.read_csv(BytesIO(raw), dtype={'Date': str, 'Symbol': str})
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        raise ValidationError('Cannot read the supplied historical CSV.') from exc
    if not {'Date','Symbol','Adj Close'}.issubset(data.columns):
        raise ValidationError('CSV requires Date, Symbol and Adj Close columns.')
    missing = sorted(set(symbols) - set(data['Symbol'].dropna()))
    if missing:
        raise ValidationError('Requested stocks are absent from the CSV: ' + ', '.join(missing))
    selected = data[data['Symbol'].isin(symbols)].copy()
    try:
        stamps = [pd.Timestamp(value) for value in selected['Date']]
        if any(pd.isna(t) or (t.hour,t.minute,t.second,t.microsecond,t.nanosecond) != (0,0,0,0,0) for t in stamps):
            raise ValueError('Not daily data')
        # Strip the timezone without conversion: the supplied -04/-05 offsets
        # represent local trading dates, not UTC dates to be shifted.
        selected['TradingDate'] = pd.DatetimeIndex([pd.Timestamp(t.date()) for t in stamps])
        selected['Price'] = pd.to_numeric(selected['Adj Close'], errors='raise')
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValidationError('CSV contains invalid daily dates or adjusted prices.') from exc
    values = selected['Price'].to_numpy(dtype=float)
    if not np.isfinite(values).all() or (values <= 0).any():
        raise ValidationError('CSV adjusted prices must be finite and positive.')
    if selected.duplicated(['TradingDate','Symbol']).any():
        raise ValidationError('CSV contains duplicate stock and date records.')
    wide = selected.pivot(index='TradingDate', columns='Symbol', values='Price').reindex(columns=list(symbols)).sort_index()
    aligned = wide.dropna(how='any').astype(float)
    if aligned.empty:
        raise ValidationError('CSV has no common trading dates for the selected stocks.')
    metadata = {
        'source_kind': 'supplied_historical_csv', 'filename': Path(path).name,
        'sha256': sha256(raw).hexdigest(), 'rows_in_file': len(data),
        'available_symbols': sorted(data['Symbol'].dropna().unique().tolist()),
        'selected_symbols': list(symbols), 'selected_rows': len(selected),
        'price_column': 'Adj Close', 'common_dates': len(aligned),
        'removed_incomplete_dates': len(wide) - len(aligned),
        'first_date': aligned.index[0].date().isoformat(),
        'last_date': aligned.index[-1].date().isoformat(),
        'normalization': 'Exchange-local date retained; sorted; common dates only; no price fill.',
        'provenance_limit': 'Supplied file contents audited; vendor history and corporate-action adjustments not independently certified.',
    }
    return aligned, metadata
