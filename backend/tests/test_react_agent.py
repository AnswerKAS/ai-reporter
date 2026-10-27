"""Agent tool loops and read-only SQL behavior."""

import pytest

from app.agent import readonly, runner
from app.datasets.base import DatasetError
from app.query import interpret
from app.reports import executor
from app.schemas.definition import SectionDefinition
from tests.fakesource import FakeSource


def test_agent_model_call_uses_chat_timeout(monkeypatch):
    """Report-agent calls use the configured chat timeout instead of 45 seconds."""
    observed = []

    def fake_ask(_prompt, _model, _key, *, timeout):
        """Record the timeout supplied to the model call."""
        observed.append(timeout)
        return '{"final":{"reply":"Готово"}}'

    monkeypatch.setattr(interpret, '_ask', fake_ask)

    assert runner._invoke('prompt', 'model', 'key') == {'final': {'reply': 'Готово'}}
    assert observed == [interpret.CHAT_TIMEOUT]


def test_agent_extracts_action_from_explanation_and_fenced_json():
    """Extra prose and example JSON do not hide the model's actual action."""
    raw = ('Пример: {"tool":"unknown"}\n'
           '```json\n{"tool":"preview_report","args":{"definition":{"sections":[]}}}\n```')
    assert runner._action(raw)['tool'] == 'preview_report'
    assert runner._action('```json\n{"final":{"reply":"готово"}}\n```') == {
        'final': {'reply': 'готово'}}


def test_report_agent_retries_other_dataset_when_attached(dataset, monkeypatch):
    """An explicit mention makes the agent repair a section on the wrong dataset."""
    actions = iter([
        {'tool': 'get_datasets'},
        {'tool': 'preview_report', 'args': {'definition': {'sections': [{
            'type': 'table', 'datasetSlug': 'other',
            'sql': 'SELECT count(*) AS total FROM dataset',
        }]}}},
        {'tool': 'preview_report', 'args': {'definition': {'sections': [{
            'type': 'table', 'datasetSlug': 'sales',
            'sql': 'SELECT count(*) AS total FROM dataset',
        }]}}},
        {'final': {'reply': 'Готово'}},
    ])

    class Catalog:
        """Expose the attached and an unrelated dataset."""
        metrics = {}
        dimensions = {}

        def __init__(self):
            """Store both datasets for the agent."""
            self.datasets = {'sales': dataset, 'other': {**dataset, 'slug': 'other'}}

        def dataset(self, slug):
            """Resolve a registered dataset by slug."""
            return self.datasets[slug]

    monkeypatch.setattr(interpret, '_openrouter_key', lambda: 'fake')
    monkeypatch.setattr(interpret, '_chat_models', lambda: ('fake-model', None))
    monkeypatch.setattr(runner, '_invoke', lambda *_: next(actions))
    monkeypatch.setattr(executor, 'build_section', lambda *_args, **_kwargs: {
        'type': 'table', 'title': 'Продажи', 'columns': [], 'rows': []})
    result = runner.chat_report([{'role': 'user', 'text': 'Продажи'}], Catalog(),
                                attached_datasets=['sales'])
    assert result['definition']['sections'][0]['datasetSlug'] == 'sales'


def test_report_agent_preserves_attached_join_dependencies(dataset, monkeypatch):
    """A joined SQL block keeps its attached dataset list after preview."""
    second = {**dataset, 'slug': 'costs', 'title': 'Расходы', 'table_name': 'costs'}
    observed = []

    class Catalog:
        """Expose two compatible datasets for a report proposal."""

        metrics = {}
        dimensions = {}

        def __init__(self):
            """Store the datasets available to the report agent."""
            self.datasets = {'sales': dataset, 'costs': second}

        def dataset(self, slug):
            """Resolve a dataset for preview rendering."""
            return self.datasets[slug]

    def fake_build(section, *_args, **_kwargs):
        """Record the joined relations present in the previewed section."""
        observed.append(section.join_dataset_slugs)
        return {'type': 'table', 'title': section.title, 'columns': [], 'rows': []}

    monkeypatch.setattr(interpret, '_openrouter_key', lambda: 'fake')
    monkeypatch.setattr(interpret, '_chat_models', lambda: ('fake-model', None))
    monkeypatch.setattr(runner, '_invoke', lambda *_: {
        'tool': 'preview_report', 'args': {'definition': {'sections': [{
            'type': 'table', 'title': 'Продажи и расходы', 'datasetSlug': 'sales',
            'joinDatasetSlugs': ['costs'],
            'sql': 'SELECT * FROM dataset LEFT JOIN dataset_2 USING (id)',
        }]}}})
    monkeypatch.setattr(executor, 'build_section', fake_build)

    result = runner.chat_report([{'role': 'user', 'text': 'Сравни продажи и расходы'}],
                                Catalog(), attached_datasets=['sales', 'costs'])

    assert observed == [['costs']]
    assert result['definition']['sections'][0]['joinDatasetSlugs'] == ['costs']


