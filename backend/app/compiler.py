import asyncio
import json
import os
import shutil
import sys
from pathlib import Path

from . import prompt
from .config import DB
from .schemas import Report
from .template_report import write_demo_script

BASE_DIR = Path(__file__).resolve().parent.parent
ARTIFACTS_DIR = BASE_DIR / 'artifacts'
SKILLS_DIR = BASE_DIR / 'skills'

OPENCODE_BIN = shutil.which('opencode') or 'opencode'
# Модель opencode для генерации report.py; при пустом значении opencode выбирает сам.
OPENCODE_MODEL = os.environ.get('OPENCODE_MODEL') or None

OPENCODE_TIMEOUT = int(os.environ.get('OPENCODE_TIMEOUT', '900'))
PYTHON_BIN = sys.executable


class CompileError(RuntimeError):
    pass


def skills_dir() -> Path:
    SKILLS_DIR.mkdir(parents=True, exist_ok=True)
    return SKILLS_DIR


def artifacts_dir() -> Path:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    return ARTIFACTS_DIR


def skill_path(name: str) -> Path:
    return skills_dir() / f'{name}.md'


async def _run(cmd: list[str], cwd: Path, timeout: int, env: dict | None = None) -> tuple[int, str]:
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=str(cwd),
        env=full_env,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise CompileError(f'процесс превысил таймаут {timeout}s: {" ".join(cmd)}')
    text = stdout.decode('utf-8', errors='replace')
    return proc.returncode or 0, text


async def _run_opencode(workdir: Path, skill_name: str, params: dict[str, str]) -> None:
    skill_file = skill_path(skill_name)
    if not skill_file.exists():
        raise CompileError(f'скилл не найден: {skill_file}')
    skill_text = skill_file.read_text(encoding='utf-8')
    prompt_text = prompt.build_prompt(skill_text, params)

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
    env = {
        'SKILL': report['skill'],
        'PERIOD': params.get('period', ''),
        'SALES_TABLE': 'sales_orders',
        'MANAGER_TABLE': 'manager_stats',
        'DATABASE_URL': os.environ.get('DATABASE_URL', DB.raw),
    }
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
    workdir = artifacts_dir() / report['id']
    workdir.mkdir(parents=True, exist_ok=True)
    # старую спеку убираем; report.py НЕ удаляем — при сбое LLM останется
    # прошлая рабочая версия (self-healing: GET пересчитает её заново)
    (workdir / 'report.spec.json').unlink(missing_ok=True)
    params = report.get('params') or {}
    generated = False

    if mode != 'demo':
        try:
            await _run_opencode(workdir, report['skill'], params)
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
    workdir = artifacts_dir() / report['id']
    if not (workdir / 'report.py').exists():
        raise CompileError('report.py отсутствует — сначала соберите отчёт')
    await _run_report_script(workdir, report)
    return _read_spec(workdir)