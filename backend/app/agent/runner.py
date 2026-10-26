"""Bounded ReAct loops for dataset questions and report composition."""

import json
import re
from collections.abc import Callable

from ..datasets import registry
from ..datasets.base import DatasetError
from ..query import interpret
from ..reports import executor
from ..schemas.definition import ReportDefinition
from .graph import run_graph
from .readonly import MAX_VISIBLE_ROWS, execute_readonly_sql, scope_dataset_sql

MAX_STEPS = 6


def _action(raw: str) -> dict:
    """Extract a single JSON action from a model reply, including fenced JSON."""
    text = (raw or '').strip()
    try:
        return json.loads(text)
    except ValueError:
        pass
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            value = json.loads(match.group())
            if isinstance(value, dict):
                return value
        except ValueError:
            pass
    raise DatasetError('агент вернул некорректное действие')


def _invoke(prompt: str, model: str, key: str) -> dict:
    """Ask the model for one ReAct action within the configured chat timeout."""
    return _action(interpret._ask(prompt, model, key, timeout=interpret.CHAT_TIMEOUT))


def _history(history: list[dict]) -> list[dict]:
    """Keep only question, answer and prior SQL relevant to a follow-up."""
    return [{'question': str(turn.get('question') or '')[:1000],
             'answer': str(turn.get('answer') or '')[:500],
             'sql': str(turn.get('sql') or '')[:5000]}
            for turn in history[-8:]]


def _sample(dataset: dict) -> dict:
    """Read five example rows through the existing dataset adapter."""
    adapter = registry.adapter_for(dataset)
    try:
        columns, rows = adapter.sample_rows(limit=5)
        return {'columns': list(columns), 'rows': [list(map(str, row)) for row in rows]}
    finally:
        adapter.close()


def _russian_columns(columns: list[str], final: dict, dataset: dict) -> list[str]:
    """Resolve every result column to a distinct Russian display heading."""
    labels = final.get('columnLabels') if isinstance(final.get('columnLabels'), dict) else {}
    schema = {item['name']: item for item in dataset.get('schema') or []}
    settings = dataset.get('field_settings') or {}
    translated: list[str] = []
    for name in columns:
        field = schema.get(name) or {}
        configured = (settings.get(name) or {}).get('title')
        candidates = (configured, field.get('comment'), labels.get(name), name)
        label = next((str(value).strip() for value in candidates
                      if value and re.search(r'[А-Яа-яЁё]', str(value))
                      and str(value).strip() not in translated), None)
        if label is None:
            raise DatasetError(
                f'Для столбца {name!r} укажи русское название в final.columnLabels; '
                'SQL и значения менять не нужно.')
        translated.append(label)
    return translated


