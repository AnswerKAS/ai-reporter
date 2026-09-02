import asyncio
import json
import os
import shutil
import signal
import sys
import uuid
from pathlib import Path

from ..core.config import DB, BASE_DIR
from ..schemas.report import Report
from . import prompt
from . import storage
from .template_report import write_demo_script
from ..datasets import registry as dataset_registry

SKILLS_DIR = BASE_DIR / 'skills'

def _find_opencode() -> str:
    """Бинарник opencode: PATH, затем типовые каталоги установки."""
    found = shutil.which('opencode')
    if found:
        return found
    for candidate in (
        Path.home() / '.opencode' / 'bin' / 'opencode',
        Path('/usr/local/bin/opencode'),
        Path('/opt/homebrew/bin/opencode'),
    ):
        if candidate.is_file():
            return str(candidate)
    return 'opencode'  # упадёт с FileNotFoundError → fallback на demo


OPENCODE_BIN = _find_opencode()
# Модель opencode для генерации report.py; при пустом значении opencode выбирает сам.
OPENCODE_MODEL = os.environ.get('OPENCODE_MODEL') or None
# Резервная модель: при таймауте/stall основной модели попытка делается ей
# (провайдеры бывают неработоспособны с конкретных IP — glm через OpenRouter
# на VPS зависает после step_start, deepseek работает).
OPENCODE_FALLBACK_MODEL = os.environ.get('OPENCODE_FALLBACK_MODEL') or None

OPENCODE_TIMEOUT = int(os.environ.get('OPENCODE_TIMEOUT', '900'))
# Черновики скиллов (generate/check/improve): короче — зависание не должно
# держать пользователя 15 минут. Watchdog черновиков считает от этого значения.
OPENCODE_DRAFT_TIMEOUT = int(os.environ.get('OPENCODE_DRAFT_TIMEOUT', '180'))
# Столько секунд без единого байта в stdout считаем зависанием агента.
OPENCODE_STALL_TIMEOUT = int(os.environ.get('OPENCODE_STALL_TIMEOUT', '120'))
PYTHON_BIN = sys.executable


# Системные переменные, без которых не стартует Python и не работает TLS.
_SYSTEM_ENV_KEYS = (
    'PATH', 'HOME', 'LANG', 'LC_ALL', 'TZ', 'TMPDIR',
    'PYTHONPATH', 'PYTHONHOME', 'PYTHONIOENCODING',
    'SSL_CERT_FILE', 'SSL_CERT_DIR', 'REQUESTS_CA_BUNDLE',
)
# Настройки, которые читают сами скрипты отчётов: режим TLS для ClickHouse
# (демо-скрипт и производные от него) и переопределения имён таблиц
# (SALES_TABLE, MANAGER_TABLE и заданные оператором в .env — суффикс _TABLE).
_REPORT_ENV_KEYS = ('CLICKHOUSE_SECURE',)
_REPORT_ENV_SUFFIXES = ('_TABLE',)


def _report_env() -> dict[str, str]:
    """Окружение для сгенерированного report.py: системный минимум плюс его
    собственные настройки. Креды метабазы приложения (PG*) и токены
    провайдеров скрипту не нужны и не передаются."""
    picked = {k: os.environ[k] for k in (*_SYSTEM_ENV_KEYS, *_REPORT_ENV_KEYS) if k in os.environ}
    picked.update({
        k: v for k, v in os.environ.items()
        if k.endswith(_REPORT_ENV_SUFFIXES)
    })
    return picked


class CompileError(RuntimeError):
    pass


def skills_dir() -> Path:
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    return SKILLS_DIR


# Пересчёты одного отчёта сериализуются: каталог артефактов общий, а GET
# (фронт опрашивает раз в 15с), /filters и /refresh могут прийти одновременно.
_report_locks: dict[str, asyncio.Lock] = {}


