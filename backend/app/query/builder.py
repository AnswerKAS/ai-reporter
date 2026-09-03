"""Построитель запросов: секция отчёта → SQL источника.

Весь SQL собирается здесь из выверенных определений семантического слоя.
Пользовательские значения (фильтры) попадают в запрос только параметрами,
поэтому произвольный SQL от пользователя невозможен по построению.
"""

import re
from dataclasses import dataclass, field

from ..datasets import registry as dataset_registry
from ..datasets.base import DatasetError
from ..semantic import registry as semantic
from . import dialects


# Алиасы выдачи не должны совпадать с именами колонок: иначе `sum(revenue)
# AS revenue` затеняет колонку и следующее выражение с `revenue` разбирается
# как агрегат внутри агрегата (ClickHouse code 184).
METRIC_PREFIX = 'm_'
DIM_PREFIX = 'd_'


# Действия, доступные автору отчёта над колонкой датасета. Список закрыт:
# пользователь выбирает из него, а не пишет выражение, поэтому произвольный
# SQL через поле отчёта невозможен.
AGGREGATES = {
    'sum': 'sum({f})',
    'count': 'count({f})',
    'count_distinct': 'count(DISTINCT {f})',
    'avg': 'avg({f})',
    'min': 'min({f})',
    'max': 'max({f})',
}


def metric_alias(slug: str) -> str:
    return METRIC_PREFIX + slug


def dim_alias(slug: str) -> str:
    return DIM_PREFIX + slug


@dataclass
class Query:
    sql: str
    params: dict
    metric_slugs: list[str] = field(default_factory=list)
    dimension_slugs: list[str] = field(default_factory=list)

    @property
    def aliases(self) -> dict[str, str]:
        """SQL-алиас → slug: исполнитель раскладывает строки по slug'ам."""
        out = {dim_alias(s): s for s in self.dimension_slugs}
        out.update({metric_alias(s): s for s in self.metric_slugs})
        return out


class Catalog:
    """Снимок словаря на время сборки отчёта.

    Без него каждая секция заново вычитывала метрики, разрезы, связи и
    датасеты — до двух десятков обращений к пулу на один отчёт.
    """

    def __init__(self) -> None:
        self.metrics = {m['slug']: m for m in semantic.list_metrics()}
        self.dimensions = {d['slug']: d for d in semantic.list_dimensions()}
        self.links = semantic.list_links()
        self.datasets = {d['slug']: d for d in dataset_registry.list_all()}
        self._adapters: dict[str, object] = {}
        # уникальность по ключу связи стоит полного скана таблицы, а на
        # сборку отчёта ответ один — держим его здесь, а не в каждой секции
        self.unique_checks: dict[tuple[str, str], bool] = {}

    def adapter(self, slug: str):
        """Адаптер с живым соединением: один на датасет за всю сборку отчёта."""
        if slug not in self._adapters:
            self._adapters[slug] = dataset_registry.adapter_for(self.dataset(slug), reuse=True)
        return self._adapters[slug]

    def close(self) -> None:
        for adapter in self._adapters.values():
            try:
                adapter.close()
            except Exception:
                pass
        self._adapters.clear()

    def metrics_by_slugs(self, slugs: list[str]) -> dict[str, dict]:
        missing = [s for s in slugs if s not in self.metrics]
        if missing:
            raise DatasetError(f'неизвестные метрики: {", ".join(missing)}')
        return {s: self.metrics[s] for s in slugs}

    def dimensions_by_slugs(self, slugs: list[str]) -> dict[str, dict]:
        missing = [s for s in slugs if s not in self.dimensions]
        if missing:
            raise DatasetError(f'неизвестные разрезы: {", ".join(missing)}')
        return {s: self.dimensions[s] for s in slugs}

    def link_between(self, left: str, right: str) -> dict | None:
        for link in self.links:
            if {link['left_slug'], link['right_slug']} == {left, right}:
                return link
        return None

    def dataset(self, slug: str) -> dict:
        dataset = self.datasets.get(slug)
        if dataset is None:
            raise DatasetError(f'датасет {slug} не найден в реестре')
        return dataset


# Строковый литерал SQL: одинарные кавычки, удвоенная кавычка внутри.
_LITERAL_RE = re.compile(r"'(?:[^']|'')*'")


