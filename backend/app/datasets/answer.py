"""Вопрос к одному датасету: модель предлагает план, SQL строит только сервер."""

import json
import re
import csv
from collections import defaultdict

from ..query import dialects, interpret
from .base import DatasetError, sanitize_error
from . import registry

MAX_ROWS = 100
MAX_HISTORY = 8
OPS = {'eq': '=', 'ne': '<>', 'gt': '>', 'gte': '>=', 'lt': '<', 'lte': '<='}
AGGS = {'count': 'COUNT', 'sum': 'SUM', 'avg': 'AVG', 'min': 'MIN', 'max': 'MAX'}
FILTER_LABELS = {'eq': 'равно', 'ne': 'не равно', 'gt': 'больше',
                 'gte': 'не меньше', 'lt': 'меньше', 'lte': 'не больше',
                 'contains': 'содержит'}


def _json(raw: str) -> dict:
    found = re.search(r'\{.*\}', raw, re.DOTALL)
    if not found:
        raise DatasetError('модель не смогла составить запрос по датасету')
    try:
        data = json.loads(found.group())
    except ValueError as exc:
        raise DatasetError('модель вернула некорректный план запроса') from exc
    if not isinstance(data, dict):
        raise DatasetError('модель вернула некорректный план запроса')
    return data


def propose(dataset: dict, question: str, history: list[dict]) -> dict:
    key = interpret._openrouter_key()
    if not key:
        raise DatasetError('модель вопросов не настроена: нужен OPENROUTER_API_KEY')
    fields = [{'name': f['name'], 'type': f['type'], 'comment': f.get('comment') or ''}
              for f in dataset.get('schema') or []]
    context = [{'question': str(h.get('question') or '')[:500],
                'plan': h.get('plan') if isinstance(h.get('plan'), dict) else None}
               for h in history[-MAX_HISTORY:]]
    prompt = (
        'Составь план чтения ОДНОГО датасета по вопросу. Верни только JSON без SQL. '
        'Формат: {"select":[{"field":"имя или *", "agg":"count|sum|avg|min|max или пусто"}], '
        '"groupBy":["имя"], "filters":[{"field":"имя","op":"eq|ne|gt|gte|lt|lte|contains",'
        '"value":"значение"}], "orderBy":{"field":"имя","direction":"asc|desc"}, "limit":100}. '
        'Названия полей выбирай только из схемы. Для уточнения используй предыдущий план. '
        'Никаких функций, выражений, JOIN, имён других таблиц и SQL-текста. '
        f'Датасет: {dataset.get("title")}. Описание: {dataset.get("description") or ""}. '
        f'Поля: {json.dumps(fields, ensure_ascii=False)}. '
        f'История: {json.dumps(context, ensure_ascii=False)}. '
        f'Новый вопрос: {question[:1000]}'
    )
    models = interpret._chat_models()
    for model in models:
        if not model:
            continue
        try:
            return _json(interpret._ask(prompt, model, key, timeout=45))
        except DatasetError:
            continue
        except Exception:
            continue
    raise DatasetError('модель вопросов сейчас недоступна')


