"""Проверка самого стенда: метабаза, авторизация, живой роутинг."""


def test_health_отвечает_без_авторизации(client):
    response = client.get('/api/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}


def test_метабаза_поднимает_все_таблицы(metabase):
    rows = metabase._raw.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    names = {r['name'] for r in rows}
    assert {'reports', 'users', 'groups', 'group_members', 'report_access', 'sessions',
            'datasets', 'metrics', 'dimensions', 'dataset_links', 'mail_servers',
            'report_schedules', 'app_meta'} <= names


def test_фикстуры_отчёта_собирают_словарь(report, model, dataset):
    assert report['slug'] == 'sales-report'
    assert dataset['status'] == 'ok'
    assert model['metric'] == 'revenue'
