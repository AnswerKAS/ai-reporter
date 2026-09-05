"""Фасад хранилища артефактов: файлы CSV-датасетов.

Сейчас артефакты лежат на диске (режим local, каталог из env ARTIFACTS_DIR,
по умолчанию backend/artifacts — лэйаут сохранён, поэтому загруженные CSV
работают без миграции). При переносе на S3 (ARTIFACTS_STORAGE=s3) достаточно
добавить реализацию с тем же интерфейсом: path/materialize будут выгружать
файлы во временный каталог, а каноничным хранилищем станет бакет.
"""

import os
import shutil
from pathlib import Path

from ..core.config import BASE_DIR

MODE = os.environ.get('ARTIFACTS_STORAGE', 'local').strip().lower() or 'local'

LOCAL_BASE = Path(os.environ.get('ARTIFACTS_DIR', '').strip() or (BASE_DIR / 'artifacts'))

# kind → подкаталог внутри базы; владелец — каталог внутри него
_SUBDIRS = {
    'csv': 'datasets',      # <base>/datasets/<slug>/data.csv
}


def _owner_dir(kind: str, owner_id: str) -> Path:
    if MODE == 'local':
        subdir = _SUBDIRS.get(kind)
        if subdir is None:
            raise ValueError(f'неизвестный вид артефактов: {kind}')
        return LOCAL_BASE / subdir / owner_id
    raise RuntimeError(f'режим хранилища {MODE!r} пока не реализован')


def path(kind: str, owner_id: str, name: str) -> Path:
    """Путь к файлу артефакта (в local-режиме это и есть каноничное место)."""
    return _owner_dir(kind, owner_id) / name


def exists(kind: str, owner_id: str, name: str) -> bool:
    return path(kind, owner_id, name).is_file()


def save_bytes(kind: str, owner_id: str, name: str, data: bytes) -> Path:
    target = path(kind, owner_id, name)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def save_text(kind: str, owner_id: str, name: str, text: str) -> Path:
    return save_bytes(kind, owner_id, name, text.encode('utf-8'))


def load_bytes(kind: str, owner_id: str, name: str) -> bytes:
    return path(kind, owner_id, name).read_bytes()


def load_text(kind: str, owner_id: str, name: str) -> str:
    return load_bytes(kind, owner_id, name).decode('utf-8')


def delete(kind: str, owner_id: str, name: str) -> None:
    path(kind, owner_id, name).unlink(missing_ok=True)


def delete_owner(kind: str, owner_id: str) -> None:
    """Удаляет весь каталог артефактов владельца (например, CSV-датасет)."""
    owner = _owner_dir(kind, owner_id)
    if owner.is_dir():
        shutil.rmtree(owner, ignore_errors=True)


def materialize(kind: str, owner_id: str, name: str, target: Path) -> Path:
    """Гарантирует файл на диске по указанному пути.

    В local-режиме файл уже там — возвращает его путь (target игнорируется,
    если совпадает). В S3-режиме будет выгружать объект в target.
    """
    source = path(kind, owner_id, name)
    if not source.is_file():
        raise FileNotFoundError(f'артефакт не найден: {source}')
    if source.resolve() == target.resolve():
        return source
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return target