def test_report_agent_rejects_unattached_join_dataset(dataset, monkeypatch):
    """Preview returns an unattached JOIN dependency for model repair."""
    second = {**dataset, 'slug': 'costs', 'title': 'Расходы'}

    class Catalog:
        """Expose both registered datasets while attaching only one."""

        metrics = {}
        dimensions = {}

        def __init__(self):
            """Store both datasets in the catalog."""
            self.datasets = {'sales': dataset, 'costs': second}

        def dataset(self, slug):
            """Resolve a catalog dataset for preview."""
            return self.datasets[slug]

    prompts = []

    def fake_invoke(prompt, *_args):
        """Return an invalid JOIN first and capture the repair observation."""
        prompts.append(prompt)
        return {'tool': 'preview_report', 'args': {'definition': {'sections': [{
            'type': 'table', 'datasetSlug': 'sales',
            'joinDatasetSlugs': ['costs'] if len(prompts) == 1 else [],
            'sql': 'SELECT * FROM dataset',
        }]}}}

    monkeypatch.setattr(interpret, '_openrouter_key', lambda: 'fake')
    monkeypatch.setattr(interpret, '_chat_models', lambda: ('fake-model', None))
    monkeypatch.setattr(runner, '_invoke', fake_invoke)
    monkeypatch.setattr(executor, 'build_section', lambda *_args, **_kwargs: {
        'type': 'table', 'title': 'Продажи', 'columns': [], 'rows': []})

    runner.chat_report([{'role': 'user', 'text': 'Продажи'}], Catalog(),
                       attached_datasets=['sales'])

    assert 'не на прикреплённый датасет' in prompts[1]


def test_report_agent_sees_failed_sql_before_repair(dataset, monkeypatch):
    """A failed preview returns both SQL and database error to the next model step."""
    actions = [
        {'tool': 'get_datasets'},
        {'tool': 'preview_report', 'args': {'definition': {'sections': [{
            'type': 'table', 'datasetSlug': 'sales',
            'sql': 'SELECT missing_column FROM dataset',
        }]}}},
        {'tool': 'preview_report', 'args': {'definition': {'sections': [{
            'type': 'table', 'datasetSlug': 'sales',
            'sql': 'SELECT city FROM dataset',
        }]}}},
        {'final': {'reply': 'Готово'}},
    ]

    class Catalog:
        """Expose a single attached dataset to the report agent."""
        metrics = {}
        dimensions = {}

        def __init__(self):
            """Store the selected dataset."""
            self.datasets = {'sales': dataset}

        def dataset(self, slug):
            """Resolve the attached dataset."""
            return self.datasets[slug]

    prompts = []

    def fake_invoke(prompt, *_args):
        """Check that the repair step can see its failed SQL and source error."""
        prompts.append(prompt)
        return actions[len(prompts) - 1]

    def fake_build(section, *_args, **_kwargs):
        """Simulate a database rejecting one column and accepting the next."""
        if 'missing_column' in section.sql:
            raise DatasetError('Unknown identifier missing_column')
        return {'type': 'table', 'title': 'Исправлено', 'columns': [], 'rows': []}

    monkeypatch.setattr(interpret, '_openrouter_key', lambda: 'fake')
    monkeypatch.setattr(interpret, '_chat_models', lambda: ('fake-model', None))
    monkeypatch.setattr(runner, '_invoke', fake_invoke)
    monkeypatch.setattr(executor, 'build_section', fake_build)
    result = runner.chat_report([{'role': 'user', 'text': 'Отчёт по городам'}],
                                Catalog(), attached_datasets=['sales'])
    assert result['definition']['sections'][0]['sql'] == 'SELECT city FROM dataset'
    assert 'SELECT missing_column FROM dataset' in prompts[2]
    assert 'Unknown identifier missing_column' in prompts[2]


def test_report_agent_uses_attached_schema_without_selected_fields(dataset, monkeypatch):
    """The agent can inspect an attached dataset and propose SQL with no field picks."""
    actions = [
        {'tool': 'get_datasets'},
        {'tool': 'sample_dataset', 'args': {'datasetSlug': 'sales'}},
        {'tool': 'preview_report', 'args': {'definition': {'sections': [{
            'type': 'chart', 'kind': 'line', 'datasetSlug': 'sales',
            'sql': 'SELECT day, SUM(revenue) AS total FROM dataset GROUP BY day',
        }]}}},
        {'final': {'reply': 'Построил динамику.'}},
    ]

    class Catalog:
        """Expose an attached dataset without any semantic fields."""
        metrics = {}
        dimensions = {}

        def __init__(self):
            """Store the attached dataset."""
            self.datasets = {'sales': dataset}

        def dataset(self, slug):
            """Resolve the attached dataset."""
            return self.datasets[slug]

    prompts = []

    def fake_invoke(prompt, *_args):
        """Capture schema and sample observations sent to the agent."""
        prompts.append(prompt)
        return actions[len(prompts) - 1]

    monkeypatch.setattr(interpret, '_openrouter_key', lambda: 'fake')
    monkeypatch.setattr(interpret, '_chat_models', lambda: ('fake-model', None))
    monkeypatch.setattr(runner, '_invoke', fake_invoke)
    monkeypatch.setattr(runner, '_sample', lambda _dataset: {
        'columns': ['day', 'revenue'], 'rows': [['2026-01-01', '100']]})
    monkeypatch.setattr(executor, 'build_section', lambda section, *_args, **_kwargs: {
        'type': section.type, 'title': section.title, 'data': [], 'series': []})
    result = runner.chat_report([{'role': 'user', 'text': 'Динамика продаж'}],
                                Catalog(), attached_datasets=['sales'])
    assert result['definition']['sections'][0]['datasetSlug'] == 'sales'
    assert '"name": "revenue"' in prompts[1]
    assert '2026-01-01' in prompts[2]


