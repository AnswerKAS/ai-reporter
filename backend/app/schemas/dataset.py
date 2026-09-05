"""Модели датасетов (реестр источников данных)."""

from typing import Literal

from .user import CamelModel


class DatasetField(CamelModel):
    name: str
    type: str
    comment: str | None = None


class DatasetMeta(CamelModel):
    slug: str
    title: str
    description: str | None = None
    source: Literal['clickhouse', 'postgres', 'oracle', 'csv']
    table_name: str | None = None
    # текст запроса отдаётся только админу; остальным виден лишь признак is_query
    query: str | None = None
    is_query: bool = False
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
    # замечания к запросу-источнику (LIMIT внутри, ORDER BY, SETTINGS)
    notes: list[str] = []


class DatasetCreate(CamelModel):
    slug: str
    title: str
    description: str | None = None
    source: Literal['clickhouse', 'postgres', 'oracle', 'csv']
    dsn: str = ''
    table_name: str = ''
    query: str = ''


class DatasetPatch(CamelModel):
    title: str | None = None
    description: str | None = None
    dsn: str | None = None
    table_name: str | None = None
    query: str | None = None


class DimensionSuggestion(CamelModel):
    slug: str
    title: str
    field: str
    type: Literal['string', 'date', 'number'] = 'string'
    column: str = ''
    column_type: str = ''
    exists: bool = False
    selected: bool = True


class MetricSuggestion(CamelModel):
    slug: str
    title: str
    expression: str
    format: Literal['number', 'money', 'percent', 'string', 'date'] = 'number'
    unit: str | None = None
    column: str = ''
    column_type: str = ''
    exists: bool = False
    selected: bool = True


class DatasetSuggestions(CamelModel):
    dimensions: list[DimensionSuggestion] = []
    metrics: list[MetricSuggestion] = []
    notes: list[str] = []


class DimensionSelection(CamelModel):
    slug: str
    title: str
    field: str
    type: Literal['string', 'date', 'number'] = 'string'


class MetricSelection(CamelModel):
    slug: str
    title: str
    expression: str
    format: Literal['number', 'money', 'percent', 'string', 'date'] = 'number'
    unit: str | None = None


class DatasetSemanticSelection(CamelModel):
    dimensions: list[DimensionSelection] = []
    metrics: list[MetricSelection] = []


class SemanticFailure(CamelModel):
    slug: str
    error: str


class DatasetSemanticResult(CamelModel):
    created_dimensions: int = 0
    created_metrics: int = 0
    skipped: list[str] = []
    failed: list[SemanticFailure] = []