def _report_lock(report_id: str) -> asyncio.Lock:
    lock = _report_locks.get(report_id)
    if lock is None:
        lock = asyncio.Lock()
        _report_locks[report_id] = lock
    return lock


def report_workdir(report_id: str) -> Path:
    """Каталог артефактов отчёта (через фасад хранилища)."""
    workdir = storage.path('report', report_id, 'report.py').parent
    workdir.mkdir(parents=True, exist_ok=True)
    return workdir


def has_report_script(report_id: str) -> bool:
    return storage.exists('report', report_id, 'report.py')


def list_skill_files() -> list[Path]:
    """Все скилл-файлы рекурсивно; служебные (с `_` в пути) исключены."""
    return [
        p for p in sorted(skills_dir().rglob('*.md'))
        if not any(part.startswith('_') for part in p.relative_to(SKILLS_DIR).parts)
    ]


def skill_path(name: str) -> Path:
    if '..' in Path(name).parts or Path(name).is_absolute():
        raise CompileError(f'некорректное имя скилла: {name}')
    return skills_dir() / f'{name}.md'


def _skill_datasets(skill_text: str) -> list[dict]:
    """Датасеты, объявленные секцией '## Датасеты' скилла.

    Секция обязательна: без неё сборка падает с понятной ошибкой — иначе
    отчёт молча строится по всем датасетам реестра (лишние таблицы,
    нерелевантные данные). Секция есть, но пустая — то же самое.
    """
    slugs = dataset_registry.parse_skill_datasets(skill_text)
    if slugs is None or not slugs:
        raise CompileError(
            'в скилле нет секции «## Датасеты: <slug>, ...» — укажите, какие датасеты '
            'использует отчёт (slug\'и из реестра), и перекомпилируйте отчёт'
        )
    known = {d['slug'] for d in dataset_registry.list_all()}
    unknown = [s for s in slugs if s not in known]
    if unknown:
        raise CompileError(f'в реестре нет датасетов: {", ".join(unknown)} — исправьте секцию «## Датасеты»')
    return dataset_registry.for_slugs(slugs)


def _datasets_meta(datasets: list[dict]) -> list[dict]:
    """Мета для промпта и datasets.json (без секретов)."""
    meta = []
    for d in datasets:
        meta.append({
            'slug': d['slug'],
            'title': d['title'],
            'description': d.get('description') or '',
            'source': d['source'],
            'table': d.get('table_name') or '',
            'file': str(dataset_registry.csv_path(d['slug'])) if d['source'] == 'csv' else '',
            'fields': d.get('schema') or [],
        })
    return meta


def _write_datasets_json(workdir: Path, datasets: list[dict]) -> None:
    (workdir / 'datasets.json').write_text(
        json.dumps(_datasets_meta(datasets), ensure_ascii=False, indent=2),
        encoding='utf-8',
    )


