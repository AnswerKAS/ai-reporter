"""Черновики скиллов: генерация по описанию и проверка правил через opencode.

Генерация: агент по правилам opencode-скилла report-skill, метаданным
выбранных датасетов и словесному описанию пользователя пишет markdown-скилл
в workdir черновика (skill.md), текст сохраняется в БД.

Проверка: отдельный агент-ревьюер сверяет скилл с правилами и пишет вердикт
verdict.json {ok: bool, issues: [...]}.
"""

import asyncio
import json
from pathlib import Path

from ..core.config import BASE_DIR
from ..core import database as db
from ..datasets import registry as dataset_registry
from ..services import storage
from .compiler import OPENCODE_BIN, OPENCODE_MODEL, OPENCODE_TIMEOUT, _run

RULES_PATH = BASE_DIR / '.opencode' / 'skills' / 'report-skill' / 'SKILL.md'

GENERATE_PROMPT = '''
Ты — автор скилл-файлов отчётов для системы ai-reporter.

=== ПРАВИЛА СОЗДАНИЯ СКИЛЛОВ ===
{rules}
=== КОНЕЦ ПРАВИЛ ===

Доступные датасеты (реестр бэкенда; описание полей можно использовать
в секции «Источник данных» скилла):
{datasets}

Пожелание пользователя (что должно быть в отчёте):
"""
{description}
"""

=== ПРОВЕРКА ДАННЫХ (обязательна) ===
Прежде чем писать скилл, сверь каждое требование пользователя с полями
перечисленных датасетов:
- использовать можно ТОЛЬКО существующие поля и таблицы из списка;
- придумывать поля, таблицы и источники запрещено;
- если данных недостаточно (нет нужных полей/разрезов/таблиц или запрос
  внутренне противоречив) — НЕ создавай skill.md. Вместо него запиши файл
  `unavailable.json` строго в формате:
  {{"reason": "что именно отсутствует или противоречит", "suggestions": ["что можно построить на имеющихся данных"]}}
  и больше ничего.
- если данные достаточны — создавай skill.md и НЕ создавай unavailable.json.
=== КОНЕЦ ПРОВЕРКИ ===

Задание:
1. Придумай и напиши markdown-скилл строго по правилам и каркасу:
   заголовок «# Скилл: {title}», секции Цель / Источник данных /
   Что должно быть в отчёте / Формат вывода / Параметры (и Фильтры,
   если нужны). Поля датасетов бери только из перечисленных выше датасетов.
2. Запиши готовый скилл в файл `skill.md` в текущей директории
   (только файл, ничего больше не запускай).
'''

CHECK_PROMPT = '''
Ты — ревьюер скилл-файлов отчётов ai-reporter.

=== ПРАВИЛА СОЗДАНИЯ СКИЛЛОВ ===
{rules}
=== КОНЕЦ ПРАВИЛ ===

=== ПРОВЕРЯЕМЫЙ СКИЛЛ ===
{skill}
=== КОНЕЦ СКИЛЛА ===

Проверь скилл на соответствие правилам: обязательные секции и их порядок,
корректность описания источника данных и полей, конкретность секции
«Что должно быть в отчёте» (форматы money/percent/date, сортировки, лимиты),
наличие «Формат вывода», разумность «Параметры»/«Фильтры», опечатки.
Slug'и датасетов из секции «## Датасеты» фиксированы реестром: не считай
их опечатками и не предлагай переименовывать.

Задание: запиши вердикт в файл `verdict.json` в текущей директории строго
в формате:
{{"ok": true/false, "issues": ["список замечаний; пустой, если ok"]}}
Файл должен содержать только JSON.
'''

IMPROVE_PROMPT = '''
Ты — редактор скилл-файлов отчётов ai-reporter.

=== ПРАВИЛА СОЗДАНИЯ СКИЛЛОВ ===
{rules}
=== КОНЕЦ ПРАВИЛ ===

=== СКИЛЛ К ИСПРАВЛЕНИЮ ===
{skill}
=== КОНЕЦ СКИЛЛА ===

=== ЗАМЕЧАНИЯ РЕВЬЮЕРА ===
{issues}
=== КОНЕЦ ЗАМЕЧАНИЙ ===

Задание:
1. Проверь скилл по правилам: обязательные секции и их порядок
   (Датасеты сразу после заголовка, Цель, Источник данных, Что должно
   быть в отчёте, Формат вывода, Параметры), конкретность «Что должно
   быть в отчёте» (форматы money/percent/date, сортировки, LIMIT),
   разумность фильтров, опечатки.
2. Slug'и датасетов из секции «## Датасеты» фиксированы реестром —
   НЕ переименовывай их и не исправляй «опечатки» в них (например
   «tast-field-details» может быть настоящим slug'ом).
3. Исправь все найденные ошибки и улучши формулировки. Суть отчёта
   и поля датасетов не меняй: добавлять поля/источники, которых нет,
   запрещено.
4. Запиши улучшенный скилл в файл `skill.md` в текущей директории
   (только файл, ничего больше не запускай).
'''