def ask_dataset(dataset: dict, question: str, history: list[dict], *,
                on_event: Callable[[dict], None] | None = None) -> dict:
    """Let the model inspect data, execute read-only SQL and explain the result."""
    key = interpret._openrouter_key()
    if not key:
        raise DatasetError('модель вопросов не настроена: нужен OPENROUTER_API_KEY')
    settings = dataset.get('field_settings') or {}
    fields = [{'name': item['name'], 'type': item['type'],
               'comment': item.get('comment') or '',
               'title': (settings.get(item['name']) or {}).get('title') or ''}
              for item in dataset.get('schema') or []]
    base = (
        'Ты ReAct агент анализа данных. На каждом шаге верни ОДИН JSON-объект: '
        '{"tool":"describe_schema|sample_rows|execute_sql", "args":{...}} '
        'или {"final":{"answer":"...","calculations":["..."],'
        '"groupBy":["..."],"filters":["..."],"orderBy":null,"scope":"...",'
        '"columnLabels":{"sql_column":"Русское название"}}}. '
        'Для execute_sql аргумент — {"sql":"SELECT ... FROM dataset ..."}. '
        'Таблица dataset — выбранный датасет. Можно применять все функции SELECT, '
        'CTE, JOIN, подзапросы, оконные функции и выражения SQL выбранного диалекта. '
        'Запрещено изменение данных или схемы. Сначала вызови execute_sql, '
        'при ошибке исправь SQL и вызови инструмент снова. '
        'В final.columnLabels дай русское название каждому столбцу результата SQL. '
        'Отвечай только по фактическому результату инструмента, без вымышленных чисел. '
        f'Диалект: {dataset["source"]}. Датасет: {dataset.get("title")}. '
        f'Поля: {json.dumps(fields, ensure_ascii=False)}. '
        f'Предыдущие вопросы: {json.dumps(_history(history), ensure_ascii=False)}. '
        f'Вопрос: {question[:1000]}.'
    )
    errors: list[str] = []
    for model in interpret._chat_models():
        if not model:
            continue
        result: tuple[str, list[str], list[list], bool] | None = None

        def decide(observations: list[dict]) -> dict:
            """Ask the model for a tool call or final answer."""
            return _invoke(base + '\nНаблюдения: ' + json.dumps(
                observations, ensure_ascii=False, default=str)[-16000:], model, key)

        def use_tool(action: dict) -> dict:
            """Inspect the dataset or run a bounded read-only SQL query."""
            nonlocal result
            tool = action.get('tool')
            args = action.get('args') if isinstance(action.get('args'), dict) else {}
            if tool == 'describe_schema':
                if on_event:
                    on_event({'type': 'status', 'text': 'Изучаю поля датасета…'})
                return {'tool': tool, 'result': fields}
            if tool == 'sample_rows':
                if on_event:
                    on_event({'type': 'status', 'text': 'Смотрю примеры строк…'})
                return {'tool': tool, 'result': _sample(dataset)}
            if tool == 'execute_sql':
                if on_event:
                    on_event({'type': 'status', 'text': 'Выполняю запрос к данным…'})
                result = None
                logical_sql = str(args.get('sql') or '')
                sql = scope_dataset_sql(dataset, logical_sql)
                columns, rows, truncated = execute_readonly_sql(dataset, sql)
                result = (logical_sql, columns, rows, truncated)
                return {'tool': tool, 'sql': logical_sql, 'columns': columns,
                        'rows': rows[:20], 'rowCount': len(rows),
                        'truncated': truncated}
            return {'error': 'Неизвестный инструмент. Выбери инструмент из списка.'}

        def finish(action: dict) -> tuple[dict | None, dict | None]:
            """Accept an answer only after the SQL tool returned real rows."""
            if result is None:
                return None, {'error': 'Сначала вызови execute_sql.'}
            final = action.get('final') or {}
            sql, columns, rows, truncated = result
            display_columns = _russian_columns(columns, final, dataset)
            safe_rows = [[str(value) if value is not None else '' for value in row]
                         for row in rows]
            answer = str(final.get('answer') or '').strip() or f'Показано строк: {len(safe_rows)}.'
            if on_event:
                on_event({'type': 'delta', 'text': answer})
            explanation = {
                'source': str(dataset.get('title') or dataset.get('slug')),
                'calculations': [str(item) for item in final.get('calculations', [])],
                'groupBy': [str(item) for item in final.get('groupBy', [])],
                'filters': [str(item) for item in final.get('filters', [])],
                'orderBy': final.get('orderBy'),
                'scope': str(final.get('scope') or 'Расчёт выполнен SQL-запросом по датасету.'),
                'limit': MAX_VISIBLE_ROWS, 'shownRows': len(safe_rows),
                'totalRows': None, 'hasMore': truncated,
            }
            return ({'answer': answer, 'columns': display_columns, 'rows': safe_rows,
                     'plan': {'sql': sql}, 'truncated': truncated,
                     'explanation': explanation, 'sql': sql, 'parameters': {}}, None)

        state = run_graph(decide, use_tool, finish, max_steps=MAX_STEPS)
        if state['output'] is not None:
            return state['output']
        errors.append(state['error'] or 'агент не завершил ответ за допустимое число шагов')
    raise DatasetError(errors[0] if errors else 'модель вопросов недоступна')