async def _run(
    cmd: list[str],
    cwd: Path,
    timeout: int,
    env: dict | None = None,
    *,
    stall_timeout: int | None = None,
    proc_slot: dict | None = None,
    inherit_env: bool = True,
) -> tuple[int, str]:
    """Запускает процесс; при таймауте или молчании (stall_timeout) убивает
    всё дерево процессов (opencode порождает детей — kill оставлял их жить
    и ломал следующие запуски). proc_slot — куда положить Process для отмены.

    inherit_env=False отдаёт процессу только системный минимум и явный env
    (для сгенерированных report.py: креды метабазы приложения им не нужны).
    """
    full_env = os.environ.copy() if inherit_env else _report_env()
    if env:
        full_env.update(env)
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(cwd),
            env=full_env,
            # opencode может ждать ввод при открытом stdin — всегда отрезаем
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            # своя группа процессов: killpg убивает и детей opencode
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        raise CompileError(f'исполняемый файл не найден: {cmd[0]} ({exc})') from exc
    if proc_slot is not None:
        proc_slot['proc'] = proc

    def _kill_tree() -> None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            try:
                proc.kill()
            except ProcessLookupError:
                pass

    chunks: list[bytes] = []

    class _Stall(Exception):
        pass

    async def _pump() -> None:
        while True:
            try:
                if stall_timeout is None:
                    chunk = await proc.stdout.read(8192)
                else:
                    chunk = await asyncio.wait_for(proc.stdout.read(8192), timeout=stall_timeout)
            except asyncio.TimeoutError:
                # молчание дольше stall_timeout — это зависание агента, а не
                # превышение общего таймаута: разводим случаи по разным веткам
                raise _Stall from None
            if not chunk:
                return
            chunks.append(chunk)

    pump = asyncio.create_task(_pump())

    def _tail(limit: int = 1200) -> str:
        return b''.join(chunks).decode('utf-8', errors='replace')[-limit:]

    try:
        await asyncio.wait_for(asyncio.shield(pump), timeout=timeout)
    except asyncio.TimeoutError:
        _kill_tree()
        raise CompileError(
            f'процесс превысил таймаут {timeout}s: {" ".join(cmd[:2])}\n--- последний вывод ---\n{_tail()}'
        ) from None
    except _Stall:
        _kill_tree()
        try:
            await asyncio.wait_for(asyncio.shield(pump), timeout=5)
        except (Exception, asyncio.CancelledError):
            pump.cancel()
        raise CompileError(
            f'агент не проявлял активности {stall_timeout}s — остановлен как зависший: {" ".join(cmd[:2])}'
            f'\n--- последний вывод ---\n{_tail()}'
        ) from None
    finally:
        if proc_slot is not None and proc_slot.get('proc') is proc:
            proc_slot.pop('proc', None)
    rc = await proc.wait()
    text = b''.join(chunks).decode('utf-8', errors='replace')
    return rc or 0, text


def _opencode_cmd(workdir: Path, prompt_text: str, model: str | None) -> list[str]:
    cmd = [
        OPENCODE_BIN, 'run', prompt_text,
        '--dir', str(workdir.resolve()),  # абсолютный путь: opencode кладёт файлы сюда
        '--format', 'json', '--auto', '--print-logs',
    ]
    if model:
        cmd += ['-m', model]
    return cmd


async def _run_opencode(workdir: Path, skill_name: str, params: dict[str, str], skill_text: str) -> None:
    datasets = _skill_datasets(skill_text)
    _write_datasets_json(workdir, datasets)
    prompt_text = prompt.build_prompt(skill_text, params, datasets)

    # stall-детекция и для генерации отчётов: молчание агента не должно
    # съедать весь таймаут — fallback на демо сработает быстрее
    try:
        code, output = await _run(
            _opencode_cmd(workdir, prompt_text, OPENCODE_MODEL),
            workdir, OPENCODE_TIMEOUT, stall_timeout=OPENCODE_STALL_TIMEOUT,
        )
    except CompileError:
        if not OPENCODE_FALLBACK_MODEL:
            raise
        print(f'[compiler] модель {OPENCODE_MODEL} не сработала, повторяю с {OPENCODE_FALLBACK_MODEL}')
        code, output = await _run(
            _opencode_cmd(workdir, prompt_text, OPENCODE_FALLBACK_MODEL),
            workdir, OPENCODE_TIMEOUT, stall_timeout=OPENCODE_STALL_TIMEOUT,
        )
    if code != 0:
        tail = output[-2000:]
        raise CompileError(f'opencode завершился с кодом {code}:\n{tail}')