@pytest.mark.parametrize('sql', [
    'SELECT city, SUM(revenue) OVER (PARTITION BY city) AS total FROM dataset',
    'WITH ranked AS (SELECT row_number() OVER (ORDER BY revenue) AS n FROM dataset) SELECT * FROM ranked',
    'SELECT 5 % 2 AS remainder FROM dataset',
])
def test_readonly_sql_accepts_analytical_queries(sql):
    """Window functions, CTEs and expressions remain available."""
    assert readonly.validate_readonly_sql(sql) == sql


@pytest.mark.parametrize('sql', [
    'DELETE FROM dataset',
    'WITH erased AS (DELETE FROM dataset RETURNING *) SELECT * FROM erased',
    'SELECT * INTO copied FROM dataset',
    'SELECT * FROM dataset; DROP TABLE dataset',
    'SELECT * FROM dataset FOR UPDATE',
])
def test_readonly_sql_rejects_mutations(sql):
    """A single read-only statement is the only permitted tool input."""
    with pytest.raises(DatasetError):
        readonly.validate_readonly_sql(sql)


def test_dataset_sql_rejects_other_source_tables(dataset, sources):
    """A dataset question cannot query another table on the same connection."""
    with pytest.raises(DatasetError):
        readonly.scope_dataset_sql(dataset, 'SELECT * FROM private_table')


@pytest.mark.parametrize('sql', [
    'SELECT * FROM dataset LEFT JOIN private_table p ON dataset.id = p.id',
    'WITH hidden AS (SELECT * FROM private_table) SELECT * FROM hidden',
    'SELECT * FROM dataset WHERE EXISTS (SELECT 1 FROM private_table)',
    'SELECT * FROM remote("host")',
    'WITH dataset AS (SELECT * FROM private_table) SELECT * FROM dataset',
])
def test_dataset_sql_rejects_hidden_source_references(dataset, sql):
    """Nested queries and relation functions cannot escape dataset relations."""
    with pytest.raises(DatasetError):
        readonly.scope_dataset_sql(dataset, sql)


@pytest.mark.parametrize('join_type', ['INNER', 'LEFT', 'RIGHT', 'FULL', 'CROSS'])
def test_dataset_sql_joins_attached_dataset_relations(dataset, sources, join_type):
    """Every ordinary join type can use a second dataset on the same connection."""
    second = {**dataset, 'slug': 'costs', 'title': 'Расходы', 'table_name': 'costs'}
    sources.add('costs', FakeSource(source='clickhouse', table='costs'))
    join = f'{join_type} JOIN dataset_2 c'
    predicate = '' if join_type == 'CROSS' else ' ON s.id = c.id'
    query = f'SELECT * FROM dataset s {join}{predicate}'

    scoped = readonly.scope_dataset_sql(dataset, query, datasets=[second])

    assert 'dataset_2 AS (SELECT * FROM' in scoped
    assert 'costs' in scoped
    assert query in scoped


def test_dataset_sql_rejects_join_across_connections(dataset, sources):
    """A second virtual dataset cannot point at another connection."""
    second = {**dataset, 'slug': 'costs', 'dsn': 'clickhouse://other/db'}
    with pytest.raises(DatasetError, match='подключен'):
        readonly.scope_dataset_sql(dataset, 'SELECT * FROM dataset JOIN dataset_2 USING (id)',
                                   datasets=[second])


def test_joinable_datasets_skips_broken_connections(dataset):
    """One broken catalog entry cannot prevent a report agent from starting."""
    broken = {**dataset, 'slug': 'broken', 'dsn': 'invalid://source'}

    assert readonly.joinable_datasets(dataset, [broken]) == []
    assert readonly.joinable_datasets(broken, [dataset]) == []


@pytest.mark.parametrize('source,dsn', [
    ('postgres', 'postgresql://user:pass@host:5432/db'),
    ('oracle', 'oracle://user:pass@host:1521/db'),
])
def test_dataset_sql_keeps_cte_joins_across_dialects(dataset, sources, source, dsn):
    """PostgreSQL and Oracle keep CTEs while joining granted virtual datasets."""
    primary = {**dataset, 'source': source, 'dsn': dsn, 'table_name': 'orders'}
    second = {**primary, 'slug': 'costs', 'table_name': 'costs'}
    sources.add('sales', FakeSource(source=source, table='orders'))
    sources.add('costs', FakeSource(source=source, table='costs'))
    query = ('WITH totals AS (SELECT id FROM dataset) '
             'SELECT * FROM totals t FULL JOIN dataset_2 c ON t.id = c.id')

    scoped = readonly.scope_dataset_sql(primary, query, datasets=[second])

    assert scoped.startswith('WITH dataset AS (SELECT * FROM')
    assert 'dataset_2 AS (SELECT * FROM' in scoped
    assert 'totals AS (SELECT id FROM dataset)' in scoped


