"""Agent tool loops and read-only SQL behavior."""

import pytest

from app.agent import readonly, runner
from app.datasets.base import DatasetError
from app.query import interpret
from app.reports import executor
from app.schemas.definition import SectionDefinition


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


def test_dataset_agent_executes_window_query(dataset, sources, monkeypatch):
    """The agent uses a SQL tool before answering from observed rows."""
    actions = iter([
        {'tool': 'describe_schema'},
        {'tool': 'execute_sql', 'args': {'sql':
            'SELECT city, SUM(revenue) OVER (PARTITION BY city) AS total FROM dataset'}},
        {'final': {'answer': 'Выручка по городу: 100',
                   'calculations': ['Оконная сумма выручки по городу'],
                   'groupBy': ['city'], 'filters': [], 'orderBy': None,
                   'scope': 'Все строки датасета'}},
    ])
    monkeypatch.setattr(interpret, '_openrouter_key', lambda: 'fake')
    monkeypatch.setattr(interpret, '_chat_models', lambda: ('fake-model', None))
    monkeypatch.setattr(runner, '_invoke', lambda *_: next(actions))
    monkeypatch.setattr(runner, 'execute_readonly_sql', lambda _dataset, _sql: (
        ['city', 'total'], [['Москва', 100]], False))

    response = runner.ask_dataset(dataset, 'Выручка по городам', [], reveal_sql=True)

    assert response['rows'] == [['Москва', '100']]
    assert 'OVER (PARTITION BY city)' in response['sql']
    assert response['explanation']['calculations'] == ['Оконная сумма выручки по городу']


def test_report_agent_validates_sql_section(dataset, monkeypatch):
    """A report SQL block is checked and queried before it is proposed."""
    actions = iter([
        {'tool': 'get_datasets'},
        {'tool': 'validate_definition', 'args': {'definition': {'sections': [{
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
    monkeypatch.setattr(runner, 'execute_readonly_sql', lambda *_args, **_kwargs: (
        ['city', 'rank'], [['Москва', 1]], False))

    response = runner.chat_report([{'role': 'user', 'text': 'Рейтинг городов'}], Catalog(dataset))

    assert response['source'] == 'agent'
    assert response['definition']['sections'][0]['datasetSlug'] == 'sales'
    assert 'ROW_NUMBER()' in response['definition']['sections'][0]['sql']


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