def _report_resources(catalog, metrics: dict, dimensions: dict,
                      preferred: list[str]) -> dict:
    """Prepare dataset schemas and vocabulary before the first model call."""
    requested = set(preferred)
    items = sorted(catalog.datasets.values(),
                   key=lambda item: (item['slug'] not in requested, item['slug']))
    return {'datasets': [
        {'slug': item['slug'], 'title': item.get('title'),
         'source': item['source'],
         'fields': [{'name': field['name'], 'type': field['type']}
                    for field in item.get('schema') or []]}
        for item in items[:30]],
        'metrics': metrics, 'dimensions': dimensions}


def _report_observations(observations: list[dict]) -> str:
    """Keep failed drafts and samples without repeating prefetched metadata."""
    relevant = []
    for item in observations:
        action = item.get('action') or {}
        if action.get('tool') in ('get_datasets', 'get_vocabulary'):
            continue
        result = item.get('result') or {}
        if action.get('tool') == 'preview_report' and isinstance(result, dict):
            if result.get('valid'):
                continue
            relevant.append({'action': action, 'error': result.get('error')})
        else:
            relevant.append(item)
    return json.dumps(relevant[-4:], ensure_ascii=False, default=str)[-12000:]


def _report_reply(definition: dict) -> str:
    """Describe a verified proposal when no reply accompanied its draft."""
    titles = [str(section.get('title') or '').strip()
              for section in definition.get('sections') or []]
    visible = [title for title in titles if title]
    return ('Подготовил отчёт: ' + ', '.join(visible[:4]) + '.') if visible else (
        'Отчёт готов. Проверьте предпросмотр и сохраните его.')


