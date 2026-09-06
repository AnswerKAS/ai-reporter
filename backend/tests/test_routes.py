"""Полнота покрытия: у каждого метода API есть свои тесты.

Список ниже — опись всех эндпоинтов и файлов, где они проверяются. Если в
приложении появится новый метод или исчезнет старый, тест упадёт: значит,
опись и тесты пора обновить вместе с кодом.
"""

import pytest

from app.main import app

# (метод, путь) → файл с тестами этого эндпоинта
COVERED = {
    ('GET', '/api/health'): 'test_smoke.py',

    ('POST', '/api/auth/login'): 'test_api_auth.py',
    ('POST', '/api/auth/logout'): 'test_api_auth.py',
    ('GET', '/api/auth/me'): 'test_api_auth.py',
    ('POST', '/api/auth/password'): 'test_api_auth.py',

    ('GET', '/api/admin/users'): 'test_api_admin.py',
    ('POST', '/api/admin/users'): 'test_api_admin.py',
    ('DELETE', '/api/admin/users/{user_id}'): 'test_api_admin.py',
    ('POST', '/api/admin/users/{user_id}/password'): 'test_api_admin.py',
    ('GET', '/api/admin/groups'): 'test_api_admin.py',
    ('POST', '/api/admin/groups'): 'test_api_admin.py',
    ('DELETE', '/api/admin/groups/{group_id}'): 'test_api_admin.py',
    ('POST', '/api/admin/groups/{group_id}/members'): 'test_api_admin.py',
    ('DELETE', '/api/admin/groups/{group_id}/members/{user_id}'): 'test_api_admin.py',
    ('GET', '/api/admin/access/{slug}'): 'test_api_admin.py',
    ('POST', '/api/admin/access'): 'test_api_admin.py',
    ('DELETE', '/api/admin/access'): 'test_api_admin.py',

    ('GET', '/api/datasets'): 'test_api_datasets.py',
    ('GET', '/api/datasets/{slug}'): 'test_api_datasets.py',
    ('POST', '/api/datasets'): 'test_api_datasets.py',
    ('PATCH', '/api/datasets/{slug}'): 'test_api_datasets.py',
    ('DELETE', '/api/datasets/{slug}'): 'test_api_datasets.py',
    ('POST', '/api/datasets/{slug}/refresh'): 'test_api_datasets.py',
    ('GET', '/api/datasets/{slug}/suggest'): 'test_api_datasets.py',
    ('POST', '/api/datasets/{slug}/semantic'): 'test_api_datasets.py',
    ('POST', '/api/datasets/{slug}/upload'): 'test_api_datasets.py',

    ('GET', '/api/metrics'): 'test_api_semantic.py',
    ('POST', '/api/metrics'): 'test_api_semantic.py',
    ('PATCH', '/api/metrics/{slug}'): 'test_api_semantic.py',
    ('POST', '/api/metrics/{slug}/test'): 'test_api_semantic.py',
    ('DELETE', '/api/metrics/{slug}'): 'test_api_semantic.py',
    ('GET', '/api/dimensions'): 'test_api_semantic.py',
    ('POST', '/api/dimensions'): 'test_api_semantic.py',
    ('PATCH', '/api/dimensions/{slug}'): 'test_api_semantic.py',
    ('DELETE', '/api/dimensions/{slug}'): 'test_api_semantic.py',
    ('GET', '/api/dataset-links'): 'test_api_semantic.py',
    ('POST', '/api/dataset-links'): 'test_api_semantic.py',
    ('DELETE', '/api/dataset-links/{link_id}'): 'test_api_semantic.py',

    ('GET', '/api/reports'): 'test_api_reports.py',
    ('POST', '/api/reports/parse'): 'test_api_reports.py',
    ('POST', '/api/reports/preview'): 'test_api_reports.py',
    ('POST', '/api/reports/builder'): 'test_api_reports.py',
    ('GET', '/api/reports/{slug}'): 'test_api_reports.py',
    ('PATCH', '/api/reports/{slug}'): 'test_api_reports.py',
    ('DELETE', '/api/reports/{slug}'): 'test_api_reports.py',
    ('GET', '/api/reports/{slug}/definition'): 'test_api_reports.py',
    ('PUT', '/api/reports/{slug}/definition'): 'test_api_reports.py',
    ('POST', '/api/reports/{slug}/filters'): 'test_api_reports.py',
    ('POST', '/api/reports/{slug}/drilldown'): 'test_api_reports.py',
    ('POST', '/api/reports/{slug}/drilldown.xlsx'): 'test_api_reports.py',

    ('GET', '/api/admin/mail-servers'): 'test_api_mail.py',
    ('POST', '/api/admin/mail-servers'): 'test_api_mail.py',
    ('PATCH', '/api/admin/mail-servers/{server_id}'): 'test_api_mail.py',
    ('POST', '/api/admin/mail-servers/{server_id}/test'): 'test_api_mail.py',
    ('DELETE', '/api/admin/mail-servers/{server_id}'): 'test_api_mail.py',
    ('GET', '/api/schedules'): 'test_api_mail.py',
    ('GET', '/api/reports/{slug}/schedules'): 'test_api_mail.py',
    ('POST', '/api/reports/{slug}/schedules'): 'test_api_mail.py',
    ('PATCH', '/api/reports/{slug}/schedules/{schedule_id}'): 'test_api_mail.py',
    ('POST', '/api/reports/{slug}/schedules/{schedule_id}/send'): 'test_api_mail.py',
    ('DELETE', '/api/reports/{slug}/schedules/{schedule_id}'): 'test_api_mail.py',
}


def api_routes() -> set[tuple[str, str]]:
    """Все методы приложения: роутеры подключены вложенно, поэтому обход рекурсивный."""
    found: set[tuple[str, str]] = set()

    def walk(obj) -> None:
        for route in getattr(obj, 'routes', None) or []:
            inner = getattr(route, 'original_router', None)
            if inner is not None:
                walk(inner)
                continue
            path = getattr(route, 'path', '')
            if not path.startswith('/api'):
                continue
            for method in getattr(route, 'methods', None) or ():
                if method not in ('HEAD', 'OPTIONS'):
                    found.add((method, path))

    walk(obj=app)
    return found


def test_у_каждого_метода_api_есть_тесты():
    assert api_routes() - set(COVERED) == set(), 'появился метод без тестов'


def test_в_описи_нет_исчезнувших_методов():
    assert set(COVERED) - api_routes() == set(), 'метод убрали, а опись осталась'


@pytest.mark.parametrize('route,module', sorted(COVERED.items()))
def test_файл_с_тестами_метода_существует(route, module):
    from pathlib import Path

    assert (Path(__file__).parent / module).is_file()