async def _run_report_script(workdir: Path, report: dict) -> Path:
    """Запускает report.py и возвращает путь к записанной спеке.

    Имя файла уникально для каждого запуска: параллельные пересчёты одного
    отчёта делят workdir и на общем report.spec.json затирали друг друга.
    """
    script = workdir / 'report.py'
    if not script.exists():
        raise CompileError('report.py не создан')
    params = report.get('params') or {}

    # датасеты, привязанные к скиллу (файл читает и демо-скрипт, и LLM-скрипт)
    skill_file = skill_path(report['skill'])
    datasets = _skill_datasets(skill_file.read_text(encoding='utf-8')) if skill_file.exists() else []
    _write_datasets_json(workdir, datasets)

    env = {
        'SKILL': report['skill'],
        'PERIOD': params.get('period', ''),
        'SALES_TABLE': 'sales_orders',
        'MANAGER_TABLE': 'manager_stats',
        'DATABASE_URL': os.environ.get('DATABASE_URL', DB.raw),
    }
    # DSN каждого датасета → DATASET_<SLUG>_DSN (для скриптов с произвольными источниками)
    for d in datasets:
        try:
            resolved = dataset_registry.resolve_dataset_dsn(d)
        except Exception:
            continue  # DSN не резолвится (не задан/невалиден) — скрипт узнает из samples
        if resolved:
            env[f"DATASET_{d['slug'].upper()}_DSN"] = resolved
    for key, value in (report.get('filter_values') or {}).items():
        if value:
            env[f'FILTER_{key.upper()}'] = str(value)
    spec_name = f'report.spec.{uuid.uuid4().hex}.json'
    code, output = await _run(
        [PYTHON_BIN, str(script), '--output', spec_name],
        workdir,
        timeout=120,
        env=env,
        inherit_env=False,
    )
    if code != 0:
        (workdir / spec_name).unlink(missing_ok=True)
        tail = output[-2000:]
        raise CompileError(f'report.py завершился с ошибкой:\n{tail}')
    return workdir / spec_name


def _read_spec(spec_file: Path) -> dict:
    """Читает спеку, валидирует и удаляет файл — спека хранится только в БД."""
    if not spec_file.exists():
        raise CompileError(f'{spec_file.name} не создан')
    try:
        raw = json.loads(spec_file.read_text(encoding='utf-8'))
        return Report.model_validate(raw).model_dump(by_alias=True)
    finally:
        spec_file.unlink(missing_ok=True)


async def compile_report(report: dict, mode: str = 'auto') -> dict:
    async with _report_lock(report['id']):
        return await _compile_report(report, mode)


async def _compile_report(report: dict, mode: str) -> dict:
    workdir = report_workdir(report['id'])
    workdir.mkdir(parents=True, exist_ok=True)
    # старую спеку убираем; report.py НЕ удаляем — при сбое LLM останется
    # прошлая рабочая версия (self-healing: GET пересчитает её заново)
    (workdir / 'report.spec.json').unlink(missing_ok=True)
    params = report.get('params') or {}

    skill_file = skill_path(report['skill'])
    if not skill_file.exists():
        raise CompileError(f'скилл не найден: {skill_file}')
    skill_text = skill_file.read_text(encoding='utf-8')
    # единый шаблон: скилл, не прошедший валидацию, не доходит до генерации
    from .skill_template import validate_skill_template
    validate_skill_template(skill_text)
    datasets = _skill_datasets(skill_text)
    _write_datasets_json(workdir, datasets)
    generated = False

    if mode != 'demo':
        try:
            await _run_opencode(workdir, report['skill'], params, skill_text)
            generated = (workdir / 'report.py').exists()
        except CompileError as exc:
            if mode == 'llm':
                raise
            print(f'[compiler] opencode не сработал ({exc}), переходим на демо-скрипт')

    if not generated:
        write_demo_script(
            workdir,
            report_id=report['id'],
            slug=report['slug'],
            title=report['title'],
            description=report.get('description'),
            skill=report['skill'],
            params=params,
        )

    return _read_spec(await _run_report_script(workdir, report))


async def refresh_report(report: dict) -> dict:
    async with _report_lock(report['id']):
        workdir = report_workdir(report['id'])
        if not (workdir / 'report.py').exists():
            raise CompileError('report.py отсутствует — сначала соберите отчёт')
        return _read_spec(await _run_report_script(workdir, report))