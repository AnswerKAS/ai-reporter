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
from .readonly import MAX_VISIBLE_ROWS, execute_readonly_sql, joinable_datasets, scope_dataset_sql

MAX_STEPS = 6
REPORT_MAX_STEPS = 8


def _action(raw: str) -> dict:
    """Extract a single JSON action from a model reply, including fenced JSON."""
    text = (raw or '').strip()
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except ValueError:
        pass
    decoder = json.JSONDecoder()
    candidates = []
    for match in re.finditer(r'\{', text):
        try:
            value, _ = decoder.raw_decode(text[match.start():])
            if isinstance(value, dict) and any(key in value for key in ('tool', 'final')):
                candidates.append(value)
        except ValueError:
            continue
    if candidates:
        return candidates[-1]
    raise DatasetError('агент вернул некорректное действие')


def _invoke(prompt: str, model: str, key: str) -> dict:
    """Ask the model for one ReAct action within the configured chat timeout."""
    return _action(interpret._ask(prompt, model, key, timeout=interpret.CHAT_TIMEOUT))


def _history(history: list[dict]) -> list[dict]:
    """Keep only question, answer and prior SQL relevant to a follow-up."""
    return [{'question': str(turn.get('question') or '')[:1000],
             'answer': str(turn.get('answer') or '')[:500],
             'sql': str(turn.get('sql') or '')[:5000],
             'datasetSlugs': list(turn.get('datasetSlugs') or
                                  ([turn['datasetSlug']] if turn.get('datasetSlug') else []))}
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
        supplied = labels.get(name)
        if isinstance(supplied, dict):
            supplied = supplied.get('Русское название') if supplied.get('sql_column', name) == name else None
        candidates = (configured, field.get('comment'), supplied, name)
        label = next((str(value).strip() for value in candidates
                      if value and re.search(r'[А-Яа-яЁё]', str(value))
                      and str(value).strip() not in translated), None)
        if label is None:
            raise DatasetError(
                f'Для столбца {name!r} укажи русское название в final.columnLabels; '
                'SQL и значения менять не нужно.')
        translated.append(label)
    return translated


def ask_dataset(dataset: dict, question: str, history: list[dict], *, reveal_sql: bool,
                on_event: Callable[[dict], None] | None = None) -> dict:
    """Keep the single-dataset API compatible with the multi-source agent."""
    return ask_datasets([dataset], question, history, reveal_sql=reveal_sql,
                        on_event=on_event)


def ask_datasets(datasets: list[dict], question: str, history: list[dict], *,
                 reveal_sql: bool, on_event: Callable[[dict], None] | None = None) -> dict:
    """Query each attached source and ground comparisons in observed SQL results."""
    selected = {item['slug']: item for item in datasets}
    if not selected:
        raise DatasetError('прикрепите хотя бы один датасет через @')
    if len(selected) != len(datasets):
        raise DatasetError('датасеты в вопросе не должны повторяться')
    key = interpret._openrouter_key()
    if not key:
        raise DatasetError('модель вопросов не настроена: нужен OPENROUTER_API_KEY')
    sources = []
    for dataset in datasets:
        settings = dataset.get('field_settings') or {}
        fields = [{'name': item['name'], 'type': item['type'],
                   'comment': item.get('comment') or '',
                   'title': (settings.get(item['name']) or {}).get('title') or ''}
                  for item in dataset.get('schema') or []]
        sources.append({'slug': dataset['slug'], 'title': dataset.get('title'),
                        'dialect': dataset['source'], 'fields': fields})
    relations = {
        dataset['slug']: {'dataset': dataset['slug'], **{
            f'dataset_{index}': item['slug']
            for index, item in enumerate(joinable_datasets(dataset, datasets), start=2)}}
        for dataset in datasets
    }
    base = (
        'Ты ReAct агент анализа данных. На каждом шаге верни ОДИН JSON-объект: '
        '{"tool":"describe_schema|sample_rows|execute_sql", "args":{...}} '
        'или {"final":{"answer":"...","calculations":["..."],'
        '"groupBy":["..."],"filters":["..."],"orderBy":null,"scope":"...",'
        '"columnLabels":{"slug":{"sql_column":"Русское название"}},'
        '"tableTitles":{"slug":"Краткое название результата"},'
        '"primaryDatasetSlug":"slug итоговой таблицы",'
        '"hypotheses":[{"text":"предположение","howToCheck":"способ проверки"}]}}. '
        'Для sample_rows и execute_sql укажи args.datasetSlug из прикреплённого списка; '
        'для execute_sql также укажи args.sql = "SELECT ... FROM dataset ...". '
        'Таблица dataset означает указанный датасет. dataset_2, dataset_3 и далее '
        'означают другие прикреплённые датасеты того же подключения по карте ниже. '
        'Используй поддерживаемые СУБД виды JOIN, включая INNER, LEFT, RIGHT, '
        'FULL, CROSS, SEMI, ANTI и ASOF, только между этими '
        'виртуальными отношениями. Физические таблицы, на которых основаны '
        'датасеты, и прочие таблицы подключения читать нельзя. '
        'Каждое подключение выполняет свой SQL. Для датасетов разных подключений '
        'делай отдельные запросы и сравнивай их результаты. '
        'Можно применять все функции SELECT, CTE, JOIN, подзапросы, '
        'оконные функции и выражения SQL соответствующего диалекта. '
        'Запрещено изменение данных или схемы. Сначала вызови execute_sql, '
        'для сравнения вызови его хотя бы раз для КАЖДОГО прикреплённого датасета. '
        'При ошибке исправь SQL и вызови инструмент снова. '
        'В final.columnLabels дай русское название каждому столбцу последнего '
        'результата SQL по каждому датасету; промежуточные запросы подписывать не нужно. '
        'В final.tableTitles дай отдельное короткое русское название таблицы последнего '
        'результата для каждого датасета. Название должно объяснять, что именно '
        'показано или посчитано (показатель, разрез или период), а не повторять '
        'название датасета. Промежуточные результаты подписывать не нужно. '
        'Сопоставляй только сравнимые периоды, единицы и ключи. Если общего ключа '
        'нет, не выдумывай связь. Гипотезы отделяй от фактов и добавляй способ проверки. '
        'Отвечай только по фактическим результатам инструментов, без вымышленных чисел. '
        'final.answer — готовый короткий ответ по-русски в Markdown. '
        'В final.primaryDatasetSlug укажи датасет с итоговым результатом, который '
        'прямо отвечает на вопрос; служебная выборка другого источника не является итогом. '
        'По умолчанию показывай одну итоговую таблицу, которая прямо отвечает на вопрос; '
        'последний SQL-запрос по одному датасету должен возвращать именно её, '
        'а промежуточные расчёты не представляй отдельными таблицами. '
        'Если несколько таблиц не запрошены явно, для одного датасета '
        'не вставляй Markdown-таблицы в final.answer: '
        'таблица последнего SQL-результата будет показана автоматически. '
        'При сравнении разных подключений можешь дать одну сводную Markdown-таблицу, '
        'основанную на проверенных результатах. Несколько отдельных таблиц делай '
        'только если пользователь явно попросил об этом. '
        'Не повторяй таблицы доказательств в тексте и не упоминай инструменты. '
        f'Прикреплённые датасеты: {json.dumps(sources, ensure_ascii=False)}. '
        f'Виртуальные отношения по основному датасету: '
        f'{json.dumps(relations, ensure_ascii=False)}. '
        f'Предыдущие вопросы: {json.dumps(_history(history), ensure_ascii=False)}. '
        f'Вопрос: {question[:1000]}.'
    )
    errors: list[str] = []
    results: list[dict] = []
    successful_budget = len(datasets) + 2
    for model in interpret._chat_models():
        if not model:
            continue
        latest_before_model = {item['datasetSlug']: item for item in results}
        prior_results = [{
            'datasetSlug': item['datasetSlug'], 'sql': item['sql'],
            'columns': item['columns'], 'rows': item['rows'][:20],
            'rowCount': len(item['rows']), 'truncated': item['truncated'],
        } for item in latest_before_model.values()]

        def decide(observations: list[dict]) -> dict:
            """Ask the model for a tool call or final answer."""
            covered = {item['datasetSlug'] for item in results}
            missing = [slug for slug in selected if slug not in covered]
            final_only = not missing and len(results) >= successful_budget
            if final_only:
                guidance = ('Все прикреплённые датасеты уже проверены, дополнительных '
                            'SQL-запросов достаточно. Сейчас верни только final с '
                            'ответом, columnLabels и tableTitles; инструменты больше '
                            'не вызывай.')
            elif missing and results:
                guidance = ('Следующий SQL выполни по ещё не проверенному датасету: '
                            + ', '.join(missing))
            else:
                guidance = 'Если наблюдений достаточно, заверши ответ через final.'
            prompt = (base + '\nПроверенные результаты предыдущей модели: '
                      + json.dumps(prior_results, ensure_ascii=False, default=str)[-8000:]
                      + '\nНаблюдения: ' + json.dumps(
                          observations, ensure_ascii=False, default=str)[-12000:]
                      + '\n' + guidance)
            action = _invoke(prompt, model, key)
            if final_only and 'final' not in action:
                raise DatasetError('модель не завершила ответ после проверенных SQL-результатов')
            return action

        def use_tool(action: dict) -> dict:
            """Inspect the dataset or run a bounded read-only SQL query."""
            tool = action.get('tool')
            args = action.get('args') if isinstance(action.get('args'), dict) else {}
            if tool == 'describe_schema':
                if on_event:
                    on_event({'type': 'status', 'text': 'Изучаю поля датасетов…'})
                return {'tool': tool, 'result': sources}
            if tool == 'sample_rows':
                slug = str(args.get('datasetSlug') or (datasets[0]['slug'] if len(datasets) == 1 else ''))
                if slug not in selected:
                    raise DatasetError(f'датасет {slug or "не указан"} не прикреплён')
                if on_event:
                    on_event({'type': 'status', 'text': f'Смотрю строки: {selected[slug]["title"]}…'})
                return {'tool': tool, 'datasetSlug': slug, 'result': _sample(selected[slug])}
            if tool == 'execute_sql':
                slug = str(args.get('datasetSlug') or (datasets[0]['slug'] if len(datasets) == 1 else ''))
                if slug not in selected:
                    raise DatasetError(f'датасет {slug or "не указан"} не прикреплён')
                dataset = selected[slug]
                if on_event:
                    on_event({'type': 'status', 'text': f'Считаю: {dataset["title"]}…'})
                logical_sql = str(args.get('sql') or '')
                sql = scope_dataset_sql(dataset, logical_sql,
                                        datasets=joinable_datasets(dataset, datasets))
                columns, rows, truncated = execute_readonly_sql(dataset, sql)
                results.append({'datasetSlug': slug, 'datasetTitle': dataset['title'],
                                'sql': logical_sql, 'columns': columns,
                                'rows': rows, 'truncated': truncated})
                return {'tool': tool, 'datasetSlug': slug, 'sql': logical_sql, 'columns': columns,
                        'rows': rows[:20], 'rowCount': len(rows),
                        'truncated': truncated}
            return {'error': 'Неизвестный инструмент. Выбери инструмент из списка.'}

        def finish(action: dict) -> tuple[dict | None, dict | None]:
            """Accept an answer only after the SQL tool returned real rows."""
            missing = [slug for slug in selected if slug not in
                       {item['datasetSlug'] for item in results}]
            if missing:
                return None, {'error': 'Сначала вызови execute_sql для каждого датасета: '
                              + ', '.join(missing)}
            final = action.get('final') or {}
            labels = final.get('columnLabels') if isinstance(final.get('columnLabels'), dict) else {}
            titles = final.get('tableTitles') if isinstance(final.get('tableTitles'), dict) else {}
            latest_results = {item['datasetSlug']: item for item in results}
            evidence = []
            for dataset in datasets:
                item = latest_results[dataset['slug']]
                source = selected[item['datasetSlug']]
                title = titles.get(item['datasetSlug'])
                if not isinstance(title, str) or not title.strip() or not re.search(
                        r'[А-Яа-яЁё]', title):
                    raise DatasetError('Укажи в final.tableTitles короткое русское '
                                       f'название результата для датасета {item["datasetSlug"]}.')
                if len(datasets) > 1 and not isinstance(labels.get(item['datasetSlug']), dict):
                    raise DatasetError('Укажи final.columnLabels отдельно для каждого '
                                       f'датасета, включая {item["datasetSlug"]}.')
                source_labels = labels.get(item['datasetSlug']) if isinstance(
                    labels.get(item['datasetSlug']), dict) else labels
                display_columns = _russian_columns(item['columns'],
                                                   {'columnLabels': source_labels}, source)
                evidence.append({**item, 'title': title.strip(), 'columns': display_columns,
                                 'rows': [[str(value) if value is not None else '' for value in row]
                                          for row in item['rows']]})
            primary_slug = final.get('primaryDatasetSlug') or datasets[0]['slug']
            if not isinstance(primary_slug, str) or primary_slug not in selected:
                raise DatasetError('Укажи в final.primaryDatasetSlug прикреплённый датасет '
                                   'с итоговой таблицей ответа.')
            primary = next(item for item in evidence if item['datasetSlug'] == primary_slug)
            hypotheses = [{'text': str(item.get('text') or '').strip(),
                           'howToCheck': str(item.get('howToCheck') or '').strip()}
                          for item in final.get('hypotheses', []) if isinstance(item, dict)
                          and str(item.get('text') or '').strip()]
            answer = str(final.get('answer') or '').strip() or f'Показано строк: {len(primary["rows"])}.'
            if on_event:
                on_event({'type': 'delta', 'text': answer})
            explanation = {
                'source': ', '.join(str(item.get('title') or item['slug']) for item in datasets),
                'calculations': [str(item) for item in final.get('calculations', [])],
                'groupBy': [str(item) for item in final.get('groupBy', [])],
                'filters': [str(item) for item in final.get('filters', [])],
                'orderBy': final.get('orderBy'),
                'scope': str(final.get('scope') or 'Расчёт выполнен SQL-запросом по датасету.'),
                'limit': MAX_VISIBLE_ROWS, 'shownRows': sum(len(item['rows']) for item in evidence),
                'totalRows': None, 'hasMore': any(item['truncated'] for item in evidence),
            }
            return ({'answer': answer, 'title': primary['title'],
                     'primaryDatasetSlug': primary_slug,
                     'columns': primary['columns'], 'rows': primary['rows'],
                     'plan': {'queries': [{'datasetSlug': item['datasetSlug'], 'sql': item['sql']}
                                          for item in evidence]},
                     'truncated': explanation['hasMore'], 'evidence': evidence,
                     'hypotheses': hypotheses, 'explanation': explanation,
                     'sql': primary['sql'] if len(evidence) == 1 else None,
                     'parameters': {}}, None)

        step_limit = (max(MAX_STEPS, len(datasets) * 3 + 3)
                      if not prior_results else max(4, len(datasets) + 2))
        state = run_graph(decide, use_tool, finish, max_steps=step_limit)
        if state['output'] is not None:
            return state['output']
        errors.append(state['error'] or 'агент не завершил ответ за допустимое число шагов')
    raise DatasetError(errors[0] if errors else 'модель вопросов недоступна')


def _report_resources(catalog, metrics: dict, dimensions: dict,
                      preferred: list[str], attached: list[str]) -> dict:
    """Prepare the schema and semantic vocabulary before the first model call."""
    requested = set(preferred)
    items = sorted((item for item in catalog.datasets.values()
                    if not attached or item['slug'] in attached),
                   key=lambda item: (item['slug'] not in requested, item['slug']))
    items = items[:max(30, len(attached))]
    visible_metrics = {slug: item for slug, item in metrics.items()
                       if not attached or item.get('dataset_slug') in attached}
    visible_dimensions = {slug: item for slug, item in dimensions.items()
                          if not attached or item.get('dataset_slug') in attached}
    return {
        'datasets': [
            {'slug': item['slug'], 'title': item.get('title'), 'source': item['source'],
             'joinableDatasetSlugs': [other['slug'] for other in
                                      joinable_datasets(item, items)],
             'fields': [{'name': field['name'], 'type': field['type'],
                         'title': (item.get('field_settings') or {}).get(
                             field['name'], {}).get('title'),
                         'comment': field.get('comment')}
                        for field in item.get('schema') or []]}
            for item in items],
        'metrics': visible_metrics,
        'dimensions': visible_dimensions,
    }


def _report_observations(observations: list[dict]) -> str:
    """Keep repair evidence while omitting metadata already in the prompt."""
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
    """Describe a verified proposal when the model did not supply a reply."""
    titles = [str(section.get('title') or '').strip()
              for section in definition.get('sections') or []]
    visible = [title for title in titles if title]
    return ('Подготовил отчёт: ' + ', '.join(visible[:4]) + '.') if visible else (
        'Отчёт готов. Проверьте предпросмотр и сохраните его.')


def chat_report(messages: list[dict], catalog, fields=None, computed=None,
                datasets=None, definition=None,
                on_event: Callable[[dict], None] | None = None,
                attached_datasets: list[str] | None = None) -> dict:
    """Build and preview a persistent visual report with LangGraph tools."""
    attached = list(dict.fromkeys(attached_datasets or []))
    unknown = [slug for slug in attached if slug not in catalog.datasets]
    if unknown:
        raise DatasetError('прикреплённый датасет не найден: ' + ', '.join(unknown))
    preferred = list(dict.fromkeys(attached + list(datasets or [])))
    key = interpret._openrouter_key()
    if not key:
        raise DatasetError('Модель для конструктора не настроена. Добавьте ключ модели в конфигурацию сервера.')
    said = [item for item in (messages or []) if str(item.get('text') or '').strip()]
    if not said:
        raise DatasetError('напишите, какой отчёт нужен — обычными словами')
    metrics, dimensions = interpret.vocabulary_of(
        catalog, fields, computed, attached or None)
    if not metrics and not catalog.datasets:
        return interpret.chat(messages, catalog, fields, computed, datasets, definition)
    resources = _report_resources(catalog, metrics, dimensions, preferred, attached)
    base = (
        'Ты ReAct агент создания отчётов. Верни один JSON: '
        '{"tool":"preview_report","args":{"definition":{...},'
        '"reply":"...","title":"..."}}. '
        'Если для SQL действительно нужны примеры значений, сначала вызови '
        '{"tool":"sample_dataset","args":{"datasetSlug":"..."}}. '
        'Схемы датасетов и словарь уже приведены ниже. Сразу собери полный визуальный '
        'отчёт с понятными названиями блоков. Выбирай KPI для главных чисел, '
        'линию или область для динамики, столбцы для сравнения, таблицу для деталей; '
        'добавляй подходящие фильтры и несколько датасетов, когда это полезно. '
        'Выбирай вид по смыслу данных, не добавляй пустых или дублирующих блоков. '
        'Для готового отчёта вызови preview_report с полным ReportDefinition, '
        'кратким reply и названием title. Успешная проверка завершит ход; '
        'после ошибки исправь определение следующим вызовом. '
        'Формат args.definition: {"sections":[{"type":"table|chart|kpi",'
        '"title":"...","datasetSlug":"slug","joinDatasetSlugs":[], '
        '"sql":"SELECT ... FROM dataset"}],'
        '"filters":[]}. Список карточек называется sections, не blocks. '
        'Если пользователь просит фильтры или по полям есть полезные разрезы, '
        'добавь filters:[{"dimension":"ключ разреза","kind":"select|daterange|number"}] '
        'из get_vocabulary. Поля даты используй как daterange. '
        'Фильтры применяются к виртуальной таблице dataset до выполнения SQL. '
        'В reply кратко объясни состав предложенного отчёта. '
        'Текущий отчёт можно дополнять. Не выдумывай slug полей. '
        'Для сравнений, рейтингов, периодов и изменения показателей во времени '
        'самостоятельно выбирай агрегации, CTE, JOIN и оконные функции '
        'по смыслу запроса и схеме датасета. Не отказывайся из-за ограничений '
        'словарных формул: здесь доступен SQL-блок. '
        'Выбирай нужные колонки из схемы самостоятельно; от пользователя '
        'не требуется отмечать поля на шаге «Данные». '
        'Когда словарной раскладки недостаточно, создай SQL-блок: '
        '{"type":"table|chart|kpi","title":"...","datasetSlug":"slug",'
        '"sql":"SELECT ... FROM dataset ...","metrics":[],"by":[]}. '
        'SQL-блок поддерживает оконные функции, CTE и все виды JOIN, доступные '
        'СУБД (включая INNER, LEFT, RIGHT, FULL, CROSS, SEMI, ANTI, ASOF). '
        'Таблица dataset означает основной datasetSlug; '
        'dataset_2, dataset_3 и далее означают элементы joinDatasetSlugs по порядку. '
        'В joinDatasetSlugs указывай только датасеты из joinableDatasetSlugs '
        'основного датасета; если датасеты прикреплены явно, используй только их. '
        'Нельзя читать исходные '
        'физические таблицы и другие таблицы подключения. Нельзя изменять данные. '
        'Для графика первая колонка SQL — ось, следующие — ряды. '
        f'Прикреплённые датасеты (обязательные источники для SQL-блоков): '
        f'{json.dumps(attached, ensure_ascii=False)}. '
        f'Предпочтительные датасеты: {json.dumps(preferred, ensure_ascii=False)}. '
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
            if tool == 'sample_dataset':
                slug = str(args.get('datasetSlug') or '')
                if attached and slug not in attached:
                    raise DatasetError('образец можно читать только из прикреплённого датасета')
                dataset = catalog.datasets.get(slug)
                if dataset is None:
                    raise DatasetError('датасет не найден: ' + slug)
                if on_event:
                    on_event({'type': 'status', 'text': 'Смотрю примеры строк датасета…'})
                return {'tool': tool, 'datasetSlug': slug, **_sample(dataset)}
            if tool == 'preview_report':
                if on_event:
                    on_event({'type': 'status', 'text': 'Проверяю карточки на данных…'})
                validated = None
                raw_definition = args.get('definition') or {}
                if (isinstance(raw_definition, dict) and not raw_definition.get('sections')
                        and isinstance(raw_definition.get('blocks'), list)):
                    raw_definition = {**raw_definition, 'sections': raw_definition['blocks']}
                candidate = interpret._validate(raw_definition,
                                                metrics, dimensions)
                if attached:
                    wrong = [section.get('datasetSlug') for section in candidate['sections']
                             if section.get('sql') and section.get('datasetSlug') not in attached]
                    wrong += [slug for section in candidate['sections'] if section.get('sql')
                              for slug in (section.get('joinDatasetSlugs') or [])
                              if slug not in attached]
                    if wrong:
                        raise DatasetError('SQL-блок ссылается не на прикреплённый датасет: '
                                           + ', '.join(str(slug) for slug in wrong))
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

        state = run_graph(decide, use_tool, finish, max_steps=REPORT_MAX_STEPS)
        if state['output'] is not None:
            return state['output']
        last_error = next((str(item['result']['error'])
                           for item in reversed(state['observations'])
                           if isinstance(item.get('result'), dict)
                           and item['result'].get('error')), None)
        errors.append(state['error'] or last_error or 'агент не завершил построение отчёта')
    raise DatasetError(errors[0] if errors else 'модель отчётов недоступна')