def compile_plan(dataset: dict, plan: dict) -> tuple[str, dict, dict]:
    """Белый список операций и полей, строгая привязка значений параметрами."""
    if dataset['source'] == 'csv':
        raise DatasetError('вопросы по CSV пока не поддерживаются')
    columns = {f['name']: f for f in dataset.get('schema') or []}
    select = plan.get('select')
    groups = plan.get('groupBy') or []
    filters = plan.get('filters') or []
    if not isinstance(select, list) or not 1 <= len(select) <= 10 or not isinstance(groups, list) or len(groups) > 5 or any(not isinstance(g, str) for g in groups) or not isinstance(filters, list) or len(filters) > 10:
        raise DatasetError('план вопроса превышает допустимые пределы')
    dialect = dialects.for_source(dataset['source'])
    def field(name: str) -> str:
        if name not in columns:
            raise DatasetError(f'неизвестное поле датасета: {name}')
        return f'd.{dialect.quote(name)}'
    def field_type(name: str) -> str:
        raw = str(columns[name].get('type') or '').lower()
        if any(token in raw for token in ('int', 'float', 'decimal', 'numeric', 'number')):
            return 'number'
        if 'date' in raw or 'time' in raw:
            return 'date'
        return 'string'
    parts, aliases = [], set()
    has_aggregate = any(isinstance(item, dict) and item.get('agg') for item in select)
    for index, item in enumerate(select):
        if not isinstance(item, dict):
            raise DatasetError('некорректное поле выборки')
        name, agg = item.get('field'), item.get('agg') or ''
        if name == '*' and agg != 'count':
            raise DatasetError('поле * разрешено только для подсчёта строк')
        if agg and agg not in AGGS:
            raise DatasetError('неизвестная агрегатная операция')
        if has_aggregate and not agg and name not in groups:
            raise DatasetError('поле без агрегации должно входить в группировку')
        expr = '*' if name == '*' else field(name)
        if agg:
            expr = f'{AGGS[agg]}({expr})'
        alias = f'c{index}'
        aliases.add(name)
        parts.append(f'{expr} AS {dialect.quote(alias)}')
    group_sql = ', '.join(field(name) for name in groups)
    where, params = [], {}
    for index, item in enumerate(filters):
        if not isinstance(item, dict) or item.get('op') not in (*OPS, 'contains'):
            raise DatasetError('неизвестный фильтр')
        name = item.get('field')
        column = field(name)
        value = item.get('value')
        if not isinstance(value, (str, int, float, bool)):
            raise DatasetError('значение фильтра должно быть строкой или числом')
        param = f'q{index}'
        if item['op'] == 'contains':
            if dataset['source'] == 'oracle':
                raise DatasetError('поиск подстроки Oracle пока не поддерживается')
            if field_type(name) != 'string':
                raise DatasetError('поиск подстроки возможен только в текстовом поле')
            where.append(f'{column} LIKE {dialect.placeholder(param)}')
            params[param] = '%' + str(value).replace('%', '\\%').replace('_', '\\_') + '%'
        else:
            where.append(f'{column} {OPS[item["op"]]} {dialect.placeholder(param, field_type(name))}')
            params[param] = value
    adapter = registry.adapter_for(dataset)
    sql = f'SELECT {", ".join(parts)} FROM {adapter.source_sql("d")}'
    if where:
        sql += ' WHERE ' + ' AND '.join(where)
    if group_sql:
        sql += ' GROUP BY ' + group_sql
    order = plan.get('orderBy')
    if order:
        if not isinstance(order, dict) or order.get('field') not in aliases or order.get('direction') not in ('asc', 'desc'):
            raise DatasetError('сортировка должна ссылаться на выбранное поле')
        alias = next(f'c{i}' for i, item in enumerate(select) if item['field'] == order['field'])
        sql += f' ORDER BY {dialect.quote(alias)} {order["direction"].upper()}'
    limit = plan.get('limit', MAX_ROWS)
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise DatasetError('некорректный предел строк')
    visible_limit = min(limit, MAX_ROWS)
    # Дополнительная строка показывает, что выдача неполная, не считая весь
    # результат вторым запросом. Клиенту она не отдаётся.
    sql += ' ' + dialect.limit_offset(visible_limit + 1)
    return sql, params, {'select': select, 'groupBy': groups, 'filters': filters,
                         'orderBy': order, 'limit': visible_limit}


