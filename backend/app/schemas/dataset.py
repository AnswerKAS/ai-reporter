"""Модели датасетов (реестр источников данных)."""

from typing import Literal

from .user import CamelModel


class DatasetField(CamelModel):
    name: str
    type: str


class DatasetMeta(CamelModel):
    slug: str
    title: str
    description: str | None = None
    source: Literal['clickhouse', 'postgres', 'csv']
    table_name: str | None = None
    file: str | None = None
    fields: list[DatasetField] = []
    status: Literal['new', 'ok', 'error'] = 'new'
    error: str | None = None
    created_at: str
    updated_at: str


class DatasetPreview(CamelModel):
    columns: list[str] = []
    rows: list[list[str]] = []
    truncated: bool = False


class DatasetDetail(CamelModel):
    dataset: DatasetMeta
    preview: DatasetPreview | None = None


class DatasetCreate(CamelModel):
    slug: str
    title: str
    description: str | None = None
    source: Literal['clickhouse', 'postgres', 'csv']
    dsn: str = ''
    table_name: str = ''


class DatasetPatch(CamelModel):
    title: str | None = None
    description: str | None = None
    dsn: str | None = None
    table_name: str | None = None