def test_report_sql_section_keeps_joined_datasets(dataset, sources, monkeypatch):
    """A saved SQL block expands the same joined dataset when rendered again."""
    second = {**dataset, 'slug': 'costs', 'title': 'Расходы', 'table_name': 'costs'}
    sources.add('costs', FakeSource(source='clickhouse', table='costs'))
    captured = []

    class Catalog:
        """Resolve the two datasets used by one SQL report block."""

        dimensions = {}

        def dataset(self, slug):
            """Return only one of the registered SQL block datasets."""
            return {'sales': dataset, 'costs': second}[slug]

    def fake_execute(_dataset, sql, **_kwargs):
        """Capture the SQL used to render the report block."""
        captured.append(sql)
        return ['city', 'cost'], [['Москва', 20]], False

    monkeypatch.setattr(executor, 'execute_readonly_sql', fake_execute)
    section = SectionDefinition.model_validate({
        'type': 'table', 'datasetSlug': 'sales', 'joinDatasetSlugs': ['costs'],
        'sql': 'SELECT s.city, c.cost FROM dataset s LEFT JOIN dataset_2 c ON s.id = c.id',
    })

    result = executor.build_section(section, {}, Catalog())

    assert result['rows'] == [{'city': 'Москва', 'cost': 20}]
    assert 'dataset_2 AS (SELECT * FROM' in captured[0]
    assert 'LEFT JOIN dataset_2 c' in captured[0]


def test_dataset_agent_executes_window_query(dataset, sources, monkeypatch):
    """The agent uses a SQL tool before answering from observed rows."""
    actions = iter([
        {'tool': 'describe_schema'},
        {'tool': 'execute_sql', 'args': {'sql':
            'SELECT city, SUM(revenue) OVER (PARTITION BY city) AS total FROM dataset'}},
        {'final': {'answer': 'Выручка по городу: 100',
                   'calculations': ['Оконная сумма выручки по городу'],
                   'groupBy': ['city'], 'filters': [], 'orderBy': None,
                   'scope': 'Все строки датасета',
                   'columnLabels': {'city': 'Город', 'total': 'Выручка'},
                   'tableTitles': {'sales': 'Выручка по городам'}}},
    ])
    monkeypatch.setattr(interpret, '_openrouter_key', lambda: 'fake')
    monkeypatch.setattr(interpret, '_chat_models', lambda: ('fake-model', None))
    monkeypatch.setattr(runner, '_invoke', lambda *_: next(actions))
    monkeypatch.setattr(runner, 'execute_readonly_sql', lambda _dataset, _sql: (
        ['city', 'total'], [['Москва', 100]], False))

    response = runner.ask_dataset(dataset, 'Выручка по городам', [], reveal_sql=False)

    assert response['rows'] == [['Москва', '100']]
    assert response['columns'] == ['Город', 'Выручка']
    assert response['title'] == 'Выручка по городам'
    assert response['evidence'][0]['title'] == 'Выручка по городам'
    assert 'OVER (PARTITION BY city)' in response['sql']
    assert response['explanation']['calculations'] == ['Оконная сумма выручки по городу']


def test_dataset_agent_compares_attached_datasets_with_evidence(dataset, monkeypatch):
    """A comparative answer requires and exposes observed rows from both sources."""
    second = {**dataset, 'slug': 'costs', 'title': 'Расходы',
              'schema': [{'name': 'month', 'type': 'String'},
                         {'name': 'cost', 'type': 'Float64'}]}
    actions = iter([
        {'tool': 'describe_schema'},
        {'tool': 'execute_sql', 'args': {'datasetSlug': 'sales',
            'sql': 'SELECT s.month, sum(s.revenue) AS amount FROM dataset s '
                   'LEFT JOIN dataset_2 c ON s.month = c.month GROUP BY s.month'}},
        {'final': {'answer': 'Предварительно выручка растёт быстрее расходов.'}},
        {'tool': 'execute_sql', 'args': {'datasetSlug': 'costs',
            'sql': 'SELECT month, sum(cost) AS amount FROM dataset GROUP BY month'}},
        {'final': {'answer': 'Выручка 100, расходы 80',
                   'columnLabels': {'month': 'Месяц', 'amount': 'Выручка'}}},
        {'final': {'answer': 'Выручка 100, расходы 80; рост маржи — гипотеза.',
                   'hypotheses': [{'text': 'Маржа могла вырасти',
                                   'howToCheck': 'Сравнить одинаковые периоды'}],
                   'columnLabels': {'sales': {'month': 'Месяц', 'amount': 'Выручка'},
                                    'costs': {'month': 'Месяц', 'amount': 'Расходы'}},
                   'tableTitles': {'sales': 'Выручка по месяцам',
                                   'costs': 'Расходы по месяцам'}}},
    ])
    observed = []
    queries = []

    def fake_query(source, sql):
        """Return a distinct verified aggregate for each attached source."""
        observed.append(source['slug'])
        queries.append(sql)
        return ['month', 'amount'], [['2026-01', 100 if source['slug'] == 'sales' else 80]], False

    monkeypatch.setattr(interpret, '_openrouter_key', lambda: 'fake')
    monkeypatch.setattr(interpret, '_chat_models', lambda: ('fake-model', None))
    monkeypatch.setattr(runner, '_invoke', lambda *_: next(actions))
    monkeypatch.setattr(runner, 'execute_readonly_sql', fake_query)

    response = runner.ask_datasets([dataset, second], 'Сравни продажи и расходы', [],
                                   reveal_sql=True)

    assert observed == ['sales', 'costs']
    assert 'dataset_2 AS (SELECT * FROM' in queries[0]
    assert [item['datasetSlug'] for item in response['evidence']] == ['sales', 'costs']
    assert response['evidence'][0]['columns'] == ['Месяц', 'Выручка']
    assert [item['title'] for item in response['evidence']] == [
        'Выручка по месяцам', 'Расходы по месяцам']
    assert response['evidence'][1]['rows'] == [['2026-01', '80']]
    assert response['hypotheses'][0]['howToCheck'] == 'Сравнить одинаковые периоды'