def explain_plan(dataset: dict, plan: dict, *, shown: int,
                 total: int | None, has_more: bool) -> dict:
    """Объяснение только из проверенного плана и реального объёма выдачи."""
    fields = {item['name']: item for item in dataset.get('schema') or []}

    def title(name: str) -> str:
        if name == '*':
            return 'все строки'
        item = fields.get(name) or {}
        return str(item.get('comment') or name)

    def calculation(item: dict) -> str:
        name = item['field']
        field = f'«{title(name)}»'
        return {
            'count': ('Количество строк' if name == '*'
                      else f'Количество непустых значений {field}'),
            'sum': f'Сумма значений {field}',
            'avg': f'Среднее значение {field}',
            'min': f'Минимум {field}',
            'max': f'Максимум {field}',
            '': f'Поле {field}',
        }[item.get('agg') or '']

    selected = plan['select']
    order = plan.get('orderBy')
    ordered = next((item for item in selected
                    if order and item['field'] == order['field']), None)
    filters = [
        f"«{title(item['field'])}» {FILTER_LABELS[item['op']]} «{item['value']}»"
        for item in plan['filters']
    ]
    return {
        'source': str(dataset.get('title') or dataset.get('slug') or 'Датасет'),
        'calculations': [calculation(item) for item in selected],
        'groupBy': [title(name) for name in plan['groupBy']],
        'filters': filters,
        'orderBy': (f"{calculation(ordered) if ordered else title(order['field'])} — "
                    + ('по возрастанию' if order['direction'] == 'asc'
                       else 'по убыванию')) if order else None,
        'scope': ('Операции выполнены по всем строкам, подходящим под условия; '
                  'лимит относится только к строкам ответа.'
                  if any(item.get('agg') for item in selected)
                  else 'Показаны строки датасета, подходящие под условия.'),
        'limit': plan['limit'],
        'shownRows': shown,
        'totalRows': total,
        'hasMore': has_more,
    }


def answer(dataset: dict, question: str, history: list[dict], *, reveal_sql: bool) -> dict:
    plan = propose(dataset, question, history)
    if dataset['source'] == 'csv':
        return _answer_csv(dataset, plan)
    sql, params, clean_plan = compile_plan(dataset, plan)
    adapter = registry.adapter_for(dataset, reuse=True)
    try:
        if dataset['source'] == 'postgres' and hasattr(adapter, '_connect'):
            conn = adapter._connect()
            conn.execute('SET statement_timeout = 30000')
            conn.execute('SET default_transaction_read_only = on')
        elif dataset['source'] == 'oracle' and hasattr(adapter, '_connect'):
            adapter._connect().call_timeout = 30000
        elif dataset['source'] == 'clickhouse':
            sql += ' SETTINGS max_execution_time = 30'
        _columns, rows = adapter.run_query(sql, params)
    except DatasetError as exc:
        raise DatasetError(sanitize_error(str(exc))) from exc
    finally:
        adapter.close()
    visible_limit = clean_plan['limit']
    safe_rows = [[str(value) if value is not None else '' for value in row]
                 for row in rows[:visible_limit]]
    truncated = len(rows) > visible_limit
    if not safe_rows:
        summary = 'По этому вопросу данных не найдено.'
    elif len(safe_rows) == 1 and len(safe_rows[0]) == 1 and not truncated:
        summary = f'{safe_rows[0][0]}'
    else:
        summary = f'Показано строк: {len(safe_rows)}.'
        if truncated:
            summary += ' Есть ещё строки.'
    labels = [f'{item.get("agg") or ""} {item["field"]}'.strip()
              for item in clean_plan['select']]
    result = {'answer': summary, 'columns': labels, 'rows': safe_rows,
              'plan': clean_plan, 'truncated': truncated,
              'explanation': explain_plan(dataset, clean_plan,
                                          shown=len(safe_rows), total=None,
                                          has_more=truncated)}
    if reveal_sql:
        result['sql'] = sql
        result['parameters'] = params
    return result


