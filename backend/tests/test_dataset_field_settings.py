"""Dataset field settings survive schema refresh and guide report creation."""

from app.datasets import registry
from app.query import builder, interpret


def test_admin_can_save_settings_and_employee_cannot(client, dataset, admin_headers,
                                                     user_headers):
    """Only an administrator can save schema field settings."""
    path = '/api/datasets/sales/fields'
    payload = {'fields': {'revenue': {
        'title': 'Оборот', 'role': 'metric', 'agg': 'avg', 'format': 'money',
    }}}

    assert client.put(path, json=payload, headers=user_headers).status_code == 403
    assert client.put(path, json=payload).status_code == 401
    response = client.put(path, json=payload, headers=admin_headers)

    assert response.status_code == 200, response.text
    assert response.json()['dataset']['fieldSettings']['revenue'] == {
        'title': 'Оборот', 'role': 'metric', 'agg': 'avg', 'format': 'money',
    }
    visible = client.get('/api/datasets', headers=user_headers).json()['datasets'][0]
    assert visible['fieldSettings']['revenue']['title'] == 'Оборот'


def test_settings_survive_schema_refresh_and_missing_column(client, dataset, sources,
                                                            admin_headers):
    """Refreshing the source schema preserves settings for temporarily absent fields."""
    path = '/api/datasets/sales/fields'
    payload = {'fields': {'revenue': {
        'title': 'Оборот', 'role': 'metric', 'agg': 'avg', 'format': 'money',
    }}}
    assert client.put(path, json=payload, headers=admin_headers).status_code == 200
    sources.specs['sales'].fields = [('city', 'String')]

    refreshed = client.post('/api/datasets/sales/refresh',
                            headers=admin_headers).json()['dataset']

    assert [field['name'] for field in refreshed['fields']] == ['city']
    assert refreshed['fieldSettings']['revenue']['title'] == 'Оборот'
    assert 'revenue' not in {field['name'] for field in refreshed['fields']}

    saved_visible_fields = client.put(path, json={'fields': {}},
                                      headers=admin_headers).json()['dataset']
    assert saved_visible_fields['fieldSettings']['revenue']['title'] == 'Оборот'

    sources.specs['sales'].fields.append(('revenue', 'Float64'))
    restored = client.post('/api/datasets/sales/refresh',
                           headers=admin_headers).json()['dataset']
    assert restored['fieldSettings']['revenue']['agg'] == 'avg'


def test_invalid_settings_are_rejected_without_partial_save(client, dataset,
                                                            admin_headers):
    """Unknown columns and incompatible aggregations leave settings untouched."""
    path = '/api/datasets/sales/fields'
    bad_field = {'fields': {'missing': {
        'title': 'Нет', 'role': 'metric', 'agg': 'sum', 'format': 'number',
    }}}
    bad_aggregate = {'fields': {'city': {
        'title': 'Город', 'role': 'metric', 'agg': 'sum', 'format': 'number',
    }}}

    assert client.put(path, json=bad_field, headers=admin_headers).status_code == 422
    assert client.put(path, json=bad_aggregate, headers=admin_headers).status_code == 422
    assert registry.get('sales')['field_settings'] == {}


def test_configured_field_guides_recommendation_and_parser(client, dataset,
                                                           admin_headers, monkeypatch):
    """Configured title and average aggregation reach definitions made without a model."""
    payload = {'fields': {
        'revenue': {'title': 'Оборот', 'role': 'metric', 'agg': 'avg',
                    'format': 'money'},
        'city': {'title': 'Населённый пункт', 'role': 'dimension',
                 'format': 'number'},
        'id': {'title': 'Идентификатор', 'role': 'ignore', 'format': 'number'},
    }}
    assert client.put('/api/datasets/sales/fields', json=payload,
                      headers=admin_headers).status_code == 200
    monkeypatch.setattr(interpret, '_openrouter_key', lambda: None)

    catalog = builder.Catalog()
    try:
        variants = interpret.recommend(catalog, datasets=['sales'])['recommendations']
        chosen = next(item for item in variants if item['title'].startswith('Оборот'))
        fields = chosen['definition']['fields']
        metric = next(item for item in fields if item['role'] == 'metric')
        assert metric['agg'] == 'avg' and metric['format'] == 'money'
        assert all(item['field'] != 'id' for item in fields)

        parsed = interpret.parse('оборот по населённым пунктам', catalog,
                                 datasets=['sales'])['definition']
        assert {item['field'] for item in parsed['fields']} == {'revenue', 'city'}
        assert next(item for item in parsed['fields'] if item['role'] == 'metric')['agg'] == 'avg'
    finally:
        catalog.close()


def test_configured_column_coexists_with_legacy_shared_metric(client, model,
                                                              admin_headers):
    """A configured column is available beside existing shared metrics."""
    payload = {'fields': {'revenue': {
        'title': 'Средний оборот', 'role': 'metric', 'agg': 'avg',
        'format': 'money',
    }}}
    response = client.put('/api/datasets/sales/fields', json=payload,
                          headers=admin_headers)
    assert response.status_code == 200, response.text

    catalog = builder.Catalog()
    try:
        metrics, _ = interpret.vocabulary_of(catalog, datasets=['sales'])
        assert any(item['title'] == 'Средний оборот' for item in metrics.values())
        assert 'revenue' in metrics
        variants = interpret.recommend(catalog, datasets=['sales'])['recommendations']
        assert any(item['title'].startswith('Средний оборот') for item in variants)
    finally:
        catalog.close()


def test_ignored_column_is_absent_from_schema_candidates(client, dataset,
                                                         admin_headers):
    """Ignoring a column removes it from new schema based choices."""
    payload = {'fields': {'revenue': {
        'title': 'Выручка', 'role': 'ignore', 'format': 'number',
    }}}
    assert client.put('/api/datasets/sales/fields', json=payload,
                      headers=admin_headers).status_code == 200

    catalog = builder.Catalog()
    try:
        metrics, dimensions = interpret.vocabulary_of(catalog, datasets=['sales'])
        assert all(item.get('_report_field', {}).get('field') != 'revenue'
                   for item in [*metrics.values(), *dimensions.values()])
    finally:
        catalog.close()