def _datasets_text(slugs: list[str]) -> str:
    items = dataset_registry.for_slugs(slugs)
    if not items:
        return '(датасеты не выбраны — опиши типовые поля)'
    lines = []
    for d in items:
        fields = ', '.join(f"{f['name']} ({f['type']})" for f in (d.get('schema') or [])) or 'схема не вычитана'
        lines.append(f"- {d['slug']}: {d['title']} [{d['source']}{'/таблица ' + d['table_name'] if d.get('table_name') else ''}] — {fields}")
    return '\n'.join(lines)


def _draft_dir(draft_id: str) -> Path:
    path = storage.path('draft', draft_id, 'skill.md').parent
    path.mkdir(parents=True, exist_ok=True)
    return path


async def generate_content(draft: dict, description: str | None = None) -> dict:
    """Генерирует скилл агентом.

    Возвращает {'content': markdown | None, 'unavailable': {'reason', 'suggestions'} | None}.
    """
    workdir = _draft_dir(draft['id'])
    rules = RULES_PATH.read_text(encoding='utf-8') if RULES_PATH.exists() else ''
    prompt_text = GENERATE_PROMPT.format(
        rules=rules,
        datasets=_datasets_text(draft.get('datasets') or []),
        description=(description or draft.get('description') or '').strip(),
        title=draft.get('title') or draft.get('name'),
    )
    skill_file = workdir / 'skill.md'
    unavailable_file = workdir / 'unavailable.json'
    skill_file.unlink(missing_ok=True)
    unavailable_file.unlink(missing_ok=True)
    code, output = await _run_opencode(workdir, prompt_text)
    if code != 0:
        raise AgentRuntimeError(code, output)
    if skill_file.exists():
        return {'content': skill_file.read_text(encoding='utf-8'), 'unavailable': None}
    if unavailable_file.exists():
        try:
            data = json.loads(unavailable_file.read_text(encoding='utf-8'))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f'невалидный unavailable.json: {exc}') from exc
        return {'content': None, 'unavailable': {
            'reason': str(data.get('reason') or 'данных недостаточно'),
            'suggestions': [str(s) for s in (data.get('suggestions') or [])],
        }}
    raise RuntimeError('агент не создал skill.md:\n' + output[-1500:])


