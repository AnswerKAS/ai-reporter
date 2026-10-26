"""Agent tool loops and read-only SQL behavior."""

import pytest

from app.agent import readonly, runner
from app.datasets.base import DatasetError
from app.query import interpret
from app.reports import executor
from app.schemas.definition import SectionDefinition


def test_agent_model_call_uses_chat_timeout(monkeypatch):
    """A report-agent model call must not fail at the obsolete 45-second limit."""
    observed = []

    def fake_ask(_prompt, _model, _key, *, timeout):
        """Reproduce the timeout error at 45 seconds and accept the chat budget."""
        observed.append(timeout)
        if timeout == 45:
            raise DatasetError(
                'модель не ответила за 45 с — попробуйте ещё раз '
                'или соберите отчёт мышью: поля слева, секции по центру'
            )
        return '{"final":{"reply":"Готово"}}'

    monkeypatch.setattr(interpret, '_ask', fake_ask)

    assert runner._invoke('prompt', 'model', 'key') == {'final': {'reply': 'Готово'}}
    assert observed == [interpret.CHAT_TIMEOUT]


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


@pytest.mark.xfail(strict=True, reason=(
    'The SQL scope only adds a dataset CTE; parse table references and reject '
    'reads outside the selected dataset before execution.'
))
def test_dataset_sql_rejects_other_source_tables(dataset, sources):
    """A dataset question cannot query another table on the same connection."""
    with pytest.raises(DatasetError):
        readonly.scope_dataset_sql(dataset, 'SELECT * FROM private_table')


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
                   'columnLabels': {'city': 'Город', 'total': 'Выручка'}}},
    ])
    monkeypatch.setattr(interpret, '_openrouter_key', lambda: 'fake')
    monkeypatch.setattr(interpret, '_chat_models', lambda: ('fake-model', None))
    monkeypatch.setattr(runner, '_invoke', lambda *_: next(actions))
    monkeypatch.setattr(runner, 'execute_readonly_sql', lambda _dataset, _sql: (
        ['city', 'total'], [['Москва', 100]], False))

    response = runner.ask_dataset(dataset, 'Выручка по городам', [])

    assert response['rows'] == [['Москва', '100']]
    assert response['columns'] == ['Город', 'Выручка']
    assert 'OVER (PARTITION BY city)' in response['sql']
    assert response['explanation']['calculations'] == ['Оконная сумма выручки по городу']


def test_dataset_agent_keeps_verified_answer_when_streaming(dataset, sources, monkeypatch):
    """Streaming sends the same final answer that the agent returns."""
    actions = iter([
        {'tool': 'execute_sql', 'args': {'sql': 'SELECT city FROM dataset'}},
        {'final': {'answer': 'Найдено 21 город', 'columnLabels': {'city': 'Город'}}},
    ])
    monkeypatch.setattr(interpret, '_openrouter_key', lambda: 'fake')
    monkeypatch.setattr(interpret, '_chat_models', lambda: ('fake-model', None))
    monkeypatch.setattr(runner, '_invoke', lambda *_: next(actions))
    monkeypatch.setattr(runner, 'execute_readonly_sql', lambda *_: (
        ['city'], [[f'Город {index}'] for index in range(21)], False))
    events = []
    answer = runner.ask_dataset(dataset, 'Сколько городов?', [], on_event=events.append)

    assert answer['answer'] == 'Найдено 21 город'
    assert events[-1] == {'type': 'delta', 'text': answer['answer']}


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
    """Initial schema and vocabulary permit one model call for a valid report."""
    class Catalog:
        """Expose one dataset and metric to the report agent."""

        metrics = {'revenue': {'slug': 'revenue', 'dataset_slug': 'sales',
                               'title': 'Выручка'}}
        dimensions = {}

        def __init__(self):
            """Register the test dataset."""
            self.datasets = {'sales': dataset}

        def dataset(self, slug):
            """Resolve the dataset used by preview rendering."""
            return self.datasets[slug]

    prompts = []

    def fake_invoke(prompt, *_args):
        """Capture the prompt and provide a complete report proposal."""
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

    result = runner.chat_report([{'role': 'user', 'text': 'Продажи'}], Catalog())

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

    with pytest.raises(DatasetError, match='агент не завершил'):
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