def test_dataset_agent_reuses_sql_when_switching_models(dataset, monkeypatch):
    """Fallback finalizes previous SQL evidence without repeating source queries."""
    second = {**dataset, 'slug': 'costs', 'title': 'Расходы'}
    calls = []
    queries = []

    def fake_invoke(prompt, model, _key):
        """Keep the primary model exploring and let the fallback finish."""
        calls.append((model, prompt))
        if model == 'primary':
            slug = 'sales' if sum(name == 'primary' for name, _ in calls) % 2 else 'costs'
            return {'tool': 'execute_sql', 'args': {
                'datasetSlug': slug, 'sql': 'SELECT city, revenue FROM dataset'}}
        return {'final': {'answer': 'Продажи выше расходов.',
                          'columnLabels': {
                              'sales': {'city': 'Город', 'revenue': 'Выручка'},
                              'costs': {'city': 'Город', 'revenue': 'Расходы'}},
                          'tableTitles': {'sales': 'Продажи по городам',
                                          'costs': 'Расходы по городам'}}}

    def fake_execute(source, _sql):
        """Count source queries across both model attempts."""
        queries.append(source['slug'])
        return ['city', 'revenue'], [['Москва', 100]], False

    monkeypatch.setattr(interpret, '_openrouter_key', lambda: 'fake')
    monkeypatch.setattr(interpret, '_chat_models', lambda: ('primary', 'fallback'))
    monkeypatch.setattr(runner, '_invoke', fake_invoke)
    monkeypatch.setattr(runner, 'execute_readonly_sql', fake_execute)

    response = runner.ask_datasets([dataset, second], 'Сравни результаты', [],
                                   reveal_sql=True)

    assert response['answer'] == 'Продажи выше расходов.'
    assert queries == ['sales', 'costs', 'sales', 'costs']
    assert [name for name, _ in calls] == ['primary'] * 5 + ['fallback']
    assert 'Проверенные результаты предыдущей модели' in calls[-1][1]


def test_dataset_agent_sends_validated_final_without_rewording(dataset, monkeypatch):
    """A checked final answer is streamed once without another model call."""
    actions = iter([
        {'tool': 'execute_sql', 'args': {'sql': 'SELECT count(*) AS total FROM dataset'}},
        {'final': {'answer': '**Итого:** 1 запись.',
                   'columnLabels': {'total': 'Количество'},
                   'tableTitles': {'sales': 'Количество записей'}}},
    ])
    events = []
    calls = []

    def fake_invoke(prompt, *_args):
        """Capture the table instruction and supply fixed model actions."""
        calls.append(prompt)
        return next(actions)

    monkeypatch.setattr(interpret, '_openrouter_key', lambda: 'fake')
    monkeypatch.setattr(interpret, '_chat_models', lambda: ('primary', None))
    monkeypatch.setattr(runner, '_invoke', fake_invoke)
    monkeypatch.setattr(runner, 'execute_readonly_sql', lambda *_args: (
        ['total'], [[1]], False))

    response = runner.ask_dataset(dataset, 'Сколько строк?', [], reveal_sql=True,
                                  on_event=events.append)

    assert response['answer'] == '**Итого:** 1 запись.'
    assert len(calls) == 2
    assert 'По умолчанию показывай одну итоговую таблицу' in calls[0]
    assert [event for event in events if event['type'] == 'delta'] == [
        {'type': 'delta', 'text': response['answer']}]


