import asyncio
import json
import os
import shutil
import sys
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

OPENCODE_TIMEOUT = int(os.environ.get('OPENCODE_TIMEOUT', '900'))
PYTHON_BIN = sys.executable


class CompileError(RuntimeError):
    pass


def skills_dir() -> Path:
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    return SKILLS_DIR


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
    """Датасеты, объявленные секцией '## Датасеты' скилла (без секции — все)."""
    return dataset_registry.for_slugs(dataset_registry.parse_skill_datasets(skill_text))


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


async def _run(cmd: list[str], cwd: Path, timeout: int, env: dict | None = None) -> tuple[int, str]:
    full_env = os.environ.copy()
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
        )
    except FileNotFoundError as exc:
        raise CompileError(f'исполняемый файл не найден: {cmd[0]} ({exc})') from exc
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise CompileError(f'процесс превысил таймаут {timeout}s: {" ".join(cmd)}')
    text = stdout.decode('utf-8', errors='replace')
    return proc.returncode or 0, text


async def _run_opencode(workdir: Path, skill_name: str, params: dict[str, str], skill_text: str) -> None:
    datasets = _skill_datasets(skill_text)
    _write_datasets_json(workdir, datasets)
    prompt_text = prompt.build_prompt(skill_text, params, datasets)

    cmd = [
        OPENCODE_BIN, 'run', prompt_text,
        '--dir', str(workdir.resolve()),  # абсолютный путь: opencode кладёт файлы сюда
        '--format', 'json', '--auto', '--print-logs',
    ]
    if OPENCODE_MODEL:
        cmd += ['-m', OPENCODE_MODEL]

    code, output = await _run(cmd, workdir, OPENCODE_TIMEOUT)
    if code != 0:
        tail = output[-2000:]
        raise CompileError(f'opencode завершился с кодом {code}:\n{tail}')


async def _run_report_script(workdir: Path, report: dict) -> None:
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
    code, output = await _run(
        [PYTHON_BIN, str(script), '--output', 'report.spec.json'],
        workdir,
        timeout=120,
        env=env,
    )
    if code != 0:
        tail = output[-2000:]
        raise CompileError(f'report.py завершился с ошибкой:\n{tail}')


def _read_spec(workdir: Path) -> dict:
    """Читает спеку, валидирует и удаляет файл — спека хранится только в БД."""
    spec_file = workdir / 'report.spec.json'
    if not spec_file.exists():
        raise CompileError('report.spec.json не создан')
    raw = json.loads(spec_file.read_text(encoding='utf-8'))
    spec = Report.model_validate(raw).model_dump(by_alias=True)
    spec_file.unlink(missing_ok=True)
    return spec


async def compile_report(report: dict, mode: str = 'auto') -> dict:
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

    await _run_report_script(workdir, report)
    return _read_spec(workdir)


async def refresh_report(report: dict) -> dict:
    workdir = report_workdir(report['id'])
    if not (workdir / 'report.py').exists():
        raise CompileError('report.py отсутствует — сначала соберите отчёт')
    await _run_report_script(workdir, report)
    return _read_spec(workdir)