def chat_report(messages: list[dict], catalog, fields=None, computed=None,
                datasets=None, definition=None,
                on_event: Callable[[dict], None] | None = None) -> dict:
    """Build and preview a persistent visual report with LangGraph tools."""
    key = interpret._openrouter_key()
    if not key:
        result = interpret.chat(messages, catalog, fields, computed, datasets, definition)
        if not result.get('definition') and result.get('recommendations'):
            choice = result['recommendations'][0]
            result.update(definition=choice['definition'], title=choice['title'],
                          reply=f'Собрал «{choice["title"]}» по доступным данным. Проверьте раскладку и сохраните отчёт.')
        result.pop('recommendations', None)
        return result
    said = [item for item in (messages or []) if str(item.get('text') or '').strip()]
    if not said:
        raise DatasetError('напишите, какой отчёт нужен — обычными словами')
    metrics, dimensions = interpret.vocabulary_of(catalog, fields, computed)
    if not metrics and not catalog.datasets:
        return interpret.chat(messages, catalog, fields, computed, datasets, definition)
    resources = _report_resources(catalog, metrics, dimensions, list(datasets or []))
    base = (
        'Ты ReAct агент создания отчётов. Верни один JSON: '
        '{"tool":"preview_report","args":{"definition":{...},'
        '"reply":"...","title":"..."}}. '
        'Схемы датасетов и словарь уже приведены ниже. Сразу собери полный визуальный '
        'отчёт с понятными названиями блоков. Выбирай KPI для главных чисел, '
        'линию или область для динамики, столбцы для сравнения, таблицу для деталей; '
        'добавляй подходящие фильтры и несколько датасетов, когда это полезно. '
        'Выбирай вид по смыслу данных, не добавляй пустых или дублирующих блоков. '
        'Для готового отчёта вызови preview_report с полным ReportDefinition, '
        'кратким reply и названием title. Успешная проверка завершит ход; '
        'после ошибки исправь определение следующим вызовом. '
        'В reply кратко объясни состав предложенного отчёта. '
        'Текущий отчёт можно дополнять. Не выдумывай slug полей. '
        'Когда словарной раскладки недостаточно, создай SQL-блок: '
        '{"type":"table|chart|kpi","title":"...","datasetSlug":"slug",'
        '"sql":"SELECT ... FROM dataset ...","metrics":[],"by":[]}. '
        'SQL-блок поддерживает любые функции чтения, включая оконные, CTE, JOIN. '
        'Нельзя изменять данные. Таблица dataset означает выбранный датасет. '
        'Для графика первая колонка SQL — ось, следующие — ряды. '
        f'Предпочтительные датасеты: {json.dumps(datasets or [], ensure_ascii=False)}. '
        f'Текущий отчёт: {json.dumps(definition or {}, ensure_ascii=False)}. '
        f'Переписка: {interpret._history(said, interpret.CHAT_HISTORY)}. '
        f'Доступные схемы и словарь: {json.dumps(resources, ensure_ascii=False, default=str)}.'
    )
    errors: list[str] = []
    for model in interpret._chat_models():
        if not model:
            continue
        validated: dict | None = None
        draft_reply = ''
        draft_title = ''

        def decide(observations: list[dict]) -> dict:
            """Ask the model to inspect context, validate a draft or finish."""
            if validated is not None:
                return {'final': {'reply': draft_reply or _report_reply(validated),
                                  'title': draft_title}}
            return _invoke(base + '\nНаблюдения: ' + _report_observations(observations),
                           model, key)

        def use_tool(action: dict) -> dict:
            """Expose report metadata or validate and preview its definition."""
            nonlocal validated, draft_reply, draft_title
            tool = action.get('tool')
            args = action.get('args') if isinstance(action.get('args'), dict) else {}
            if tool == 'get_vocabulary':
                if on_event:
                    on_event({'type': 'status', 'text': 'Изучаю показатели и разрезы…'})
                return {'tool': tool, 'metrics': resources['metrics'],
                        'dimensions': resources['dimensions']}
            if tool == 'get_datasets':
                if on_event:
                    on_event({'type': 'status', 'text': 'Изучаю датасеты…'})
                return {'tool': tool, 'datasets': resources['datasets']}
            if tool == 'preview_report':
                if on_event:
                    on_event({'type': 'status', 'text': 'Проверяю карточки на данных…'})
                validated = None
                candidate = interpret._validate(args.get('definition') or {},
                                                metrics, dimensions)
                report = ReportDefinition.model_validate(candidate)
                previews = []
                for section in report.sections:
                    block = executor.build_section(
                        section.model_copy(update={'limit': min(section.limit or 20, 20)}),
                        {}, catalog, computed=candidate.get('computed'),
                        fields=candidate.get('fields'))
                    previews.append({'type': block['type'], 'title': block.get('title'),
                                     'kind': block.get('kind'),
                                     'columns': [item.get('header') for item in block.get('columns', [])],
                                     'series': [item.get('name') for item in block.get('series', [])],
                                     'rows': len(block.get('rows', block.get('data', []))),
                                     'items': block.get('items', [])[:5]})
                validated = candidate
                draft_reply = str(args.get('reply') or '').strip()
                draft_title = str(args.get('title') or '').strip()
                return {'tool': tool, 'valid': True, 'blocks': previews}
            return {'error': 'Неизвестный инструмент.'}

        def finish(action: dict) -> tuple[dict | None, dict | None]:
            """Return a verified report proposal and a conversational reply."""
            final = action.get('final') if isinstance(action.get('final'), dict) else action
            if validated is None:
                return None, {'error': 'Сначала вызови preview_report для полного отчёта.'}
            reply = str(final.get('reply') or '').strip()
            if on_event:
                on_event({'type': 'delta', 'text': reply or 'Отчёт готов. Проверьте предпросмотр и сохраните его.'})
            return ({'reply': reply or 'Раскладка готова — проверьте предпросмотр.',
                     'definition': validated,
                     'title': str(final.get('title') or '').strip() or None,
                     'notes': [], 'source': 'agent',
                     'model': interpret._model_id(model)}, None)

        state = run_graph(decide, use_tool, finish, max_steps=MAX_STEPS)
        if state['output'] is not None:
            return state['output']
        errors.append(state['error'] or 'агент не завершил построение отчёта')
    raise DatasetError(errors[0] if errors else 'модель отчётов недоступна')
