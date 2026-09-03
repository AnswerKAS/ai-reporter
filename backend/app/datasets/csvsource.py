"""Адаптер CSV: файл в artifacts/datasets/<slug>/data.csv."""

import csv
from pathlib import Path

from .base import DatasetAdapter, DatasetError, DatasetField


class CsvAdapter(DatasetAdapter):
    def __init__(self, file: Path) -> None:
        self._file = file

    def _open(self):
        if not self._file or not Path(self._file).exists():
            raise DatasetError('CSV-файл не загружен')
        return Path(self._file).open(encoding='utf-8-sig', newline='')

    def test_connection(self) -> None:
        with self._open():
            pass

    def fetch_schema(self) -> list[DatasetField]:
        with self._open() as f:
            reader = csv.reader(f, delimiter=_sniff_delimiter(self._file))
            try:
                header = next(reader)
            except StopIteration as exc:
                raise DatasetError('CSV-файл пуст') from exc
            sample = [row for row, _ in zip(reader, range(50))]
        types = _infer_types(header, sample)
        return [DatasetField(name=h.strip() or f'col_{i}', type=t) for i, (h, t) in enumerate(zip(header, types))]

    def sample_rows(self, limit: int = 50) -> tuple[list[str], list[list]]:
        delimiter = _sniff_delimiter(self._file)
        with self._open() as f:
            reader = csv.reader(f, delimiter=delimiter)
            try:
                header = next(reader)
            except StopIteration as exc:
                raise DatasetError('CSV-файл пуст') from exc
            rows = [[(c[:200] + '…' if len(c) > 200 else c) for c in row] for row, _ in zip(reader, range(limit))]
        return header, rows


    def run_query(self, sql: str, params: dict | None = None) -> tuple[list[str], list[list]]:
        raise DatasetError(
            'агрегация по CSV пока не поддерживается — нужен локальный движок запросов'
        )

    def quoted_table(self, table: str) -> str:
        return str(self._file)

    def close(self) -> None:
        """Файлу закрывать нечего — метод для единообразия интерфейса."""


def _sniff_delimiter(file: Path) -> str:
    try:
        with Path(file).open(encoding='utf-8-sig') as f:
            head = f.read(4096)
        dialect = csv.Sniffer().sniff(head, delimiters=',;\t')
        return dialect.delimiter
    except Exception:
        return ','


def _infer_types(header: list[str], rows: list[list[str]]) -> list[str]:
    def guess(values: list[str]) -> str:
        vals = [v.strip() for v in values if v.strip() != '']
        if not vals:
            return 'string'
        def all_of(pred) -> bool:
            return all(pred(v) for v in vals)
        if all_of(str.isdigit):
            return 'integer'
        try:
            for v in vals:
                float(v.replace(',', '.'))
            return 'float'
        except ValueError:
            pass
        from datetime import datetime
        for fmt in ('%Y-%m-%d', '%d.%m.%Y', '%Y-%m-%d %H:%M:%S'):
            try:
                for v in vals:
                    datetime.strptime(v, fmt)
                return 'date'
            except ValueError:
                continue
        return 'string'

    return [guess([r[i] for r in rows if i < len(r)]) for i in range(len(header))]
