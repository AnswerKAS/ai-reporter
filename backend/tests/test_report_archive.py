"""Архив отчётов при удалении источников."""

from app.core import database as db
from app.datasets import registry as datasets


def test_deleting_dataset_archives_dependent_report(client, admin_headers, report):
    """Удаление источника сразу убирает отчёт из активного каталога."""
    response = client.delete('/api/datasets/sales', headers=admin_headers)
    assert response.status_code == 200
    assert db.get_report(report['slug']).get('archived_at')
    assert client.get('/api/reports', headers=admin_headers).json()['total'] == 0
    archived = client.get('/api/reports?archived=true', headers=admin_headers).json()
    assert [row['slug'] for row in archived['reports']] == [report['slug']]
    assert db.get_definition(report['slug'])['sections']


def create_report(slug, definition, **kwargs):
    """Создаёт отчёт с произвольным определением для проверки зависимостей."""
    return db.create_report(id=slug, slug=slug, title=slug, description=None,
                            definition=definition, **kwargs)


def recreate_dataset(original):
    """Возвращает источник с прежним slug без восстановления отчётов."""
    return datasets.create(**{key: original[key] for key in (
        'slug', 'title', 'description', 'source', 'dsn', 'table_name', 'schema', 'status', 'error')})


def test_impact_requires_admin_and_lists_only_affected_active_reports(
        client, admin_headers, user_headers, report):
    """Предупреждение называет связанные отчёты и доступно только администратору."""
    create_report('independent', {'sections': []})
    assert client.get('/api/datasets/sales/deletion-impact', headers=user_headers).status_code == 403
    result = client.get('/api/datasets/sales/deletion-impact', headers=admin_headers)
    assert result.status_code == 200
    assert result.json() == {'total': 1, 'reports': [{'slug': report['slug'], 'title': 'Продажи'}]}
    client.delete('/api/datasets/sales', headers=admin_headers)
    assert not db.get_report('independent')['archived_at']
    assert client.get('/api/datasets/missing/deletion-impact', headers=admin_headers).status_code == 404


def test_archived_read_and_drilldown_do_not_execute_sources(client, admin_headers, report, monkeypatch):
    """Архив открывается с причиной; чтение и детализация не обращаются к источнику."""
    from app.reports import executor, drilldown

    datasets.delete('sales')

    def unexpected_execution(*args, **kwargs):
        """Любое исполнение архивного отчёта нарушает проверяемый контракт."""
        raise AssertionError('archived report executed')

    monkeypatch.setattr(executor, 'execute', unexpected_execution)
    monkeypatch.setattr(drilldown, 'fetch', unexpected_execution)
    data = client.get('/api/reports/sales-report', headers=admin_headers).json()['report']
    assert data['archivedAt'] and 'Продажи' in data['archiveReason']
    assert data['sections'] == []
    assert client.post('/api/reports/sales-report/drilldown', headers=admin_headers, json={}).status_code == 409
    assert client.post('/api/reports/sales-report/drilldown.xlsx', headers=admin_headers, json={}).status_code == 409
    assert client.post('/api/reports/sales-report/filters', headers=admin_headers,
                       json={'values': {}}).status_code == 409
    assert client.get('/api/reports/sales-report/definition', headers=admin_headers).status_code == 200


def test_archive_keeps_status_access_tags_and_favorites(client, admin_headers, plain_user, user_headers, report):
    """Архив отделён от статуса исполнения, сохраняет права, темы и закрепление."""
    db.grant_access(report_slug=report['slug'], user_id=plain_user['id'])
    db.add_favorite(plain_user['id'], report['slug'])
    db.set_report_tags(report['slug'], ['Продажи'])
    db.update_status(report['slug'], status='error', error='previous error')
    datasets.delete('sales')
    assert db.get_report(report['slug'])['status'] == 'error'
    assert db.get_report(report['slug'])['error'] == 'previous error'
    assert client.get('/api/reports?favorite=true', headers=user_headers).json()['total'] == 0
    assert client.get('/api/reports/facets', headers=user_headers).json()['total'] == 0
    facets = client.get('/api/reports/facets?archived=true', headers=user_headers).json()
    assert facets['total'] == 1 and facets['favorites'] == 1
    data = client.get('/api/reports?archived=true&tag=Продажи&limit=1', headers=user_headers).json()
    assert data['total'] == 1 and data['reports'][0]['favorite']
    assert client.get('/api/reports/sales-report', headers=user_headers).status_code == 200
    assert client.post('/api/reports/sales-report/restore', headers=user_headers).status_code == 403


