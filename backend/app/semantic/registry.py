"""Реестр семантического слоя: метрики, разрезы, связи датасетов.

Метрика — именованный агрегат над полями одного датасета («Выручка» =
`sum(revenue)`). Определение пишется и выверяется один раз, дальше все отчёты
ссылаются на него по slug'у — поэтому «выручка» в системе означает ровно
одно и то же.

Разрез — именованное поле для группировки («Город» = `region`).
Связь — условие джойна между двумя датасетами одного источника.

Выражения метрик пишет администратор (как и имена таблиц датасетов) — это
граница доверия. Пользователь SQL не вводит нигде.
"""

import uuid

from ..core.database import _conn, utcnow
from ..datasets import registry as dataset_registry
from ..datasets.base import DatasetError, sanitize_error
from ..query import dialects

METRIC_FORMATS = ('number', 'money', 'percent', 'string', 'date')
DIMENSION_TYPES = ('string', 'date', 'number')
LINK_KINDS = ('inner', 'left')


def new_id() -> str:
    return uuid.uuid4().hex


# --- метрики ---------------------------------------------------------------

def list_metrics() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute('SELECT * FROM metrics ORDER BY slug').fetchall()
    return [dict(r) for r in rows]


def get_metric(slug: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute('SELECT * FROM metrics WHERE slug = %s', (slug,)).fetchone()
    return dict(row) if row is not None else None


def create_metric(*, slug: str, title: str, description: str | None, dataset_slug: str,
                  expression: str, format: str = 'number', unit: str | None = None) -> dict:
    now = utcnow()
    with _conn() as conn:
        conn.execute(
            'INSERT INTO metrics (slug, title, description, dataset_slug, expression, format, unit, '
            'status, error, created_at, updated_at) '
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'new', NULL, %s, %s)",
            (slug, title, description, dataset_slug, expression, format, unit, now, now),
        )
    return get_metric(slug)


def update_metric(slug: str, **fields) -> dict | None:
    allowed = ('title', 'description', 'expression', 'format', 'unit', 'status', 'error')
    sets, values = ['updated_at = %s'], [utcnow()]
    for column in allowed:
        if fields.get(column) is not None:
            sets.append(f'{column} = %s')
            values.append(fields[column])
    if fields.get('clear_error'):
        sets.append('error = NULL')
    with _conn() as conn:
        conn.execute(f'UPDATE metrics SET {", ".join(sets)} WHERE slug = %s', (*values, slug))
    return get_metric(slug)


def delete_metric(slug: str) -> None:
    with _conn() as conn:
        conn.execute('DELETE FROM metrics WHERE slug = %s', (slug,))


# --- разрезы ---------------------------------------------------------------

def list_dimensions() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute('SELECT * FROM dimensions ORDER BY slug').fetchall()
    return [dict(r) for r in rows]


