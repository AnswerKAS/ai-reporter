"""Обзор меток, наследование и подсказки с учётом прав на отчёты."""

from app.core import database as db


def test_admin_sees_tags_from_reports_people_and_groups(client, report, admin_headers, plain_user):
    """Каталог включает даже метки, ещё не назначенные отчётам."""
    db.set_report_tags(report['slug'], ['sales'])
    db.set_access_tags('user', plain_user['id'], ['personal'])
    db.create_group(id='g', name='Группа')
    db.set_access_tags('group', 'g', ['group-only'])
    rows = {item['tag']: item for item in client.get('/api/admin/tags', headers=admin_headers).json()['tags']}
    assert rows['sales']['reportCount'] == 1
    assert rows['personal']['userCount'] == 1
    assert rows['group-only']['groupCount'] == 1
    usage = client.get('/api/admin/tags/usage?tag=sales', headers=admin_headers).json()
    assert usage['reports'][0]['slug'] == report['slug']


def test_tag_suggestions_do_not_reveal_private_labels(client, report, user_headers, plain_user):
    """Подсказки содержат свои разрешения и доступные темы, но не чужие метки."""
    db.set_report_tags(report['slug'], ['private-label'])
    db.set_access_tags('user', plain_user['id'], ['personal'])
    assert client.get('/api/report-tags', headers=user_headers).json()['tags'] == ['personal']
    assert client.get('/api/admin/tags', headers=user_headers).status_code == 403
    assert client.get('/api/admin/tags/usage?tag=private-label', headers=user_headers).status_code == 403
    db.grant_access(report['slug'], user_id=plain_user['id'])
    assert 'private-label' in client.get('/api/report-tags', headers=user_headers).json()['tags']


def test_effective_tags_explain_group_inheritance(client, plain_user, admin_headers):
    """Личные и унаследованные метки различимы и показывают группу-источник."""
    db.create_group(id='g', name='Финансы')
    db.add_group_member('g', plain_user['id'])
    db.set_access_tags('group', 'g', ['finance'])
    db.set_access_tags('user', plain_user['id'], ['direct'])
    response = client.get(f'/api/admin/access-tags/user/{plain_user["id"]}?effective=true', headers=admin_headers)
    data = response.json()
    assert data['tags'] == ['direct']
    assert data['inheritedTags'] == ['finance']
    assert data['effectiveTags'] == ['direct', 'finance']
    assert data['inheritedFrom'][0]['groupName'] == 'Финансы'