def test_archive_catalog_honors_access_search_and_pagination(client, admin_headers, user_headers, report):
    """Архивный поиск остаётся постраничным и не раскрывает чужие отчёты."""
    create_report('second', db.get_definition(report['slug']))
    datasets.delete('sales')
    assert client.get('/api/reports?archived=true', headers=user_headers).json()['total'] == 0
    assert client.get('/api/reports/facets?archived=true', headers=user_headers).json()['total'] == 0
    page = client.get('/api/reports?archived=true&limit=1&offset=1', headers=admin_headers).json()
    assert page['total'] == 2 and len(page['reports']) == 1
    assert client.get('/api/reports?archived=true&q=second', headers=admin_headers).json()['total'] == 1


def test_restore_requires_valid_sources_and_explicit_action(client, admin_headers, report, dataset):
    """Возвращение slug не оживляет отчёт; явное восстановление проверяет исполнение."""
    datasets.delete('sales')
    db.update_status(report['slug'], status='error', error='old source failure')
    before = db.get_report(report['slug'])['archived_at']
    result = client.post('/api/reports/sales-report/restore', headers=admin_headers)
    assert result.status_code == 422
    assert db.get_report(report['slug'])['archived_at'] == before
    recreate_dataset(dataset)
    assert db.get_report(report['slug'])['archived_at'] == before
    result = client.post('/api/reports/sales-report/restore', headers=admin_headers)
    assert result.status_code == 200
    assert result.json()['report']['archivedAt'] is None
    assert result.json()['report']['status'] == 'ready'
    assert not result.json()['report']['error']
    assert client.get('/api/reports', headers=admin_headers).json()['total'] == 1
    assert client.post('/api/reports/missing/restore', headers=admin_headers).status_code == 404


def test_owner_can_repair_definition_and_explicitly_restore(client, dataset_user_headers, plain_user, report):
    """Автор сохраняет исправленное определение в архиве и восстанавливает его отдельно."""
    create_report('own', db.get_definition(report['slug']), created_by=plain_user['id'])
    from app.reports.archive import archive_reports
    with db._conn() as conn:
        archive_reports(conn, [{'slug': 'own'}], 'Удалён прежний источник')
    result = client.put('/api/reports/own/definition', headers=dataset_user_headers,
                        json=db.get_definition(report['slug']))
    assert result.status_code == 200
    assert result.json()['report']['archivedAt']
    assert client.post('/api/reports/own/restore', headers=dataset_user_headers).status_code == 200


def test_backfill_archives_missing_sources_once_without_unarchiving(report):
    """Миграция ловит прежнее удаление и не повторяет архивирование при следующем старте."""
    from app.reports.archive import backfill_missing_datasets
    with db._conn() as conn:
        conn.execute('DELETE FROM datasets WHERE slug = %s', ('sales',))
    backfill_missing_datasets()
    original = db.get_report(report['slug'])
    assert original['archived_at'] and 'sales' in original['archive_reason']
    create_report('later', db.get_definition(report['slug']))
    backfill_missing_datasets()
    assert db.get_report(report['slug'])['archived_at'] == original['archived_at']
    assert db.get_report('later')['archived_at'] is None


def test_dependency_index_includes_formulas_filters_sql_and_only_used_fields(model, dataset):
    """Индекс учитывает реальные ссылки и не архивирует отчёт из-за неиспользованного поля."""
    from app.reports.archive import DependencyIndex
    with db._conn() as conn:
        index = DependencyIndex(conn)
    own = {'key': 'amount', 'datasetSlug': 'own-source'}
    other = {'key': 'unused', 'dataset_slug': 'unused-source'}
    definition = {
        'sections': [{'metrics': ['ratio'], 'by': ['city']}],
        'fields': [own, other],
        'computed': [{'key': 'ratio', 'left': 'amount', 'right': 'revenue'}],
        'filters': [{'dimension': 'day'}],
    }
    assert index.datasets(definition) == {'sales', 'own-source'}
    assert index.datasets({'sections': [{'sql': 'select 1', 'datasetSlug': 'main',
                                         'joinDatasetSlugs': ['joined']} ]}) == {'main', 'joined'}
    assert index.datasets({'sections': [{'sql': 'select 1', 'dataset_slug': 'legacy',
                                         'join_dataset_slugs': ['other']} ]}) == {'legacy', 'other'}


def test_deleting_sql_join_source_archives_whole_report(dataset):
    """Удаление дополнительного SQL-датасета архивирует отчёт целиком."""
    report = create_report('sql', {'sections': [{'type': 'table', 'sql': 'select * from dataset',
        'datasetSlug': 'other', 'joinDatasetSlugs': ['sales']}]})
    datasets.delete('sales')
    assert db.get_report(report['slug'])['archived_at']