def test_dataset_agent_uses_latest_result_instead_of_exploratory_queries(dataset, monkeypatch):
    """A final answer only needs labels for the latest SQL result of each source."""
    actions = iter([
        {'tool': 'execute_sql', 'args': {'sql': 'SELECT count(*) AS cnt FROM dataset'}},
        {'tool': 'execute_sql', 'args': {'sql': 'SELECT city, sum(revenue) AS total FROM dataset GROUP BY city'}},
        {'final': {'answer': 'Москва: 100',
                   'columnLabels': {'city': 'Город', 'total': 'Выручка'},
                   'tableTitles': {'sales': 'Выручка по городам'}}},
    ])
    monkeypatch.setattr(interpret, '_openrouter_key', lambda: 'fake')
    monkeypatch.setattr(interpret, '_chat_models', lambda: ('fake-model', None))
    monkeypatch.setattr(runner, '_invoke', lambda *_: next(actions))
    monkeypatch.setattr(runner, 'execute_readonly_sql', lambda _dataset, sql: (
        (['cnt'], [[1]], False) if 'AS cnt' in sql else
        (['city', 'total'], [['Москва', 100]], False)))

    response = runner.ask_datasets([dataset], 'Выручка по городам', [], reveal_sql=True)

    assert response['columns'] == ['Город', 'Выручка']
    assert response['rows'] == [['Москва', '100']]
    assert len(response['evidence']) == 1
    assert len(response['plan']['queries']) == 1
    assert 'GROUP BY city' in response['sql']


def test_dataset_agent_repairs_missing_table_title(dataset, monkeypatch):
    """A missing result title returns to the model before any table is shown."""
    actions = iter([
        {'tool': 'execute_sql', 'args': {'sql': 'SELECT count(*) AS total FROM dataset'}},
        {'final': {'answer': 'Одна запись',
                   'columnLabels': {'total': 'Количество'}}},
        {'final': {'answer': 'Одна запись',
                   'columnLabels': {'total': 'Количество'},
                   'tableTitles': {'sales': 'Количество записей'}}},
    ])
    prompts = []

    def fake_invoke(prompt, *_args):
        """Capture the repair observation delivered to the model."""
        prompts.append(prompt)
        return next(actions)

    monkeypatch.setattr(interpret, '_openrouter_key', lambda: 'fake')
    monkeypatch.setattr(interpret, '_chat_models', lambda: ('fake-model', None))
    monkeypatch.setattr(runner, '_invoke', fake_invoke)
    monkeypatch.setattr(runner, 'execute_readonly_sql', lambda *_: (['total'], [[1]], False))

    response = runner.ask_datasets([dataset], 'Сколько строк?', [], reveal_sql=True)

    assert 'final.tableTitles' in prompts[2]
    assert response['title'] == 'Количество записей'


def test_dataset_agent_accepts_nested_russian_column_labels(dataset):
    """A model's structured Russian label maps to the matching SQL column."""
    assert runner._russian_columns(
        ['total'], {'columnLabels': {'total': {'sql_column': 'total',
                                              'Русское название': 'Выручка'}}}, dataset
    ) == ['Выручка']


def test_dataset_agent_rejects_query_for_unattached_dataset(dataset, monkeypatch):
    """A model action cannot query a source that the user did not attach."""
    actions = iter([
        {'tool': 'execute_sql', 'args': {'datasetSlug': 'other',
            'sql': 'SELECT count(*) FROM dataset'}},
        {'tool': 'execute_sql', 'args': {'datasetSlug': 'sales',
            'sql': 'SELECT count(*) AS total FROM dataset'}},
        {'final': {'answer': 'Одна строка', 'columnLabels': {'total': 'Количество'},
                   'tableTitles': {'sales': 'Количество записей'}}},
    ])
    prompts = []

    def fake_invoke(prompt, *_args):
        """Capture the error observation before the agent repairs its action."""
        prompts.append(prompt)
        return next(actions)

    monkeypatch.setattr(interpret, '_openrouter_key', lambda: 'fake')
    monkeypatch.setattr(interpret, '_chat_models', lambda: ('fake-model', None))
    monkeypatch.setattr(runner, '_invoke', fake_invoke)
    monkeypatch.setattr(runner, 'execute_readonly_sql', lambda *_: (['total'], [[1]], False))
    response = runner.ask_datasets([dataset], 'Сколько строк?', [], reveal_sql=True)

    assert 'не прикреплён' in prompts[1]
    assert response['rows'] == [['1']]


def test_dataset_agent_uses_configured_russian_column_titles(dataset):
    """Dataset field names and administrator labels take precedence over raw SQL names."""
    dataset['schema'] = [{'name': 'city', 'type': 'String', 'comment': 'Город из БД'},
                         {'name': 'revenue', 'type': 'Float64', 'comment': ''}]
    dataset['field_settings'] = {'city': {'title': 'Город продажи'}}
    assert runner._russian_columns(['city', 'revenue'],
                                   {'columnLabels': {'revenue': 'Выручка'}}, dataset) == [
        'Город продажи', 'Выручка']


def test_dataset_agent_requires_russian_column_titles(dataset):
    """An unknown SQL alias must be translated before its table reaches the user."""
    with pytest.raises(DatasetError, match='columnLabels'):
        runner._russian_columns(['opaque_alias'], {}, dataset)


def test_dataset_agent_resolves_duplicate_configured_titles(dataset):
    """A final label can disambiguate fields with the same saved title."""
    dataset['schema'] = [{'name': 'a', 'type': 'String'}, {'name': 'b', 'type': 'String'}]
    dataset['field_settings'] = {'a': {'title': 'Сумма'}, 'b': {'title': 'Сумма'}}
    assert runner._russian_columns(['a', 'b'],
                                   {'columnLabels': {'b': 'Сумма возвратов'}}, dataset) == [
        'Сумма', 'Сумма возвратов']