def _qualify(expression: str, fields: list[str], alias: str) -> str:
    """Дописывает алиас таблицы к именам полей внутри выражения метрики.

    Нужно только при джойнах: без них имена однозначны. Заменяются лишь
    известные поля датасета и только как отдельные слова, уже
    квалифицированные (`t.field`) не трогаются.

    Строковые литералы пропускаются целиком: в выражении вида
    `sum(if(category = 'orders', revenue, 0))` слово orders — значение, а не
    колонка, и превращать его в 't0.orders' значит тихо сломать условие,
    получив 0 вместо суммы.
    """
    def qualify_code(chunk: str) -> str:
        for name in sorted(fields, key=len, reverse=True):
            chunk = re.sub(rf'(?<![\w.]){re.escape(name)}\b', f'{alias}.{name}', chunk)
        return chunk

    out, last = [], 0
    for found in _LITERAL_RE.finditer(expression):
        out.append(qualify_code(expression[last:found.start()]))
        out.append(found.group(0))
        last = found.end()
    out.append(qualify_code(expression[last:]))
    return ''.join(out)


def _dataset_fields(dataset: dict) -> list[str]:
    return [f.get('name') for f in (dataset.get('schema') or []) if f.get('name')]


def _is_unique_on(dataset: dict, field: str, adapter=None) -> bool:
    """Уникален ли датасет по полю связи (проверка по реальным данным).

    Если справа несколько строк на один ключ, каждая строка левой таблицы
    размножится, и суммы её метрик раздуются. Схема этого не показывает —
    спрашиваем сам источник.
    """
    dialect = dialects.for_source(dataset['source'])
    adapter = adapter or dataset_registry.adapter_for(dataset)
    table = adapter.quoted_table(dataset.get('table_name') or '')
    quoted = dialect.quote(field)
    _, rows = adapter.run_query(
        f'SELECT count(*) AS total, count(DISTINCT {quoted}) AS keys FROM {table}'
    )
    if not rows:
        return True
    total, keys = rows[0][0], rows[0][1]
    return int(total) == int(keys)


# Признаки того, что в тексте ошибки — наши внутренности, а не что-то,
# что пользователь может исправить сам.
_SQL_NOISE = re.compile(
    r'\bLINE \d|missing FROM-clause|ILLEGAL_AGGREGATION|syntax error|'
    r'\bSELECT\b|\bFROM\b|\bJOIN\b|\b[tq]\d+\.|\b[md]_\w+',
    re.IGNORECASE,
)
# Пропавшая колонка — не наш дефект, а рассинхрон поля отчёта со схемой
# источника, и починить его может сам автор отчёта. Имя колонки в таком
# сообщении — самое ценное, поэтому оно должно дойти до человека.
_MISSING_COLUMN_RE = re.compile(
    r'column\s+"?([\w.]+)"?\s+does not exist|'
    r'Unknown (?:expression or function )?identifier\s+`?([\w.]+)`?',
    re.IGNORECASE,
)
_UNAVAILABLE = re.compile(
    r'timeout|timed out|connection|could not connect|closed the connection|'
    r'network|refused|unreachable',
    re.IGNORECASE,
)


def explain_source_error(text: str) -> str:
    """Ошибка источника → фраза для того, кто SQL не пишет.

    Пользователь конструктора не писал запрос и не может починить его по
    тексту вроде «missing FROM-clause entry for table t2». Такие ошибки —
    наш дефект, и говорить о них надо так, чтобы человек понял, что делать:
    не подбирать поля наугад, а сообщить о поломке. Подробности остаются
    в логе сервера.
    """
    if _UNAVAILABLE.search(text):
        return 'источник данных сейчас не отвечает — попробуйте ещё раз через минуту'
    missing = _MISSING_COLUMN_RE.search(text)
    if missing:
        column = (missing.group(1) or missing.group(2) or '').split('.')[-1]
        return (f'в источнике больше нет колонки «{column}» — поле отчёта, '
                'которое на неё ссылается, нужно пересоздать или убрать')
    if _SQL_NOISE.search(text):
        return ('не удалось собрать запрос по этому набору полей — это ошибка '
                'конструктора, а не ваша. Уберите последнее добавленное поле, '
                'чтобы продолжить, и сообщите о проблеме')
    return text


def _plan_edges(plan: list[tuple[str, dict | None]]) -> dict[str, list[tuple[str, str]]]:
    """Связи внутри плана: сосед и поле, по которому он подключается."""
    edges: dict[str, list[tuple[str, str]]] = {}
    for _, link in plan:
        if link is None:
            continue
        left, left_field = link['left_slug'], link['left_field']
        right, right_field = link['right_slug'], link['right_field']
        edges.setdefault(left, []).append((right, right_field))
        edges.setdefault(right, []).append((left, left_field))
    return edges


def _reachable(start: set[str], graph: dict) -> set[str]:
    """Датасеты, до которых вообще есть путь по связям."""
    seen = set(start)
    queue = list(start)
    while queue:
        current = queue.pop()
        for other, _ in graph.get(current, ()):
            if other not in seen:
                seen.add(other)
                queue.append(other)
    return seen


