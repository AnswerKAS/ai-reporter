"""ABAC: авторство, назначения и метки дают одинаковый доступ в API и каталоге."""

from app.core import database as db, report_access


def test_автор_видит_отчёт_без_назначения(metabase, plain_user):
    report = db.create_report(id='i1', slug='owned', title='Мой', description=None,
                              definition={}, created_by=plain_user['id'])
    assert report_access.can(plain_user, report, 'view')
    assert report_access.can(plain_user, report, 'tags')
    assert db.accessible_slugs(plain_user) == {'owned'}


def test_метка_группы_и_отзыв(metabase, plain_user):
    report = db.create_report(id='i1', slug='tagged', title='Общий', description=None,
                              definition={})
    db.set_report_tags('tagged', ['finance'])
    db.create_group(id='g1', name='Финансы')
    db.add_group_member('g1', plain_user['id'])
    db.set_access_tags('group', 'g1', ['finance'])
    assert report_access.can(plain_user, report, 'view')
    assert not report_access.can(plain_user, report, 'tags')
    assert db.accessible_slugs(plain_user) == {'tagged'}
    page, total = db.search_reports(plain_user, limit=20, offset=0)
    assert total == 1 and [item['slug'] for item in page] == ['tagged']
    assert db.report_facets(plain_user)['total'] == 1
    db.set_access_tags('group', 'g1', [])
    assert not report_access.can(plain_user, report, 'view')
    assert db.accessible_slugs(plain_user) == set()
    assert db.search_reports(plain_user, limit=20, offset=0)[1] == 0


def test_админ_назначает_метки(client, admin_headers, plain_user, user_headers):
    path = f'/api/admin/access-tags/user/{plain_user["id"]}'
    assert client.put(path, headers=admin_headers, json={'tags': ['finance']}).json() == {'tags': ['finance']}
    assert client.get(path, headers=admin_headers).json() == {'tags': ['finance']}
    assert client.get(path, headers=user_headers).status_code == 403
    assert client.put(path, headers=user_headers, json={'tags': ['x']}).status_code == 403


def test_читатель_не_меняет_метки_отчёта(client, report, plain_user, user_headers):
    db.grant_access(report['slug'], user_id=plain_user['id'])
    response = client.patch(f'/api/reports/{report["slug"]}', headers=user_headers,
                            json={'tags': ['finance']})
    assert response.status_code == 403


def test_объяснение_доступа(client, report, admin_headers, plain_user):
    db.set_report_tags(report['slug'], ['finance'])
    db.set_access_tags('user', plain_user['id'], ['finance'])
    response = client.get(f'/api/admin/access/{report["slug"]}/effective', headers=admin_headers)
    assert response.status_code == 200
    person = next(u for u in response.json()['users'] if u['userId'] == plain_user['id'])
    assert person['reasons'] == ['метка']
    listing = client.get(f'/api/admin/users/{plain_user["id"]}/accessible-reports', headers=admin_headers)
    assert listing.status_code == 200
    assert listing.json()['reports'][0]['reasons'] == ['метка']
