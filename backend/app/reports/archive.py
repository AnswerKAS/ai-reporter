"""Архивирование отчётов по зависимостям без обращения к источникам данных."""

import json

from ..core import database as db
from ..datasets.base import DatasetError
from ..query.builder import _join_plan


class DependencyIndex:
    """Снимок держателей полей и связей на одну операцию с каталогом."""

    def __init__(self, conn):
        """Читает словарь и связи один раз в транзакции вызывающего."""
        self.metrics = {r['slug']: r['dataset_slug'] for r in
                        conn.execute('SELECT slug, dataset_slug FROM metrics').fetchall()}
        self.dimensions = {r['slug']: r['dataset_slug'] for r in
                           conn.execute('SELECT slug, dataset_slug FROM dimensions').fetchall()}
        self.links = [dict(r) for r in conn.execute('SELECT * FROM dataset_links ORDER BY created_at').fetchall()]

    def datasets(self, definition: dict) -> set[str]:
        """Находит использованные поля, формулы, фильтры, SQL и мосты связей."""
        own = {f['key']: f.get('datasetSlug', f.get('dataset_slug'))
               for f in definition.get('fields', [])}
        computed = {f['key']: f for f in definition.get('computed', [])}
        result = set()

        def holders(key: str, seen: frozenset = frozenset()) -> list[str]:
            """Разворачивает формулу, защищаясь от циклов старых определений."""
            if key in seen:
                return []
            if key in computed:
                field = computed[key]
                return holders(field['left'], seen | {key}) + holders(field['right'], seen | {key})
            slug = own.get(key) or self.metrics.get(key) or self.dimensions.get(key)
            return [slug] if slug else []

        filters = [slug for f in definition.get('filters', []) for slug in holders(f['dimension'])]
        result.update(filters)
        for section in definition.get('sections', []):
            if section.get('sql'):
                slug = section.get('datasetSlug', section.get('dataset_slug'))
                if slug:
                    result.add(slug)
                result.update(section.get('joinDatasetSlugs', section.get('join_dataset_slugs', [])))
                continue
            keys = [*section.get('metrics', []), *section.get('by', [])]
            order = list(dict.fromkeys(slug for key in keys for slug in holders(key)))
            result.update(order)
            if order:
                try:
                    result.update(slug for slug, _ in _join_plan(order, self))
                except DatasetError:
                    pass  # Прямые зависимости сохраняются и у уже сломанного плана.
                for slug in filters:
                    try:
                        result.update(item for item, _ in _join_plan([*order, slug], self))
                    except DatasetError:
                        pass  # Фильтр из несвязанного источника не добавляет мосты.
        return result


def dependent_reports(conn, slug: str) -> list[dict]:
    """Возвращает активные отчёты, использующие датасет, в стабильном порядке."""
    index = DependencyIndex(conn)
    rows = conn.execute(
        'SELECT slug, title, definition FROM reports WHERE archived_at IS NULL ORDER BY slug'
    ).fetchall()
    return [dict(row) for row in rows
            if slug in index.datasets(json.loads(row['definition'] or '{}'))]


def archive_reports(conn, reports: list[dict], reason: str) -> None:
    """Помечает отчёты в транзакции удаления, сохраняя статус и определение."""
    if reports:
        conn.execute(
            'UPDATE reports SET archived_at = %s, archive_reason = %s, updated_at = %s '
            'WHERE slug = ANY(%s) AND archived_at IS NULL',
            (db.utcnow(), reason, db.utcnow(), [r['slug'] for r in reports]),
        )


def backfill_missing_datasets() -> None:
    """Один раз архивирует старые отчёты после инициализации каталога датасетов."""
    with db._conn() as conn:
        if db._meta_get(conn, 'report_archive_backfilled'):
            return
        index = DependencyIndex(conn)
        existing = {r['slug'] for r in conn.execute('SELECT slug FROM datasets').fetchall()}
        rows = conn.execute('SELECT slug, definition FROM reports WHERE archived_at IS NULL').fetchall()
        for row in rows:
            missing = index.datasets(json.loads(row['definition'] or '{}')) - existing
            if missing:
                archive_reports(conn, [dict(row)], 'Отсутствуют датасеты: ' + ', '.join(sorted(missing)))
        db._meta_set(conn, 'report_archive_backfilled', '1')
