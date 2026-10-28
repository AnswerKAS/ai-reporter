"""Обзор используемых меток без раскрытия чужих отчётов обычному читателю."""

from . import database as db


def catalog(user: dict) -> list[dict]:
    """Сводит темы отчётов и разрешения; полные счётчики доступны только админу."""
    if user.get('role') != 'admin':
        condition, args = db._access_sql(user)
        with db._conn() as conn:
            rows = conn.execute(
                'SELECT DISTINCT rt.tag FROM report_tags rt JOIN reports r ON r.slug = rt.report_slug '
                'WHERE ' + condition, tuple(args),
            ).fetchall()
        _, allowed = db.access_attributes(user['id'])
        return [{'tag': tag} for tag in sorted({r['tag'] for r in rows} | allowed)]
    counts: dict[str, dict] = {}
    with db._conn() as conn:
        for table, key in (('report_tags', 'reportCount'), ('user_access_tags', 'userCount'),
                           ('group_access_tags', 'groupCount')):
            for row in conn.execute(f'SELECT tag, COUNT(*) AS n FROM {table} GROUP BY tag').fetchall():
                item = counts.setdefault(row['tag'], {'tag': row['tag'], 'reportCount': 0,
                                                      'userCount': 0, 'groupCount': 0})
                item[key] = row['n']
    return [counts[tag] for tag in sorted(counts)]


def usage(tag: str) -> dict:
    """Возвращает ограниченные примеры назначений выбранной метки для администратора."""
    with db._conn() as conn:
        reports = conn.execute(
            'SELECT r.slug, r.title, r.archived_at FROM reports r JOIN report_tags rt '
            'ON rt.report_slug = r.slug WHERE rt.tag = %s ORDER BY r.search_text LIMIT 100', (tag,),
        ).fetchall()
        users = conn.execute(
            'SELECT u.id, u.username FROM users u JOIN user_access_tags ut '
            'ON ut.user_id = u.id WHERE ut.tag = %s ORDER BY u.username LIMIT 100', (tag,),
        ).fetchall()
        groups = conn.execute(
            'SELECT g.id, g.name FROM groups g JOIN group_access_tags gt '
            'ON gt.group_id = g.id WHERE gt.tag = %s ORDER BY g.name LIMIT 100', (tag,),
        ).fetchall()
    return {'reports': [{'slug': r['slug'], 'title': r['title'], 'archivedAt': r['archived_at']} for r in reports],
            'users': [dict(row) for row in users], 'groups': [dict(row) for row in groups]}


def effective_tags(kind: str, identifier: str) -> dict:
    """Отделяет личные метки от полученных через группы, не меняя назначения."""
    direct = db.get_access_tags(kind, identifier)
    sources: dict[str, dict] = {}
    if kind == 'user':
        with db._conn() as conn:
            rows = conn.execute(
                'SELECT g.id, g.name, gt.tag FROM groups g '
                'JOIN group_members gm ON gm.group_id = g.id '
                'JOIN group_access_tags gt ON gt.group_id = g.id '
                'WHERE gm.user_id = %s ORDER BY g.name, gt.tag', (identifier,),
            ).fetchall()
        for row in rows:
            sources.setdefault(row['id'], {'groupId': row['id'], 'groupName': row['name'],
                                            'tags': []})['tags'].append(row['tag'])
    inherited = {tag for source in sources.values() for tag in source['tags']}
    return {'tags': direct, 'inheritedTags': sorted(inherited),
            'effectiveTags': sorted(set(direct) | inherited), 'inheritedFrom': list(sources.values())}
