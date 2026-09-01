"""Базовый интерфейс адаптера источника данных."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


class DatasetError(RuntimeError):
    """Ошибка подключения или чтения датасета (текст безопасно показывать в UI)."""


@dataclass
class DatasetField:
    name: str
    type: str

    def as_dict(self) -> dict:
        return {'name': self.name, 'type': self.type}


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