def test_deleting_bridge_dataset_archives_joined_report(model, dataset):
    """Источник-мост без собственных полей тоже является зависимостью отчёта."""
    from app.semantic import registry as semantic
    bridge = {**dataset, 'slug': 'bridge'}
    recreate_dataset(bridge)
    recreate_dataset({**dataset, 'slug': 'target'})
    semantic.create_dimension(slug='target-city', title='Город', description=None,
                              dataset_slug='target', field='city', type='string')
    semantic.create_link(title=None, left_slug='sales', right_slug='bridge',
                         left_field='city', right_field='city')
    semantic.create_link(title=None, left_slug='bridge', right_slug='target',
                         left_field='city', right_field='city')
    create_report('joined', {'sections': [{'metrics': ['revenue'], 'by': ['target-city']}]})
    datasets.delete('bridge')
    assert db.get_report('joined')['archived_at']


def test_failed_dataset_delete_rolls_back_archival(report, metabase, monkeypatch):
    """Ошибка удаления откатывает архивирование в той же транзакции."""
    from contextlib import contextmanager
    import sqlite3
    import pytest

    @contextmanager
    def transactional_connection():
        """Даёт SQLite настоящую транзакцию вместо автокоммита общей фикстуры."""
        metabase.execute('BEGIN')
        try:
            yield metabase
            metabase.execute('COMMIT')
        except Exception:
            metabase.execute('ROLLBACK')
            raise

    metabase.execute("CREATE TRIGGER block_delete BEFORE DELETE ON datasets "
                     "BEGIN SELECT RAISE(ABORT, 'delete blocked'); END")
    monkeypatch.setattr(datasets, '_conn', transactional_connection)
    with pytest.raises(sqlite3.IntegrityError, match='delete blocked'):
        datasets.delete('sales')
    assert db.get_report(report['slug'])['archived_at'] is None
    assert datasets.get('sales')


def test_archived_report_is_not_rendered_for_mail(report):
    """Рассылка архивного отчёта останавливается до исполнения источника."""
    import pytest
    from app.mail.sender import MailError, report_spec
    datasets.delete('sales')
    with pytest.raises(MailError, match='архиве'):
        report_spec(report['slug'])


def test_archived_schedules_are_skipped_and_resume_after_restore(report, dataset):
    """Планировщик пропускает архив без потери настроек рассылки."""
    from datetime import datetime
    from app.mail import registry as mail

    schedule = mail.create_schedule(report_slug=report['slug'], author_id='u',
                                    recipients=['a@example.com'], next_run_at='2026-01-01T09:00:00')
    datasets.delete('sales')
    assert mail.due_schedules(datetime(2026, 10, 28)) == []
    assert mail.get_schedule(schedule['id'])['enabled']
    recreate_dataset(dataset)
    assert mail.due_schedules(datetime(2026, 10, 28)) == []
    with db._conn() as conn:
        conn.execute('UPDATE reports SET archived_at = NULL WHERE slug = %s', (report['slug'],))
    assert [item['id'] for item in mail.due_schedules(datetime(2026, 10, 28))] == [schedule['id']]


def test_backfill_archives_report_with_deleted_dictionary_metrics(metabase):
    """Потерянная метрика архивирует отчёт даже после первой миграции датасетов."""
    from app.reports.archive import backfill_missing_datasets
    db._meta_set(metabase, 'report_archive_backfilled', '1')
    create_report('missing-manager-stats', {'sections': [{'type': 'kpi', 'metrics': [
        'manager_stats_revenue_sum', 'manager_stats_tasks_done_sum']} ]})
    backfill_missing_datasets()
    report = db.get_report('missing-manager-stats')
    assert report['archived_at']
    assert 'manager_stats_revenue_sum' in report['archive_reason']
    assert 'manager_stats_tasks_done_sum' in report['archive_reason']


def test_deleting_dictionary_metric_archives_dependent_reports(client, admin_headers, report):
    """Удаление словарного показателя сразу убирает зависимый отчёт из каталога."""
    create_report('unrelated', {'sections': []})
    response = client.delete('/api/metrics/revenue', headers=admin_headers)
    assert response.status_code == 200
    archived = db.get_report(report['slug'])
    assert archived['archived_at'] and 'revenue' in archived['archive_reason']
    assert not db.get_report('unrelated')['archived_at']
    assert client.get('/api/reports', headers=admin_headers).json()['total'] == 1


def test_deleting_formula_operand_archives_dependent_report(model):
    """Словарный операнд используется даже когда в секции выбрана только формула."""
    from app.semantic import registry as semantic
    create_report('formula', {'sections': [{'type': 'kpi', 'metrics': ['ratio']}],
                             'computed': [{'key': 'ratio', 'left': 'revenue', 'right': 'revenue'}]})
    semantic.delete_metric('revenue')
    assert db.get_report('formula')['archived_at']


