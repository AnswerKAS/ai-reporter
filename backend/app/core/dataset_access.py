"""Назначения датасетов: администратор либо личное/групповое разрешение."""

from fastapi import HTTPException

from . import database as db


def allowed_slugs(user: dict) -> set[str] | None:
    """Возвращает актуальное объединение назначений; None означает администратора."""
    if user.get('role') == 'admin':
        return None
    with db._conn() as conn:
        rows = conn.execute(
            'SELECT DISTINCT d.slug FROM datasets d JOIN dataset_access da ON da.dataset_slug = d.slug '
            'WHERE da.user_id = %s OR da.group_id IN '
            '(SELECT group_id FROM group_members WHERE user_id = %s)',
            (user['id'], user['id']),
        ).fetchall()
    return {row['slug'] for row in rows}


def require_datasets(user: dict, slugs) -> None:
    """Отклоняет весь запрос до чтения источников при отсутствии назначения."""
    allowed = allowed_slugs(user)
    if allowed is not None and not set(slugs) <= allowed:
        raise HTTPException(403, 'Нет доступа к датасету. Обратитесь к администратору для назначения доступа.')


def definition_datasets(definition, *, index=None) -> set[str]:
    """Разрешает словарь, формулы, SQL JOIN и мосты; учитывает свои поля целиком."""
    from ..reports.archive import DependencyIndex
    raw = definition.model_dump(by_alias=True) if hasattr(definition, 'model_dump') else definition
    raw = dict(raw or {})
    from ..query.builder import split_filter_key
    values = raw.get('filterValues') or raw.get('filter_values') or {}
    raw['filters'] = [*(raw.get('filters') or []),
                      *({'dimension': split_filter_key(key)[0]} for key, value in values.items()
                        if value not in (None, ''))]
    if index is None:
        with db._conn() as conn:
            index = DependencyIndex(conn)
    slugs = index.datasets(raw)
    slugs.update(f.get('datasetSlug', f.get('dataset_slug')) for f in (raw or {}).get('fields', []))
    return slugs - {None, ''}


def require_definition(user: dict, definition) -> None:
    """Проверяет все зависимости перед предпросмотром и сохранением определения."""
    if user.get('role') != 'admin':
        require_datasets(user, definition_datasets(definition))


def can_use_definition(user: dict, definition) -> bool:
    """Проверяет, доступны ли источники для сырых строк опубликованного отчёта."""
    allowed = allowed_slugs(user)
    return allowed is None or definition_datasets(definition) <= allowed


def require_payload(user: dict, payload: dict) -> None:
    """Проверяет выбранные источники и поля до передачи пользовательского ТЗ модели."""
    if user.get('role') == 'admin':
        return
    for key in ('datasets', 'attachedDatasets'):
        if payload.get(key):
            require_datasets(user, payload[key])
    fields, computed = payload.get('fields') or [], payload.get('computed') or []
    require_definition(user, {'fields': fields, 'computed': computed,
                              'sections': [{'metrics': [f['key'] for f in computed]}]})
    if payload.get('definition'):
        require_definition(user, payload['definition'])


def visible_turns(user: dict, turns: list[dict], fallback_slug: str | None = None) -> list[dict]:
    """Скрывает сохранённые ответы отозванных источников без удаления переписки."""
    allowed = allowed_slugs(user)
    if allowed is None:
        return turns
    visible = []
    for turn in turns:
        slugs = turn.get('datasetSlugs') or [turn.get('datasetSlug') or fallback_slug]
        if all(slug in allowed for slug in slugs):
            visible.append(turn)
    return visible


def grants(slug: str) -> dict:
    """Читает личные и групповые назначения без автоматического доступа админа."""
    with db._conn() as conn:
        rows = conn.execute('SELECT user_id, group_id FROM dataset_access WHERE dataset_slug = %s',
                            (slug,)).fetchall()
    return {'userIds': sorted(r['user_id'] for r in rows if r['user_id']),
            'groupIds': sorted(r['group_id'] for r in rows if r['group_id'])}


def set_grants(slug: str, user_ids: list[str], group_ids: list[str]) -> dict:
    """Проверяет все назначения до замены; пустой набор отзывает доступ обычных людей."""
    users, groups = sorted(set(user_ids)), sorted(set(group_ids))
    with db._conn() as conn:
        if conn.execute('SELECT slug FROM datasets WHERE slug = %s', (slug,)).fetchone() is None:
            raise HTTPException(404, 'датасет не найден')
        existing_users = {r['id'] for r in conn.execute('SELECT id FROM users WHERE id = ANY(%s)', (users,)).fetchall()}
        existing_groups = {r['id'] for r in conn.execute('SELECT id FROM groups WHERE id = ANY(%s)', (groups,)).fetchall()}
        if existing_users != set(users) or existing_groups != set(groups):
            raise HTTPException(422, 'Выберите существующих пользователей и группы.')
        conn.execute('DELETE FROM dataset_access WHERE dataset_slug = %s', (slug,))
        for user_id in users:
            conn.execute('INSERT INTO dataset_access (dataset_slug, user_id) VALUES (%s, %s)', (slug, user_id))
        for group_id in groups:
            conn.execute('INSERT INTO dataset_access (dataset_slug, group_id) VALUES (%s, %s)', (slug, group_id))
    return {'userIds': users, 'groupIds': groups}


def require_report_history(user: dict, messages: list[dict]) -> None:
    """Проверяет всю историю одним снимком словаря, не раскрывая отозванные источники."""
    from ..reports.archive import DependencyIndex
    definitions = [(message.get('payload') or {}).get('definition') for message in messages]
    definitions = [definition for definition in definitions if definition]
    if not definitions or user.get('role') == 'admin':
        return
    allowed = allowed_slugs(user)
    with db._conn() as conn:
        index = DependencyIndex(conn)
    if any(not definition_datasets(definition, index=index) <= allowed for definition in definitions):
        raise HTTPException(403, 'В истории есть датасеты, доступ к которым отозван. Начните новый диалог с доступными источниками.')