def test_report_agent_previews_sql_section(dataset, monkeypatch):
    """A SQL table is rendered through the report executor before proposal."""
    actions = iter([
        {'tool': 'get_datasets'},
        {'tool': 'preview_report', 'args': {'definition': {'sections': [{
            'type': 'table', 'datasetSlug': 'sales', 'sql':
                'SELECT city, ROW_NUMBER() OVER (ORDER BY revenue) AS rank FROM dataset',
        }]}}},
        {'final': {'reply': 'Построил таблицу с рангом.', 'title': 'Рейтинг'}},
    ])

    class Catalog:
        """Minimal semantic catalog for the report agent."""

        metrics = {}
        dimensions = {}

        def __init__(self, selected_dataset):
            """Store the selected registered dataset."""
            self.datasets = {'sales': selected_dataset}

        def dataset(self, slug):
            """Resolve a registered dataset by slug."""
            return self.datasets[slug]

    monkeypatch.setattr(interpret, '_openrouter_key', lambda: 'fake')
    monkeypatch.setattr(interpret, '_chat_models', lambda: ('fake-model', None))
    monkeypatch.setattr(runner, '_invoke', lambda *_: next(actions))
    monkeypatch.setattr(executor, 'execute_readonly_sql', lambda *_args, **_kwargs: (
        ['city', 'rank'], [['Москва', 1]], False))

    response = runner.chat_report([{'role': 'user', 'text': 'Рейтинг городов'}], Catalog(dataset))

    assert response['source'] == 'agent'
    assert response['definition']['sections'][0]['datasetSlug'] == 'sales'
    assert 'ROW_NUMBER()' in response['definition']['sections'][0]['sql']


def test_report_agent_accepts_blocks_alias_from_model(dataset, monkeypatch):
    """A model draft using blocks still reaches normal section validation."""
    actions = iter([
        {'tool': 'get_datasets'},
        {'tool': 'preview_report', 'args': {'definition': {'blocks': [{
            'type': 'table', 'title': 'Продажи', 'datasetSlug': 'sales',
            'sql': 'SELECT city, revenue FROM dataset',
        }]}}},
        {'final': {'reply': 'Готово'}},
    ])

    class Catalog:
        """Expose one attached dataset to the report agent."""
        metrics = {}
        dimensions = {}

        def __init__(self):
            """Store the dataset under its slug."""
            self.datasets = {'sales': dataset}

        def dataset(self, slug):
            """Resolve a registered dataset by slug."""
            return self.datasets[slug]

    monkeypatch.setattr(interpret, '_openrouter_key', lambda: 'fake')
    monkeypatch.setattr(interpret, '_chat_models', lambda: ('fake-model', None))
    monkeypatch.setattr(runner, '_invoke', lambda *_args: next(actions))
    monkeypatch.setattr(executor, 'build_section', lambda section, *_args, **_kwargs: {
        'type': section.type, 'title': section.title, 'columns': [], 'rows': []})
    result = runner.chat_report([{'role': 'user', 'text': 'Продажи'}], Catalog(),
                                attached_datasets=['sales'])
    assert result['definition']['sections'][0]['title'] == 'Продажи'


def test_report_agent_previews_mixed_visual_blocks(dataset, monkeypatch):
    """KPI, line chart and table are checked before the full layout is returned."""
    sections = [
        {'type': 'kpi', 'title': 'Продажи', 'datasetSlug': 'sales',
         'sql': 'SELECT count(*) AS total FROM dataset'},
        {'type': 'chart', 'kind': 'line', 'title': 'Динамика', 'datasetSlug': 'sales',
         'sql': 'SELECT day, sum(revenue) AS total FROM dataset GROUP BY day'},
        {'type': 'table', 'title': 'Детали', 'datasetSlug': 'sales',
         'sql': 'SELECT city, revenue FROM dataset'},
    ]
    actions = iter([{'tool': 'get_datasets'},
                    {'tool': 'preview_report', 'args': {'definition': {'sections': sections}}},
                    {'final': {'reply': 'Готово', 'title': 'Продажи'}}])

    class Catalog:
        """Expose the selected dataset to the visual report agent."""
        metrics = {}
        dimensions = {}

        def __init__(self):
            """Store the selected registered dataset."""
            self.datasets = {'sales': dataset}

        def dataset(self, slug):
            """Resolve the selected dataset for a report section."""
            return self.datasets[slug]

    previewed = []

    def fake_build(section, *_args, **_kwargs):
        """Record that each visual section was rendered."""
        previewed.append(section.type)
        return {'type': section.type, 'title': section.title,
                'items': [], 'rows': [], 'data': [], 'columns': [], 'series': []}

    monkeypatch.setattr(interpret, '_openrouter_key', lambda: 'fake')
    monkeypatch.setattr(interpret, '_chat_models', lambda: ('fake-model', None))
    monkeypatch.setattr(runner, '_invoke', lambda *_: next(actions))
    monkeypatch.setattr(executor, 'build_section', fake_build)
    result = runner.chat_report([{'role': 'user', 'text': 'Продажи'}], Catalog())

    assert previewed == ['kpi', 'chart', 'table']
    assert [section['title'] for section in result['definition']['sections']] == [
        'Продажи', 'Динамика', 'Детали']