async def check_content(draft: dict) -> dict:
    """Проверяет скилл по правилам; вердикт {ok, issues}."""
    workdir = _draft_dir(draft['id'])
    rules = RULES_PATH.read_text(encoding='utf-8') if RULES_PATH.exists() else ''
    prompt_text = CHECK_PROMPT.format(rules=rules, skill=draft.get('content') or '')
    verdict_file = workdir / 'verdict.json'
    verdict_file.unlink(missing_ok=True)
    code, output = await _run_opencode(workdir, prompt_text)
    if code != 0:
        raise AgentRuntimeError(code, output)
    if not verdict_file.exists():
        raise AgentRuntimeError(code, 'агент не создал verdict.json:\n' + output[-1500:])
    try:
        verdict = json.loads(verdict_file.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise AgentRuntimeError(0, f'невалидный вердикт: {exc}') from exc
    ok = bool(verdict.get('ok'))
    issues = [str(i) for i in (verdict.get('issues') or [])]
    if not ok and not issues:
        issues = ['скилл не соответствует правилам (детализацию агент не дал)']
    return {'ok': ok, 'issues': issues}


async def improve_content(draft: dict) -> str:
    """Агент-редактор проверяет скилл по правилам и исправляет ошибки."""
    workdir = _draft_dir(draft['id'])
    rules = RULES_PATH.read_text(encoding='utf-8') if RULES_PATH.exists() else ''
    issues = draft.get('issues') or []
    issues_text = '\n'.join(f'- {i}' for i in issues) if issues else '(нет формальных замечаний — улучши скилл по правилам)'
    prompt_text = IMPROVE_PROMPT.format(
        rules=rules,
        skill=draft.get('content') or '',
        issues=issues_text,
    )
    skill_file = workdir / 'skill.md'
    skill_file.unlink(missing_ok=True)
    code, output = await _run_opencode(workdir, prompt_text)
    if code != 0:
        raise AgentRuntimeError(code, output)
    if not skill_file.exists():
        raise AgentRuntimeError(code, 'агент не создал skill.md:\n' + output[-1500:])
    return skill_file.read_text(encoding='utf-8')


def _run_opencode_cmd(workdir: Path, prompt_text: str) -> list[str]:
    cmd = [OPENCODE_BIN, 'run', prompt_text, '--dir', str(workdir.resolve()), '--format', 'json', '--auto', '--print-logs']
    if OPENCODE_MODEL:
        cmd += ['-m', OPENCODE_MODEL]
    return cmd


async def _run_opencode(workdir: Path, prompt_text: str) -> tuple[int, str]:
    return await _run(_run_opencode_cmd(workdir, prompt_text), workdir, OPENCODE_TIMEOUT)


_tasks: set[asyncio.Task] = set()


class AgentRuntimeError(RuntimeError):
    """Сбой вызова opencode: несёт код возврата и хвост вывода."""

    def __init__(self, code: int, output: str) -> None:
        self.code = code
        self.output = output
        super().__init__(f'opencode завершился с кодом {code}')


def _clean_agent_error(code: int, output: str) -> str:
    """Человекочитаемое сообщение вместо сырого дампа логов opencode."""
    if code in (-15, 143):
        return 'opencode был остановлен во время генерации (SIGTERM) — обычно это перезапуск сервиса. Запустите перегенерацию.'
    if code == -9 or code == 137:
        return 'opencode был принудительно завершён (SIGKILL) — возможна нехватка памяти на сервере. Запустите перегенерацию.'
    # из логов берём последнюю содержательную строку (не JSON-поток и не служебные поля)
    for line in reversed(output.strip().splitlines()):
        text = line.strip()
        if not text or text.startswith('timestamp=') or text.startswith('{'):
            continue
        return f'opencode завершился с кодом {code}: {text[-300:]}'
    return f'opencode завершился с кодом {code} (логов нет)'


def spawn_generation(draft_id: str, description: str | None = None) -> None:
    """Запускает генерацию в фоне; статус черновика обновляется по завершении."""
    async def _job() -> None:
        draft = db.get_skill_draft(draft_id)
        if draft is None:
            return
        # предвалидация: если схемы всех выбранных датасетов не вычитаны —
        # отказ сразу, без вызова агента (быстрый фидбек пользователю)
        items = dataset_registry.for_slugs(draft.get('datasets') or [])
        if items and all(not (d.get('schema') or []) for d in items):
            db.update_skill_draft(draft_id, status='unavailable', issues=[
                'Схемы выбранных датасетов не вычитаны — выполните «Проверить и вычитать схему» '
                'в разделе «Датасеты», затем перегенерируйте скилл.',
            ])
            return
        try:
            result = await generate_content(draft, description)
            if result['unavailable'] is not None:
                issues = [result['unavailable']['reason'], *result['unavailable']['suggestions']]
                db.update_skill_draft(draft_id, status='unavailable', issues=issues)
            else:
                db.update_skill_draft(draft_id, content=result['content'], status='draft', issues=[])
        except AgentRuntimeError as exc:
            db.update_skill_draft(draft_id, status='failed', issues=[_clean_agent_error(exc.code, exc.output)])
        except Exception as exc:
            db.update_skill_draft(draft_id, status='failed', issues=[str(exc)])

    task = asyncio.create_task(_job())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def rescue_interrupted_generations() -> None:
    """При старте бэкенда черновики с фоновыми задачами, умершими вместе
    с процессом (перезапуск/деплой), переводятся в состояние, из которого
    их можно продолжить: `generating` → `failed`, `improving` → `review`."""
    for draft in db.list_skill_drafts():
        if draft['status'] == 'generating':
            db.update_skill_draft(draft['id'], status='failed', issues=[
                'Генерация была прервана перезапуском сервиса — запустите перегенерацию.',
            ])
        elif draft['status'] == 'improving':
            db.update_skill_draft(draft['id'], status='review', issues=[
                'Исправление скилла было прервано перезапуском сервиса — '
                'запустите «Улучшить скилл» или «Проверить по правилам» заново.',
            ])


def spawn_check(draft_id: str) -> None:
    async def _job() -> None:
        draft = db.get_skill_draft(draft_id)
        if draft is None:
            return
        try:
            verdict = await check_content(draft)
            db.update_skill_draft(
                draft_id,
                status='checked' if verdict['ok'] else 'rejected',
                issues=verdict['issues'],
            )
        except AgentRuntimeError as exc:
            db.update_skill_draft(draft_id, status='rejected', issues=[_clean_agent_error(exc.code, exc.output)])
        except Exception as exc:
            db.update_skill_draft(draft_id, status='rejected', issues=[str(exc)])

    task = asyncio.create_task(_job())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def spawn_improve(draft_id: str) -> None:
    """Агент-редактор исправляет скилл по правилам, затем автоматически
    запускает повторную проверку (статус черновика на время исправления —
    `improving`, после — `review`)."""
    async def _job() -> None:
        draft = db.get_skill_draft(draft_id)
        if draft is None:
            return
        prior_status = draft['status']
        try:
            content = await improve_content(draft)
            if not content.strip():
                raise RuntimeError('агент вернул пустой скилл')
            db.update_skill_draft(draft_id, content=content, status='review', issues=[])
            spawn_check(draft_id)
        except AgentRuntimeError as exc:
            db.update_skill_draft(draft_id, status=prior_status, issues=[_clean_agent_error(exc.code, exc.output)])
        except Exception as exc:
            db.update_skill_draft(draft_id, status=prior_status, issues=[str(exc)])

    task = asyncio.create_task(_job())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
