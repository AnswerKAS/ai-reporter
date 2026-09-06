"""Фейковый источник данных: адаптер без единой живой СУБД.

Он повторяет ровно тот контракт, который построитель и исполнитель от
адаптера ждут (`source_sql`, `run_query`, `fetch_schema`, …), и запоминает
каждый выполненный SQL — по нему тесты и проверяют, что именно собрал
построитель.
"""

import re

from app.datasets.base import DatasetAdapter, DatasetError, DatasetField

_ALIAS_RE = re.compile(r'AS\s+["`](\w+)["`]')
_UNIQUE_PROBE_RE = re.compile(r'count\(DISTINCT\s+["`]?(\w+)', re.IGNORECASE)


class FakeSource:
    """Описание одного источника: схема, данные и как он ломается."""

    def __init__(self, source: str = 'clickhouse', *, fields=None, rows=None,
                 query: str = '', table: str = 't', unique: tuple = (),
                 fail: str | None = None, fail_on: str | None = None,
                 result=None, distinct=None, row_count: int = 3) -> None:
        self.source = source
        self.fields = list(fields or [('id', 'Int64'), ('city', 'String'),
                                      ('day', 'Date'), ('revenue', 'Float64')])
        self.rows = list(rows or [[1, 'Москва', '2026-01-01', 100.0]])
        self.query = query
        self.table = table
        self.unique = set(unique)      # поля, по которым датасет уникален
        self.fail = fail               # источник недоступен целиком
        self.fail_on = fail_on         # подстрока SQL, на которой запрос падает
        self.result = result           # (columns, rows) для запросов построителя
        self.distinct = distinct       # значения для select-фильтра
        self.row_count = row_count
        self.queries: list[tuple[str, dict]] = []


class FakeAdapter(DatasetAdapter):
    def __init__(self, spec: FakeSource) -> None:
        self.spec = spec
        self.closed = False

    # --- подключение ------------------------------------------------------

    def _guard(self) -> None:
        if self.spec.fail:
            raise DatasetError(self.spec.fail)

    def test_connection(self) -> None:
        self._guard()

    def fetch_schema(self) -> list[DatasetField]:
        self._guard()
        return [DatasetField(name=n, type=t) for n, t in self.spec.fields]

    def sample_rows(self, limit: int = 50) -> tuple[list[str], list[list]]:
        self._guard()
        # настоящие адаптеры отдают превью строками (_fmt) — повторяем
        rows = [['' if v is None else str(v) for v in row] for row in self.spec.rows[:limit]]
        return [n for n, _ in self.spec.fields], rows

    # --- SQL --------------------------------------------------------------

    def quoted_table(self, table: str) -> str:
        name = table or self.spec.table
        return f'`{name}`' if self.spec.source == 'clickhouse' else f'"{name}"'

    def source_sql(self, alias: str = '') -> str:
        body = f'({self.spec.query})' if self.spec.query else self.quoted_table('')
        if not alias:
            return body
        # Oracle не терпит AS перед алиасом таблицы — как и настоящий адаптер
        return f'{body} {alias}' if self.spec.source == 'oracle' else f'{body} AS {alias}'

    def run_query(self, sql: str, params: dict | None = None) -> tuple[list[str], list[list]]:
        self._guard()
        self.spec.queries.append((sql, dict(params or {})))
        if self.spec.fail_on and self.spec.fail_on in sql:
            raise DatasetError(f'запрос не выполнен: {self.spec.fail_on}')

        probe = _UNIQUE_PROBE_RE.search(sql)
        if probe and 'count(*)' in sql:
            # проверка уникальности ключа связи: total vs keys
            field = probe.group(1)
            total = 10
            return ['total', 'keys'], [[total, total if field in self.spec.unique else total - 1]]
        if sql.lstrip().upper().startswith('SELECT DISTINCT'):
            values = self.spec.distinct if self.spec.distinct is not None else ['Москва', 'Тверь']
            return ['value'], [[v] for v in values]
        if self.spec.result is not None:
            return self.spec.result
        return self._synthetic(sql)

    def _synthetic(self, sql: str) -> tuple[list[str], list[list]]:
        """Правдоподобная выдача по алиасам запроса: числа нулями, разрезы буквами."""
        head = sql.split('\nFROM', 1)[0]
        columns: list[str] = []
        for name in _ALIAS_RE.findall(head):
            if name not in columns:
                columns.append(name)
        if not columns:
            columns = [n for n, _ in self.spec.fields]
        rows = []
        for i in range(self.spec.row_count):
            rows.append([
                (i + 1) * 100.0 if column.startswith('m_') else f'знач{i + 1}'
                for column in columns
            ])
        return columns, rows

    def close(self) -> None:
        self.closed = True


class Sources:
    """Реестр фейковых источников: slug датасета → его поведение."""

    def __init__(self) -> None:
        self.specs: dict[str, FakeSource] = {}
        self.adapters: list[FakeAdapter] = []
        # настоящая фабрика адаптеров: нужна тестам, которые проверяют
        # источник целиком (например CSV — он читает файл, а не сеть)
        self.real_adapter_for = None

    def add(self, slug: str, spec: FakeSource | None = None, **kwargs) -> FakeSource:
        self.specs[slug] = spec or FakeSource(**kwargs)
        return self.specs[slug]

    def get(self, slug: str) -> FakeSource:
        return self.specs.setdefault(slug, FakeSource())

    def adapter_for(self, dataset: dict, reuse: bool = False) -> FakeAdapter:
        spec = self.get(dataset['slug'])
        spec.source = dataset.get('source') or spec.source
        spec.query = (dataset.get('query') or '').strip() or spec.query
        spec.table = dataset.get('table_name') or spec.table
        adapter = FakeAdapter(spec)
        self.adapters.append(adapter)
        return adapter

    def install(self, monkeypatch) -> 'Sources':
        from app.datasets import registry as dataset_registry

        self.real_adapter_for = dataset_registry.adapter_for
        monkeypatch.setattr(dataset_registry, 'adapter_for', self.adapter_for)
        return self

    def uninstall(self, monkeypatch) -> None:
        # вернуть настоящую фабрику адаптеров на время одного теста
        from app.datasets import registry as dataset_registry

        monkeypatch.setattr(dataset_registry, 'adapter_for', self.real_adapter_for)