def get_dimension(slug: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute('SELECT * FROM dimensions WHERE slug = %s', (slug,)).fetchone()
    return dict(row) if row is not None else None


def create_dimension(*, slug: str, title: str, description: str | None, dataset_slug: str,
                     field: str, type: str = 'string') -> dict:
    now = utcnow()
    with _conn() as conn:
        conn.execute(
            'INSERT INTO dimensions (slug, title, description, dataset_slug, field, type, '
            'created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)',
            (slug, title, description, dataset_slug, field, type, now, now),
        )
    return get_dimension(slug)


def update_dimension(slug: str, **fields) -> dict | None:
    allowed = ('title', 'description', 'field', 'type')
    sets, values = ['updated_at = %s'], [utcnow()]
    for column in allowed:
        if fields.get(column) is not None:
            sets.append(f'{column} = %s')
            values.append(fields[column])
    with _conn() as conn:
        conn.execute(f'UPDATE dimensions SET {", ".join(sets)} WHERE slug = %s', (*values, slug))
    return get_dimension(slug)


def delete_dimension(slug: str) -> None:
    with _conn() as conn:
        conn.execute('DELETE FROM dimensions WHERE slug = %s', (slug,))


# --- связи датасетов --------------------------------------------------------

def list_links() -> list[dict]:
    with _conn() as conn:
        rows = conn.execute('SELECT * FROM dataset_links ORDER BY created_at').fetchall()
    return [dict(r) for r in rows]


def get_link(link_id: str) -> dict | None:
    with _conn() as conn:
        row = conn.execute('SELECT * FROM dataset_links WHERE id = %s', (link_id,)).fetchone()
    return dict(row) if row is not None else None


def create_link(*, title: str | None, left_slug: str, right_slug: str,
                left_field: str, right_field: str, kind: str = 'inner') -> dict:
    link_id = new_id()
    with _conn() as conn:
        conn.execute(
            'INSERT INTO dataset_links (id, title, left_slug, right_slug, left_field, right_field, '
            'kind, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)',
            (link_id, title, left_slug, right_slug, left_field, right_field, kind, utcnow()),
        )
    return get_link(link_id)


def delete_link(link_id: str) -> None:
    with _conn() as conn:
        conn.execute('DELETE FROM dataset_links WHERE id = %s', (link_id,))


# --- проверка определений ----------------------------------------------------

def validate_metric(slug: str) -> dict:
    """Прогоняет выражение метрики по источнику и обновляет статус.

    Битое выражение обязано быть видно сразу, а не всплыть в отчёте: метрика
    получает статус error, и построитель запросов её не пропустит.
    """
    return validate_metrics([slug])[0]


def validate_metrics(slugs: list[str]) -> list[dict]:
    """Проверяет выражения метрик, открывая по одному соединению на датасет.

    Метрики одного датасета сначала проверяются одним запросом: при заведении
    словаря по датасету их сразу больше десятка, а подключение к ClickHouse
    стоит на порядок дороже самой проверки. Если пачка не прошла, выражения
    перепроверяются по одному на том же соединении — иначе одна опечатка
    пометила бы ошибкой все метрики датасета, не назвав виноватую.
    """
    metrics = []
    for slug in slugs:
        metric = get_metric(slug)
        if metric is None:
            raise DatasetError(f'метрика {slug} не найдена')
        metrics.append(metric)

    by_dataset: dict[str, list[dict]] = {}
    for metric in metrics:
        by_dataset.setdefault(metric['dataset_slug'], []).append(metric)

    results: dict[str, dict] = {}
    for dataset_slug, group in by_dataset.items():
        dataset = dataset_registry.get(dataset_slug)
        if dataset is None:
            for metric in group:
                results[metric['slug']] = update_metric(
                    metric['slug'], status='error',
                    error=f'датасет {dataset_slug} не найден') or metric
            continue
        results.update(_validate_group(dataset, group))
    return [results[m['slug']] for m in metrics]


def _validate_group(dataset: dict, group: list[dict]) -> dict[str, dict]:
    """Проверяет метрики одного датасета на одном соединении."""
    adapter = None
    try:
        adapter = dataset_registry.adapter_for(dataset, reuse=True)
        source = adapter.source_sql('t0')
        try:
            tail = ' ' + dialects.for_source(dataset['source']).limit_offset(1)
        except DatasetError:
            # источник без диалекта (CSV): до запроса дело всё равно не дойдёт,
            # и метрика должна получить свою прежнюю ошибку, а не «нужен движок»
            tail = ' LIMIT 1'
        if len(group) > 1:
            select = ', '.join(f'{m["expression"]} AS a{i}' for i, m in enumerate(group))
            try:
                adapter.run_query(f'SELECT {select} FROM {source}{tail}')
                return {m['slug']: (update_metric(m['slug'], status='ok', clear_error=True) or m)
                        for m in group}
            except Exception:
                pass  # виноватую назовём поимённо ниже
        out = {}
        for metric in group:
            try:
                adapter.run_query(
                    f'SELECT {metric["expression"]} AS value FROM {source}{tail}')
                out[metric['slug']] = update_metric(
                    metric['slug'], status='ok', clear_error=True) or metric
            except Exception as exc:  # драйвер может бросить своё
                out[metric['slug']] = update_metric(
                    metric['slug'], status='error', error=sanitize_error(str(exc))) or metric
        return out
    except DatasetError as exc:
        # источник недоступен целиком — ошибка одна на всю группу
        return {m['slug']: (update_metric(m['slug'], status='error',
                                          error=sanitize_error(str(exc))) or m)
                for m in group}
    finally:
        if adapter is not None:
            try:
                adapter.close()
            except Exception:
                pass


def validate_link(left_slug: str, right_slug: str) -> None:
    """Связь возможна только внутри одного источника.

    Джойн спускается в SQL источника; свести таблицы из разных СУБД можно
    только локальным движком — до его появления отклоняем явно, а не молча
    отдаём неверные числа.
    """
    left = dataset_registry.get(left_slug)
    right = dataset_registry.get(right_slug)
    if left is None or right is None:
        raise DatasetError('оба датасета связи должны существовать в реестре')
    if left['source'] != right['source']:
        raise DatasetError(
            f"связь между разными типами источников ({left['source']} и {right['source']}) "
            'пока не поддерживается — нужен локальный движок'
        )
    if left['source'] == 'csv':
        raise DatasetError('связи для CSV-датасетов пока не поддерживаются')
    try:
        if dataset_registry.resolve_dataset_dsn(left) != dataset_registry.resolve_dataset_dsn(right):
            raise DatasetError(
                'датасеты связи живут на разных серверах — джойн не спускается в SQL'
            )
    except DatasetError:
        raise
    except Exception as exc:
        raise DatasetError(f'не удалось сверить источники связи: {sanitize_error(str(exc))}') from exc


# --- выборки для построителя запросов ---------------------------------------

def metrics_by_slugs(slugs: list[str]) -> dict[str, dict]:
    known = {m['slug']: m for m in list_metrics()}
    missing = [s for s in slugs if s not in known]
    if missing:
        raise DatasetError(f'неизвестные метрики: {", ".join(missing)}')
    return {s: known[s] for s in slugs}


def dimensions_by_slugs(slugs: list[str]) -> dict[str, dict]:
    known = {d['slug']: d for d in list_dimensions()}
    missing = [s for s in slugs if s not in known]
    if missing:
        raise DatasetError(f'неизвестные разрезы: {", ".join(missing)}')
    return {s: known[s] for s in slugs}


def link_between(left_slug: str, right_slug: str) -> dict | None:
    """Связь между двумя датасетами в любом направлении."""
    for link in list_links():
        pair = {link['left_slug'], link['right_slug']}
        if pair == {left_slug, right_slug}:
            return link
    return None