def test_deleting_filter_dimension_archives_report(client, admin_headers, report):
    """Удаление разреза фильтра архивирует отчёт без группировки по этому разрезу."""
    create_report('filtered', {'sections': [{'type': 'kpi', 'metrics': ['revenue']}],
                              'filters': [{'dimension': 'day', 'kind': 'daterange'}]})
    response = client.delete('/api/dimensions/day', headers=admin_headers)
    assert response.status_code == 200
    assert db.get_report('filtered')['archived_at']
    assert not db.get_report(report['slug'])['archived_at']


def test_opening_report_with_missing_metrics_archives_before_execution(client, admin_headers, metabase, monkeypatch):
    """Старый отчёт с удалёнными метриками открывает причину архива без SQL."""
    from app.reports import executor
    create_report('missing-manager-stats', {'sections': [{'type': 'kpi', 'metrics': [
        'manager_stats_revenue_sum', 'manager_stats_tasks_done_sum']}]})

    def unexpected_execution(*args, **kwargs):
        """Источник не должен исполняться при потерянных ссылках словаря."""
        raise AssertionError('broken report executed')

    monkeypatch.setattr(executor, 'execute', unexpected_execution)
    response = client.get('/api/reports/missing-manager-stats', headers=admin_headers)
    assert response.status_code == 200
    report = response.json()['report']
    assert report['archivedAt'] and report['sections'] == []
    assert 'manager_stats_revenue_sum' in report['archiveReason']
    assert 'manager_stats_tasks_done_sum' in report['archiveReason']
    assert client.get('/api/reports', headers=admin_headers).json()['total'] == 0


def test_missing_fields_check_accepts_report_local_fields_and_formulas(dataset):
    """Поля и формулы отчёта не требуют записей общего словаря."""
    from app.reports.archive import backfill_missing_datasets
    create_report('local', {
        'sections': [{'type': 'table', 'metrics': ['ratio'], 'by': ['local-city']}],
        'fields': [{'key': 'local-revenue', 'datasetSlug': 'sales', 'role': 'metric'},
                   {'key': 'local-city', 'datasetSlug': 'sales', 'role': 'dimension'}],
        'computed': [{'key': 'ratio', 'left': 'local-revenue', 'right': 'local-revenue'},
                     {'key': 'unused-formula', 'left': 'missing', 'right': 'missing'}],
        'filters': [{'dimension': 'local-city'}],
    })
    backfill_missing_datasets()
    assert db.get_report('local')['archived_at'] is None


def test_missing_fields_check_distinguishes_metric_and_dimension_keys(model):
    """Разрез с таким же ключом не заменяет отсутствующий показатель и наоборот."""
    from app.reports.archive import DependencyIndex
    with db._conn() as conn:
        index = DependencyIndex(conn)
    reason = index.missing_reason({'sections': [{'metrics': ['city'], 'by': ['revenue']}]}, {'sales'})
    assert 'Отсутствуют показатели: city' in reason
    assert 'Отсутствуют разрезы: revenue' in reason


def test_sql_section_ignores_unused_semantic_keys(dataset):
    """SQL-блок не требует метрики из оставшихся полей визуальной секции."""
    from app.reports.archive import DependencyIndex
    with db._conn() as conn:
        index = DependencyIndex(conn)
    assert index.missing_reason({'sections': [{'sql': 'select 1', 'datasetSlug': 'sales',
                                               'metrics': ['unused-metric'], 'by': ['unused-dimension']}]},
                                {'sales'}) is None


def test_transient_query_failure_does_not_archive_report(client, admin_headers, report, monkeypatch):
    """Временная ошибка источника не превращает исправное определение в архивное."""
    from app.reports import executor
    from app.datasets.base import DatasetError

    def fail_query(*args, **kwargs):
        """Имитирует временную ошибку выполнения существующего источника."""
        raise DatasetError('Источник временно недоступен')

    monkeypatch.setattr(executor, 'execute', fail_query)
    response = client.get('/api/reports/sales-report', headers=admin_headers)
    assert response.status_code == 502
    assert db.get_report(report['slug'])['archived_at'] is None


def test_restore_rejects_missing_filter_dimension(client, admin_headers, model):
    """Фильтр нельзя потерять молча при восстановлении отчёта из архива."""
    from app.semantic import registry as semantic
    create_report('filtered', {'sections': [{'type': 'kpi', 'metrics': ['revenue']}],
                              'filters': [{'dimension': 'day', 'kind': 'daterange'}]})
    semantic.delete_dimension('day')
    response = client.post('/api/reports/filtered/restore', headers=admin_headers)
    assert response.status_code == 422
    assert 'day' in response.json()['detail']
    assert db.get_report('filtered')['archived_at']