def _safe_datasets(holder: str, edges: dict, unique) -> set[str]:
    """Датасеты, присоединяемые к holder без размножения его строк.

    Шаг безопасен, только если ведёт в датасет, уникальный по своему ключу
    связи. Дальше по цепочке идём лишь через безопасные шаги: раздувание
    транзитивно — справочник, уже размноженный продажами, размножит и всё,
    что подключится через него.
    """
    seen = {holder}
    queue = [holder]
    while queue:
        current = queue.pop()
        for other, other_field in edges.get(current, ()):
            if other in seen or not unique(other, other_field):
                continue
            seen.add(other)
            queue.append(other)
    return seen


def _plan_link_graph(plan: list[tuple[str, dict | None]]) -> dict[str, list[tuple[str, dict]]]:
    """Связи внутри плана — с самими связями, а не только с полями.

    Нужен, чтобы путь для подзапроса искался среди датасетов, которые уже
    есть в плане: иначе подзапрос может выбрать мост, которого нет ни в
    self.datasets, ни в self.aliases.
    """
    graph: dict[str, list[tuple[str, dict]]] = {}
    for _, link in plan:
        if link is None:
            continue
        graph.setdefault(link['left_slug'], []).append((link['right_slug'], link))
        graph.setdefault(link['right_slug'], []).append((link['left_slug'], link))
    return graph


def _link_graph(catalog: 'Catalog') -> dict[str, list[tuple[str, dict]]]:
    """Все связи словаря как граф: сосед → связь, по которой он подключается."""
    graph: dict[str, list[tuple[str, dict]]] = {}
    for link in catalog.links:
        graph.setdefault(link['left_slug'], []).append((link['right_slug'], link))
        graph.setdefault(link['right_slug'], []).append((link['left_slug'], link))
    return graph


def _bridge(joined: set[str], target: str, graph: dict) -> list[tuple[str, dict]] | None:
    """Кратчайший путь от уже присоединённых датасетов к target.

    Промежуточные датасеты в секции не участвуют — они нужны только как
    мост. Без этого «план и факт вместе» упирались бы в «нет связи», хотя
    связь есть: обе таблицы висят на справочнике точек.
    """
    previous: dict[str, tuple[str, dict]] = {}
    seen = set(joined)
    queue = list(joined)
    while queue:
        current = queue.pop(0)
        for other, link in graph.get(current, ()):
            if other in seen:
                continue
            seen.add(other)
            previous[other] = (current, link)
            if other == target:
                path: list[tuple[str, dict]] = []
                node = target
                while node in previous:
                    parent, used = previous[node]
                    path.append((node, used))
                    node = parent
                return list(reversed(path))
            queue.append(other)
    return None


def _join_plan(dataset_slugs: list[str], catalog: Catalog) -> list[tuple[str, dict | None]]:
    """Порядок подключения датасетов: базовый, затем связанные с уже взятыми.

    Если прямой связи нет, ищется путь через промежуточные датасеты — они
    добавляются в план молча, потому что своих колонок в отчёт не дают.
    """
    graph = _link_graph(catalog)
    remaining = list(dataset_slugs)
    base = remaining.pop(0)
    plan: list[tuple[str, dict | None]] = [(base, None)]
    joined = {base}
    while remaining:
        # датасет мог уже войти в план как мост — тогда искать путь к нему не нужно
        remaining = [slug for slug in remaining if slug not in joined]
        if not remaining:
            break
        for candidate in list(remaining):
            path = _bridge(joined, candidate, graph)
            if path is None:
                continue
            for slug, link in path:
                if slug in joined:
                    continue
                plan.append((slug, link))
                joined.add(slug)
            remaining.remove(candidate)
            break
        else:
            raise DatasetError(
                f'нет связи между датасетами: {", ".join(sorted(joined))} и '
                f'{", ".join(remaining)} — заведите связь в семантическом слое'
            )
    return plan