def _answer_csv(dataset: dict, plan: dict) -> dict:
    """Тот же ограниченный план над CSV; читаем файл целиком с потолком строк."""
    fields = {f['name'] for f in dataset.get('schema') or []}
    select = plan.get('select')
    groups = plan.get('groupBy') or []
    filters = plan.get('filters') or []
    if not isinstance(select, list) or not 1 <= len(select) <= 10 or not isinstance(groups, list) or len(groups) > 5 or any(not isinstance(g, str) for g in groups) or not isinstance(filters, list) or len(filters) > 10:
        raise DatasetError('план вопроса превышает допустимые пределы')
    for item in select:
        if not isinstance(item, dict) or item.get('field') not in fields | {'*'} or (item.get('agg') or '') not in (*AGGS, ''):
            raise DatasetError('неизвестное поле или операция')
        if item['field'] == '*' and item.get('agg') != 'count':
            raise DatasetError('поле * разрешено только для подсчёта строк')
    if any(name not in fields for name in groups):
        raise DatasetError('неизвестное поле группировки')
    for item in filters:
        if not isinstance(item, dict) or item.get('field') not in fields or item.get('op') not in (*OPS, 'contains') or not isinstance(item.get('value'), (str, int, float)):
            raise DatasetError('некорректный фильтр')
    adapter = registry.adapter_for(dataset)
    path = adapter._file
    if not path.exists():
        raise DatasetError('CSV-файл не загружен')
    def passes(row: dict) -> bool:
        for filt in filters:
            left, right = row.get(filt['field']) or '', str(filt['value'])
            op = filt['op']
            if op == 'contains':
                good = right.lower() in left.lower()
            elif op in ('eq', 'ne'):
                good = left == right if op == 'eq' else left != right
            else:
                try:
                    a, b = float(left), float(right)
                except ValueError:
                    a, b = left, right
                good = {'gt': a > b, 'gte': a >= b, 'lt': a < b, 'lte': a <= b}[op]
            if not good:
                return False
        return True
    rows = []
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        for index, row in enumerate(reader):
            if index >= 50000:
                raise DatasetError('CSV больше 50 000 строк — вопрос требует подключения к БД')
            if passes(row):
                rows.append(row)
    has_aggregate = any(item.get('agg') for item in select)
    if has_aggregate and any(not item.get('agg') and item['field'] not in groups for item in select):
        raise DatasetError('поле без агрегации должно входить в группировку')
    buckets = defaultdict(list)
    if has_aggregate:
        for row in rows:
            buckets[tuple(row.get(name) or '' for name in groups)].append(row)
        if not groups and not buckets:
            buckets[()] = []
    else:
        for index, row in enumerate(rows):
            key = tuple(row.get(name) or '' for name in groups) if groups else (index,)
            buckets[key].append(row)
    output = []
    for batch in buckets.values():
        result = []
        for item in select:
            name, agg = item['field'], item.get('agg') or ''
            values = [row.get(name) or '' for row in batch] if name != '*' else []
            if agg == 'count':
                value = len(batch) if name == '*' else sum(v != '' for v in values)
            elif agg in ('sum', 'avg'):
                try:
                    numbers = [float(v.replace(',', '.')) for v in values if v != '']
                except ValueError as exc:
                    raise DatasetError(f'поле {name} нельзя сложить как число') from exc
                value = sum(numbers) if agg == 'sum' else (sum(numbers) / len(numbers) if numbers else None)
            elif agg in ('min', 'max'):
                if values:
                    numeric = next((f for f in dataset['schema'] if f['name'] == name), {}).get('type', '').lower()
                    compare = (lambda v: float(v.replace(',', '.'))) if any(word in numeric for word in ('int', 'float', 'number', 'decimal')) else (lambda v: v)
                    value = (min if agg == 'min' else max)(values, key=compare)
                else:
                    value = None
            else:
                value = values[0] if values else ''
            result.append('' if value is None else str(value))
        output.append(result)
    order = plan.get('orderBy')
    if order:
        if not isinstance(order, dict) or order.get('direction') not in ('asc', 'desc'):
            raise DatasetError('некорректная сортировка')
        positions = [i for i, item in enumerate(select) if item['field'] == order.get('field')]
        if not positions:
            raise DatasetError('сортировка должна ссылаться на выбранное поле')
        position = positions[0]
        output.sort(key=lambda row: row[position], reverse=order['direction'] == 'desc')
    limit = plan.get('limit', MAX_ROWS)
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
        raise DatasetError('некорректный предел строк')
    visible = output[:min(limit, MAX_ROWS)]
    columns = [f'{item.get("agg") or ""} {item["field"]}'.strip() for item in select]
    truncated = len(output) > len(visible)
    summary = ('По этому вопросу данных не найдено.' if not visible else
               visible[0][0] if len(visible) == 1 and len(visible[0]) == 1 and not truncated else
               f'Показано {len(visible)} из {len(output)} строк.')
    clean_plan = {'select': select, 'groupBy': groups, 'filters': filters,
                  'orderBy': order, 'limit': min(limit, MAX_ROWS)}
    return {'answer': summary, 'columns': columns, 'rows': visible,
            'plan': clean_plan,
            'truncated': truncated,
            'explanation': explain_plan(dataset, clean_plan, shown=len(visible),
                                        total=len(output), has_more=truncated)}