def test_report_agent_finishes_after_first_valid_preview(dataset, monkeypatch):
    """Prefetched schema and vocabulary allow one model call per valid proposal."""
    class Catalog:
        """Expose one dataset and one metric for the initial model context."""

        metrics = {'revenue': {'slug': 'revenue', 'dataset_slug': 'sales',
                               'title': 'Выручка'}}
        dimensions = {}

        def __init__(self):
            """Register the attached test dataset."""
            self.datasets = {'sales': dataset}

        def dataset(self, slug):
            """Resolve the dataset used by preview rendering."""
            return self.datasets[slug]

    prompts = []

    def fake_invoke(prompt, *_args):
        """Record the first prompt and propose a complete report."""
        prompts.append(prompt)
        return {'tool': 'preview_report', 'args': {
            'definition': {'sections': [{'type': 'table', 'title': 'Продажи',
                                         'datasetSlug': 'sales',
                                         'sql': 'SELECT city FROM dataset'}]},
            'reply': 'Построил таблицу продаж.', 'title': 'Продажи'}}

    monkeypatch.setattr(interpret, '_openrouter_key', lambda: 'fake')
    monkeypatch.setattr(interpret, '_chat_models', lambda: ('fake-model', None))
    monkeypatch.setattr(runner, '_invoke', fake_invoke)
    monkeypatch.setattr(executor, 'build_section', lambda section, *_args, **_kwargs: {
        'type': section.type, 'title': section.title, 'columns': [], 'rows': []})

    result = runner.chat_report([{'role': 'user', 'text': 'Продажи'}], Catalog(),
                                attached_datasets=['sales'])

    assert len(prompts) == 1
    assert '"name": "revenue"' in prompts[0]
    assert result['reply'] == 'Построил таблицу продаж.'
    assert result['title'] == 'Продажи'
    assert len(result['definition']['sections']) == 1


def test_report_agent_rejects_unpreviewed_definition(dataset, monkeypatch):
    """A model final action cannot bypass live card rendering."""
    actions = iter([{'final': {'reply': 'Готово', 'definition': {'sections': [
        {'type': 'kpi', 'datasetSlug': 'sales', 'sql': 'SELECT count(*) FROM dataset'}]}}},
                    {'final': {'reply': 'Готово'}}])

    class Catalog:
        """Expose one dataset while testing the finalization guard."""
        metrics = {}
        dimensions = {}

        def __init__(self):
            """Store one selected dataset."""
            self.datasets = {'sales': dataset}

    monkeypatch.setattr(interpret, '_openrouter_key', lambda: 'fake')
    monkeypatch.setattr(interpret, '_chat_models', lambda: ('fake-model', None))
    monkeypatch.setattr(runner, '_invoke', lambda *_: next(actions))

    with pytest.raises(DatasetError, match='Сначала вызови preview_report'):
        runner.chat_report([{'role': 'user', 'text': 'Продажи'}], Catalog())


def test_sql_report_section_renders_as_table(dataset, monkeypatch):
    """Saved SQL report blocks render real query columns and rows."""
    section = SectionDefinition.model_validate({
        'type': 'table', 'title': 'Рейтинг', 'datasetSlug': 'sales',
        'sql': 'SELECT city, ROW_NUMBER() OVER (ORDER BY revenue) AS rank FROM dataset',
    })

    class Catalog:
        """Resolve the selected test dataset."""

        def dataset(self, slug):
            """Return the registered dataset."""
            assert slug == 'sales'
            return dataset

    monkeypatch.setattr(executor, 'execute_readonly_sql', lambda *_args, **_kwargs: (
        ['city', 'rank'], [['Москва', 1]], False))
    result = executor.build_section(section, {}, Catalog())

    assert result['title'] == 'Рейтинг'
    assert result['rows'] == [{'city': 'Москва', 'rank': 1}]


def test_sql_report_section_applies_report_filter_before_aggregation(dataset, monkeypatch):
    """A report date filter narrows the virtual dataset used by agent SQL."""
    section = SectionDefinition.model_validate({
        'type': 'chart', 'kind': 'line', 'datasetSlug': 'sales',
        'sql': 'SELECT day, SUM(revenue) AS total FROM dataset GROUP BY day',
    })

    class Catalog:
        """Provide the source and a semantic date dimension."""
        dimensions = {'day': {'dataset_slug': 'sales', 'field': 'day', 'type': 'date'}}

        def dataset(self, slug):
            """Resolve the SQL block source."""
            assert slug == 'sales'
            return dataset

    calls = []

    def fake_execute(_dataset, sql, **kwargs):
        """Record the bounded SQL and bound filter values."""
        calls.append((sql, kwargs['parameters']))
        return ['day', 'total'], [['2026-01-01', 100]], False

    monkeypatch.setattr(executor, 'execute_readonly_sql', fake_execute)
    rendered = executor.build_section(section, {'day__from': '2026-01-01'}, Catalog())
    assert 'WHERE `day` >= {f_day__from:Date}' in calls[0][0]
    assert calls[0][1] == {'f_day__from': '2026-01-01'}
    assert rendered.get('filterNote') is None
