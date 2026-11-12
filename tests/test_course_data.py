from pathlib import Path

import pandas as pd
import pytest

from course_data import read_course_prices
from models import ValidationError


def write_csv(tmp_path, text):
    path = tmp_path / 'prices.csv'
    path.write_text(text)
    return path


def test_adjusted_column_local_dates_and_common_dates(tmp_path):
    path = write_csv(tmp_path, 'Date,Symbol,Close,Adj Close\n'
        '2024-03-11 00:00:00-04:00,AAA,999,11\n'
        '2024-03-08 00:00:00-05:00,AAA,999,10\n'
        '2024-03-08 00:00:00-05:00,BBB,999,20\n')
    before = path.read_bytes()
    prices, meta = read_course_prices(path, ('AAA','BBB'))
    assert prices.index.tolist() == [pd.Timestamp('2024-03-08')]
    assert prices.iloc[0].tolist() == [10.,20.]
    assert prices.index.tz is None
    assert meta['removed_incomplete_dates'] == 1
    assert path.read_bytes() == before


@pytest.mark.parametrize('row', [
    'not-a-date,AAA,10', '2024-01-01,AAA,0', '2024-01-01,AAA,-1',
    '2024-01-01,AAA,inf', '2024-01-01,AAA,',
    '2024-01-01 12:00:00-05:00,AAA,10',
])
def test_invalid_selected_csv_records_rejected(tmp_path,row):
    path = write_csv(tmp_path,'Date,Symbol,Adj Close\n'+row+'\n')
    with pytest.raises(ValidationError): read_course_prices(path,('AAA',))


def test_duplicates_and_missing_symbols_are_not_silently_dropped(tmp_path):
    path=write_csv(tmp_path,'Date,Symbol,Adj Close\n2024-01-01,AAA,10\n2024-01-01,AAA,11\n')
    with pytest.raises(ValidationError,match='duplicate'): read_course_prices(path,('AAA',))
    with pytest.raises(ValidationError,match='absent'): read_course_prices(path,('AAA','BBB'))


def test_missing_columns_and_empty_intersection(tmp_path):
    path=write_csv(tmp_path,'Date,Symbol,Close\n2024-01-01,AAA,10\n')
    with pytest.raises(ValidationError,match='requires'):read_course_prices(path,('AAA',))
    path=write_csv(tmp_path,'Date,Symbol,Adj Close\n2024-01-01,AAA,10\n2024-01-02,BBB,20\n')
    with pytest.raises(ValidationError,match='no common'):read_course_prices(path,('AAA','BBB'))
