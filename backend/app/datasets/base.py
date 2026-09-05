"""Базовый интерфейс адаптера источника данных."""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass


class DatasetError(RuntimeError):
    """Ошибка подключения или чтения датасета (текст безопасно показывать в UI)."""


# --- маскирование секретов в текстах ошибок -------------------------------

_URL_RE = re.compile(r'\b([a-zA-Z][a-zA-Z0-9+.-]*)://[^\s"\']+', re.IGNORECASE)
_CONNINFO_RE = re.compile(r'\b(password|user|host|hostname|dbname|database|port)\s*=\s*\S+', re.IGNORECASE)
_SERVER_AT_RE = re.compile(r'(to server at\s+)"([^"]*)"', re.IGNORECASE)
_FOR_USER_RE = re.compile(r'(for user\s+)"([^"]*)"', re.IGNORECASE)
_RESOLVE_HOST_RE = re.compile(r"(resolve host\s+)'([^']+)'", re.IGNORECASE)
_HOST_QUOTED_RE = re.compile(r'\b(host\s+)"([^"\n]+)"', re.IGNORECASE)
_IPV4_RE = re.compile(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b')


def _mask_quoted(match: re.Match) -> str:
    inner = match.group(2)
    if '://' in inner or '@' in inner:
        return f'{match.group(1)}"***"'
    return match.group(0)


_QUOTED_RE = re.compile(r'([=(]\s*)"([^"\n]*)"', re.IGNORECASE)


def sanitize_error(text: str) -> str:
    """Убирает из текста ошибки DSN, логины, пароли и адреса серверов."""
    out = _URL_RE.sub(lambda m: f'{m.group(1)}://***', text)
    out = _CONNINFO_RE.sub(lambda m: f"{m.group(1)}=***", out)
    out = _SERVER_AT_RE.sub(r'\1"***"', out)
    out = _FOR_USER_RE.sub(r'\1"***"', out)
    out = _RESOLVE_HOST_RE.sub(r"\1'***'", out)
    out = _HOST_QUOTED_RE.sub(r'\1"***"', out)
    out = _IPV4_RE.sub('***', out)
    out = _QUOTED_RE.sub(_mask_quoted, out)
    return out


@dataclass
class DatasetField:
    name: str
    type: str
    # комментарий колонки в источнике: единственное место, где смысл поля
    # описан теми, кто владеет данными, — тянем его как есть
    comment: str = ''

    def as_dict(self) -> dict:
        return {'name': self.name, 'type': self.type, 'comment': self.comment}


class DatasetAdapter(ABC):
    """Доступ к источнику одного датасета (таблица или файл)."""

    @abstractmethod
    def test_connection(self) -> None:
        """Проверяет доступность источника; бросает DatasetError при сбое."""

    @abstractmethod
    def fetch_schema(self) -> list[DatasetField]:
        """Возвращает поля источника (имя + тип)."""

    @abstractmethod
    def sample_rows(self, limit: int = 50) -> tuple[list[str], list[list]]:
        """Превью: (заголовки колонок, строки). Не более limit строк."""

    @abstractmethod
    def run_query(self, sql: str, params: dict | None = None) -> tuple[list[str], list[list]]:
        """Выполняет SELECT, собранный построителем запросов.

        SQL приходит только из семантического слоя (выражения метрик пишет
        админ); значения пользователя передаются параметрами.
        """

    @abstractmethod
    def quoted_table(self, table: str) -> str:
        """Имя таблицы, процитированное по правилам источника."""

    def source_sql(self, alias: str = '') -> str:
        """Выражение источника для FROM: имя таблицы или подзапрос.

        Алиас даёт вызывающий, а не адаптер: подзапрос в FROM без алиаса в
        PostgreSQL до 16-й версии — синтаксическая ошибка, а из пяти мест,
        которые строят FROM, алиас нумерует только построитель секции.

        ВАЖНО: результат предназначен ТОЛЬКО для run_query(). В PostgreSQL
        в нём удвоены '%' — их схлопывает разбор параметров psycopg.
        """
        return self.quoted_table('')

    def close(self) -> None:
        """Освобождает переиспользуемое соединение (если оно есть)."""