class SectionQuery:
    """Собирает запрос одной секции отчёта."""

    def __init__(self, metrics: list[str], by: list[str], *, grain: str | None = None,
                 order_by: str | None = None, order_dir: str = 'desc',
                 limit: int | None = None, filters: dict[str, str] | None = None,
                 catalog: Catalog | None = None,
                 computed: list[dict] | None = None,
                 fields: list[dict] | None = None) -> None:
        if not metrics:
            raise DatasetError('в секции не выбрано ни одной метрики')
        self.catalog = catalog or Catalog()
        # разрезы словаря; поля самого отчёта добавятся ниже
        self.dimension_defs = {s: self.catalog.dimensions[s]
                               for s in by if s in self.catalog.dimensions}
        self.grain = grain
        self.order_by = order_by
        self.order_dir = 'asc' if str(order_dir).lower() == 'asc' else 'desc'
        self.limit = limit
        self.filter_values = filters or {}

        # поля самого отчёта: колонка датасета, взятая автором «под себя».
        # Они дополняют словарь только внутри этой секции.
        self.local_metrics, self.local_dimensions = self._resolve_fields(fields or [])
        if self.local_dimensions:
            self.dimension_defs = {
                s: self.dimension_defs.get(s) or self.local_dimensions.get(s) for s in by
            }

        # вычисляемые поля отчёта: сами в источник не ходят, их выражение
        # собирается из показателей — операнды нужны в запросе,
        # даже если пользователь не положил их в секцию
        self.computed_defs = self._resolve_computed(metrics, computed or [])
        base_slugs = [s for s in metrics if s not in self.computed_defs]
        for field in self.computed_defs.values():
            for side in (field['left'], field['right']):
                if side not in base_slugs:
                    base_slugs.append(side)
        self.base_defs = self._metrics_by_slugs(base_slugs)

        broken = [m['slug'] for m in self.base_defs.values() if m['status'] == 'error']
        if broken:
            raise DatasetError(f'метрики не прошли проверку: {", ".join(broken)}')

        # в выдачу идёт то, что выбрано, и в том порядке, в каком выбрано
        self.metric_defs = {
            slug: (self._computed_meta(slug) if slug in self.computed_defs else self.base_defs[slug])
            for slug in metrics
        }

        unknown_dims = [s for s in by if self.dimension_defs.get(s) is None]
        if unknown_dims:
            raise DatasetError(f'неизвестные разрезы: {", ".join(unknown_dims)}')

        # разрезы, по которым фильтруют: их датасеты тоже нужны в запросе,
        # иначе фильтр молча отбрасывается — карточка KPI осталась бы
        # нефильтрованной рядом с отфильтрованной таблицей
        self.filter_dims = {}
        for filter_slug, value in (filters or {}).items():
            if value in (None, ''):
                continue
            found = (self.catalog.dimensions.get(filter_slug)
                     or self.local_dimensions.get(filter_slug))
            if found is not None:
                self.filter_dims[filter_slug] = found

        # порядок датасетов: сначала те, откуда метрики — они задают базовую таблицу
        base_order: list[str] = []
        for item in list(self.base_defs.values()) + list(self.dimension_defs.values()):
            if item['dataset_slug'] not in base_order:
                base_order.append(item['dataset_slug'])

        # датасет фильтра добавляем, только если до него есть путь по связям:
        # фильтр из вовсе не связанной таблицы к этой секции не относится
        connected = _reachable(set(base_order), _link_graph(self.catalog))
        extra = [dim['dataset_slug'] for dim in self.filter_dims.values()
                 if dim['dataset_slug'] in connected and dim['dataset_slug'] not in base_order]

        self._prepare(base_order + extra)
        if self._drop_unapplicable_filters():
            # снятый фильтр не должен тащить свою таблицу в джойн: иначе она
            # осталась бы там и размножила строки метрик
            keep = [d for d in extra
                    if d in {dim['dataset_slug'] for dim in self.filter_dims.values()}]
            self._prepare(base_order + keep)

        self._check_dimensions()
        # если какой-то держатель метрик размножается другим — считаем каждый
        # датасет отдельно и соединяем уже агрегаты
        self.preaggregate = any(
            other not in self._safe[m]
            for m in self.metric_datasets
            for other in self.metric_datasets
            if other != m
        )

    def _prepare(self, ordered: list[str]) -> None:
        """План подключения и всё, что из него следует."""
        # план может добавить датасеты-мосты: своих колонок они не дают,
        # но нужны как путь между таблицами
        self.plan = _join_plan(ordered, self.catalog) if ordered else []
        self.dataset_slugs = [slug for slug, _ in self.plan] or ordered
        self.datasets = {slug: self.catalog.dataset(slug) for slug in self.dataset_slugs}

        sources = {d['source'] for d in self.datasets.values()}
        if len(sources) > 1:
            raise DatasetError(
                'секция обращается к разным типам источников — кросс-источниковые '
                'запросы пока не поддерживаются'
            )
        self.dialect = dialects.for_source(next(iter(sources)))
        self.aliases = {slug: f't{i}' for i, slug in enumerate(self.dataset_slugs)}
        self.joined = len(self.dataset_slugs) > 1

        # какие датасеты можно присоединить к каждому держателю метрик,
        # не размножив его строки — от этого зависит и допустимость разреза,
        # и способ сборки запроса
        self._edges = _plan_edges(self.plan)
        self.metric_datasets = []
        for item in self.base_defs.values():
            if item['dataset_slug'] not in self.metric_datasets:
                self.metric_datasets.append(item['dataset_slug'])
        self._safe = {m: _safe_datasets(m, self._edges, self._is_unique)
                      for m in self.metric_datasets}

    def _drop_unapplicable_filters(self) -> bool:
        """Снимает фильтры, применимые не ко всем показателям секции.

        Фильтр обязан действовать на всю секцию: применить его к части
        показателей значило бы показать несопоставимые числа рядом. Но и
        ронять отчёт из-за этого нельзя — секция остаётся нефильтрованной,
        и об этом честно написано под ней.
        """
        self.unapplied_filters: list[str] = []
        for slug, dim in list(self.filter_dims.items()):
            target = dim['dataset_slug']
            if target not in self.aliases:
                continue  # датасет фильтра не связан с секцией — фильтр не о ней
            blocked = [holder for holder in self.metric_datasets
                       if target not in self._safe[holder]]
            if not blocked:
                continue
            titles = ', '.join(self.metric_defs[m]['title'] for m in self.metric_defs
                               if self._holder_of(m) in blocked)
            self.unapplied_filters.append(
                f'«{dim["title"]}» — у показателей {titles} нет такого разреза'
            )
            self.filter_dims.pop(slug)
            self.filter_values = {k: v for k, v in self.filter_values.items() if k != slug}
        return bool(self.unapplied_filters)

    def _is_unique(self, slug: str, field: str) -> bool:
        key = (slug, field)
        cache = self.catalog.unique_checks
        if key not in cache:
            cache[key] = _is_unique_on(self.datasets[slug], field, self.catalog.adapter(slug))
        return cache[key]

    def _check_dimensions(self) -> None:
        """Разрез должен быть достижим из каждого держателя метрик безопасно.

        «План по категориям» бессмысленен: категория лежит в продажах, и путь
        к ней размножает строки плана. Такое не спасает никакая предагрегация,
        поэтому отказываем сразу и по существу.
        """
        for dim in self.dimension_defs.values():
            target = dim['dataset_slug']
            for holder in self.metric_datasets:
                if target in self._safe[holder]:
                    continue
                raise DatasetError(
                    f'разрез «{dim["title"]}» нельзя применить к метрикам датасета '
                    f'{holder}: путь к {target} размножает их строки. У {holder} '
                    f'просто нет такого разреза'
                )

    def _resolve_fields(self, fields: list[dict]) -> tuple[dict, dict]:
        """Поля отчёта → описания метрик и разрезов.

        Имя колонки сверяется со схемой датасета, действие — со списком
        AGGREGATES. Определение отчёта может прислать любой авторизованный
        пользователь, поэтому в SQL попадает только то, что нашлось в схеме.
        """
        local_metrics, local_dims = {}, {}
        for item in fields:
            key = item['key']
            if key in self.catalog.metrics or key in self.catalog.dimensions:
                raise DatasetError(
                    f'поле «{item.get("title") or key}» повторяет имя {key} из словаря — '
                    'переименуйте его'
                )
            dataset = self.catalog.dataset(item['dataset_slug'])
            names = _dataset_fields(dataset)
            if item['field'] not in names:
                raise DatasetError(
                    f'в датасете {item["dataset_slug"]} нет колонки {item["field"]}'
                )
            if item.get('role') == 'dimension':
                local_dims[key] = {
                    'slug': key, 'title': item['title'],
                    'dataset_slug': item['dataset_slug'], 'field': item['field'],
                    'type': item.get('type') or 'string',
                }
                continue
            agg = item.get('agg') or 'sum'
            if agg not in AGGREGATES:
                raise DatasetError(f'неизвестное действие над полем: {agg}')
            local_metrics[key] = {
                'slug': key, 'title': item['title'],
                'dataset_slug': item['dataset_slug'],
                'expression': AGGREGATES[agg].format(f=item['field']),
                'format': item.get('format') or 'number',
                'unit': None, 'status': 'ok',
            }
        return local_metrics, local_dims

    def _metrics_by_slugs(self, slugs: list[str]) -> dict:
        """Метрики словаря и поля самого отчёта — в одном пространстве имён."""
        out, missing = {}, []
        for slug in slugs:
            found = self.catalog.metrics.get(slug) or self.local_metrics.get(slug)
            if found is None:
                missing.append(slug)
            else:
                out[slug] = found
        if missing:
            raise DatasetError(f'неизвестные метрики: {", ".join(missing)}')
        return out

    def _resolve_computed(self, metrics: list[str], computed: list[dict]) -> dict:
        """Вычисляемые поля, которые действительно нужны этой секции."""
        by_key = {}
        for field in computed:
            key = field['key']
            if key in self.catalog.metrics or key in self.local_metrics:
                raise DatasetError(
                    f'своё поле «{field.get("title") or key}» повторяет имя показателя '
                    f'{key} — переименуйте его'
                )
            by_key[key] = field
        used = {slug: by_key[slug] for slug in metrics if slug in by_key}
        known = set(self.catalog.metrics) | set(self.local_metrics)
        for field in used.values():
            missing = [s for s in (field['left'], field['right']) if s not in known]
            if missing:
                raise DatasetError(
                    f'своё поле «{field["title"]}» ссылается на неизвестные показатели: '
                    f'{", ".join(missing)}'
                )
        return used

    def _computed_meta(self, key: str) -> dict:
        """Описание вычисляемого поля в виде обычной метрики — для выдачи."""
        field = self.computed_defs[key]
        return {
            'slug': key,
            'title': field['title'],
            'format': field.get('format') or 'number',
            'unit': None,
            'status': 'ok',
            'expression': '',  # собирается в _metric_sql: операнды знают свои таблицы
            'dataset_slug': self.base_defs[field['left']]['dataset_slug'],
        }

    # --- части запроса ---

    def _dimension_sql(self, slug: str) -> str:
        dim = self.dimension_defs[slug]
        alias = self.aliases[dim['dataset_slug']]
        expr = f"{alias}.{self.dialect.quote(dim['field'])}"
        if dim['type'] == 'date' and self.grain:
            expr = self.dialect.date_trunc(expr, self.grain)
        return expr

    def _base_metric_sql(self, slug: str) -> str:
        metric = self.base_defs[slug]
        expression = metric['expression']
        if self.joined:
            dataset = self.datasets[metric['dataset_slug']]
            expression = _qualify(
                expression, _dataset_fields(dataset), self.aliases[metric['dataset_slug']]
            )
        return expression

    def _combine(self, field: dict, left: str, right: str) -> str:
        """Собирает выражение формулы из готовых частей."""
        if field['op'] == '/':
            # деление на ноль даёт NULL, а не падение всего отчёта
            expr = f'({left}) / nullif(({right}), 0)'
        else:
            expr = f'({left}) {field["op"]} ({right})'
        if (field.get('format') or 'number') == 'percent':
            # фронт форматирует percent как проценты, а не как долю: 1.3 → «1,3 %».
            # Формула, помеченная процентом, — доля по построению, поэтому
            # приводим её к тому же виду здесь, а не заставляем считать в уме.
            expr = f'({expr}) * 100'
        return expr

    def _metric_sql(self, slug: str) -> str:
        if slug not in self.computed_defs:
            return self._base_metric_sql(slug)
        field = self.computed_defs[slug]
        return self._combine(field,
                             self._base_metric_sql(field['left']),
                             self._base_metric_sql(field['right']))

    def _operand_datasets(self, slug: str) -> set[str]:
        """Датасеты, из которых формула берёт операнды."""
        field = self.computed_defs[slug]
        return {self.base_defs[field['left']]['dataset_slug'],
                self.base_defs[field['right']]['dataset_slug']}

    def _from_sql(self, slugs: list[str] | None = None) -> str:
        parts = []
        plan = self.plan if slugs is None else _join_plan(slugs, self.catalog)
        for slug, link in plan:
            if slug not in self.datasets:
                raise DatasetError(f'датасет {slug} не входит в план секции')
            dataset = self.datasets[slug]
            table = self.catalog.adapter(slug).quoted_table(dataset.get('table_name') or '')
            alias = self.aliases[slug]
            if link is None:
                parts.append(f'{table} AS {alias}')
                continue
            # связь хранится как left→right, но подключать можем любую сторону
            if slug == link['left_slug']:
                own_field, other, other_field = (
                    link['left_field'], link['right_slug'], link['right_field'])
            else:
                own_field, other, other_field = (
                    link['right_field'], link['left_slug'], link['left_field'])
            kind = 'LEFT JOIN' if link['kind'] == 'left' else 'INNER JOIN'
            parts.append(
                f'{kind} {table} AS {alias} ON {alias}.{self.dialect.quote(own_field)} = '
                f'{self.aliases[other]}.{self.dialect.quote(other_field)}'
            )
        return '\n'.join(parts)

    def _where_sql(self, slugs: set[str] | None = None) -> tuple[str, dict]:
        available = set(self.aliases) if slugs is None else slugs
        clauses, params = [], {}
        for slug, value in self.filter_values.items():
            if value in (None, ''):
                continue
            dim = self.catalog.dimensions.get(slug) or self.local_dimensions.get(slug)
            if dim is None or dim['dataset_slug'] not in available:
                continue  # фильтр не относится к этой части запроса
            alias = self.aliases[dim['dataset_slug']]
            name = f'f_{slug}'
            clauses.append(
                f"{alias}.{self.dialect.quote(dim['field'])} = "
                f'{self.dialect.placeholder(name, dim["type"])}'
            )
            params[name] = float(value) if dim['type'] == 'number' else str(value)
        return ('WHERE ' + ' AND '.join(clauses) if clauses else ''), params

    def _order_limit_sql(self) -> str:
        sql = ''
        order = self.order_by or (next(iter(self.metric_defs)) if self.dimension_defs else None)
        if order in self.metric_defs:
            sql += f'\nORDER BY {self.dialect.quote(metric_alias(order))} {self.order_dir.upper()}'
        elif order in self.dimension_defs:
            sql += f'\nORDER BY {self.dialect.quote(dim_alias(order))} {self.order_dir.upper()}'
        if self.limit:
            sql += f'\nLIMIT {int(self.limit)}'
        return sql

    def _build_single(self) -> Query:
        """Обычный путь: один SELECT по объединённым таблицам."""
        select_parts = [f'{self._dimension_sql(s)} AS {self.dialect.quote(dim_alias(s))}'
                        for s in self.dimension_defs]
        select_parts += [f'{self._metric_sql(s)} AS {self.dialect.quote(metric_alias(s))}'
                         for s in self.metric_defs]
        where_sql, params = self._where_sql()

        sql = f'SELECT {", ".join(select_parts)}\nFROM {self._from_sql()}'
        if where_sql:
            sql += f'\n{where_sql}'
        if self.dimension_defs:
            group = ', '.join(self._dimension_sql(s) for s in self.dimension_defs)
            sql += f'\nGROUP BY {group}'
        sql += self._order_limit_sql()
        return Query(sql=sql, params=params,
                     metric_slugs=list(self.metric_defs),
                     dimension_slugs=list(self.dimension_defs))

    def _subquery_slugs(self, holder: str) -> list[str]:
        """Датасеты, нужные агрегату holder: он сам, разрезы и путь до них.

        Путь ищется по связям основного плана: подзапрос не вправе
        притащить датасет, для которого нет ни алиаса, ни таблицы.
        """
        needed = {holder}
        needed.update(d['dataset_slug'] for d in self.dimension_defs.values())
        needed.update(d['dataset_slug'] for d in self.filter_dims.values()
                      if d['dataset_slug'] in self.aliases)
        graph = _plan_link_graph(self.plan)
        ordered = [holder]
        for target in sorted(needed):
            if target == holder:
                continue
            path = _bridge(set(ordered), target, graph)
            if path is None:
                raise DatasetError(
                    f'не удалось соединить {holder} и {target} внутри секции'
                )
            for slug, _ in path:
                if slug not in ordered:
                    ordered.append(slug)
        return ordered

    def _build_preaggregated(self) -> Query:
        """Каждый держатель метрик считается на своём уровне, соединяются агрегаты.

        Прямой джойн двух таблиц фактов множит строки: план точки, сложенный
        по строкам продаж, вырастает в число этих строк раз. Поэтому сначала
        сворачиваем каждый датасет до разрезов секции, и только потом
        соединяем — суммы остаются своими.

        Формула, операнды которой лежат в разных датасетах («план ÷ факт»),
        внутри подзапроса невыразима: чужая таблица туда не входит. Такие
        считаются снаружи, поверх уже соединённых агрегатов.
        """
        dims = list(self.dimension_defs)

        # что где считать: базовые метрики — в своём подзапросе, формулы —
        # там же, если оба операнда «дома», иначе снаружи
        outer_formulas = [m for m in self.metric_defs
                          if m in self.computed_defs and len(self._operand_datasets(m)) > 1]
        inside: dict[str, list[str]] = {ds: [] for ds in self.metric_datasets}
        for slug in self.metric_defs:
            if slug in outer_formulas:
                continue
            inside[self._holder_of(slug)].append(slug)
        # операнды внешних формул должны попасть в выдачу своих подзапросов,
        # даже если пользователь их сам не выбирал
        operands: dict[str, list[str]] = {ds: [] for ds in self.metric_datasets}
        for slug in outer_formulas:
            field = self.computed_defs[slug]
            for side in (field['left'], field['right']):
                holder = self.base_defs[side]['dataset_slug']
                if side not in inside[holder] and side not in operands[holder]:
                    operands[holder].append(side)

        params: dict = {}
        parts = []
        for index, holder in enumerate(self.metric_datasets):
            emitted = inside[holder] + operands[holder]
            if not emitted:
                continue
            slugs = self._subquery_slugs(holder)
            select = [f'{self._dimension_sql(d)} AS {self.dialect.quote(dim_alias(d))}'
                      for d in dims]
            select += [f'{self._metric_sql(m)} AS {self.dialect.quote(metric_alias(m))}'
                       for m in emitted]
            where_sql, sub_params = self._where_sql(set(slugs))
            params.update(sub_params)
            sub = f'SELECT {", ".join(select)}\nFROM {self._from_sql(slugs)}'
            if where_sql:
                sub += f'\n{where_sql}'
            if dims:
                sub += '\nGROUP BY ' + ', '.join(self._dimension_sql(d) for d in dims)
            parts.append({'alias': f'q{index}', 'sql': sub, 'holder': holder,
                          'emitted': emitted})

        at = {m: part['alias'] for part in parts for m in part['emitted']}

        select_out = []
        for d in dims:
            column = self.dialect.quote(dim_alias(d))
            sources = ', '.join(f'{part["alias"]}.{column}' for part in parts)
            select_out.append(f'coalesce({sources}) AS {column}')
        for slug in self.metric_defs:
            column = self.dialect.quote(metric_alias(slug))
            if slug in outer_formulas:
                field = self.computed_defs[slug]
                left = f'{at[field["left"]]}.{self.dialect.quote(metric_alias(field["left"]))}'
                right = f'{at[field["right"]]}.{self.dialect.quote(metric_alias(field["right"]))}'
                select_out.append(f'{self._combine(field, left, right)} AS {column}')
            else:
                select_out.append(f'{at[slug]}.{column}')

        head = parts[0]
        sql = f'SELECT {", ".join(select_out)}\nFROM (\n{head["sql"]}\n) AS {head["alias"]}'
        for part in parts[1:]:
            if dims:
                on = ' AND '.join(
                    f'{head["alias"]}.{self.dialect.quote(dim_alias(d))} = '
                    f'{part["alias"]}.{self.dialect.quote(dim_alias(d))}' for d in dims
                )
                sql += f'\nFULL OUTER JOIN (\n{part["sql"]}\n) AS {part["alias"]} ON {on}'
            else:
                sql += f'\nCROSS JOIN (\n{part["sql"]}\n) AS {part["alias"]}'
        sql += self._order_limit_sql()
        sql += self.dialect.join_settings()
        return Query(sql=sql, params=params,
                     metric_slugs=list(self.metric_defs),
                     dimension_slugs=dims)

    def _holder_of(self, slug: str) -> str:
        """Датасет, которому принадлежит поле выдачи (для формулы — её операнд)."""
        if slug in self.computed_defs:
            return self.base_defs[self.computed_defs[slug]['left']]['dataset_slug']
        return self.base_defs[slug]['dataset_slug']

    def build(self) -> Query:
        if self.preaggregate:
            return self._build_preaggregated()
        return self._build_single()

    def run(self) -> tuple[list[str], list[list]]:
        query = self.build()
        try:
            return self.catalog.adapter(self.dataset_slugs[0]).run_query(query.sql, query.params)
        except DatasetError as exc:
            # отказы, которые мы формулируем сами (раздувание, отсутствие связи),
            # сюда не попадают — они поднимаются раньше, до обращения к источнику
            print(f'[query] запрос не выполнен: {exc}\n{query.sql}')
            raise DatasetError(explain_source_error(str(exc))) from exc


def distinct_values(dimension_slug: str, limit: int = 200,
                    catalog: Catalog | None = None,
                    dim: dict | None = None) -> list[str]:
    """Значения разреза для select-фильтра.

    dim передают для разрезов самого отчёта: их в общем словаре нет.
    """
    catalog = catalog or Catalog()
    dim = dim or catalog.dimensions.get(dimension_slug)
    if dim is None:
        raise DatasetError(f'разрез {dimension_slug} не найден')
    dataset = catalog.dataset(dim['dataset_slug'])
    dialect = dialects.for_source(dataset['source'])
    adapter = catalog.adapter(dim['dataset_slug'])
    table = adapter.quoted_table(dataset.get('table_name') or '')
    field_sql = dialect.quote(dim['field'])
    _, rows = adapter.run_query(
        f'SELECT DISTINCT {field_sql} AS value FROM {table} '
        f'WHERE {field_sql} IS NOT NULL ORDER BY value LIMIT {int(limit)}'
    )
    return [str(r[0]) for r in rows if r and r[0] is not None]
