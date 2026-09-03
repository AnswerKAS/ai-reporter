"""Модели семантического слоя: метрики, разрезы, связи."""

from typing import Literal

from .user import CamelModel


class MetricMeta(CamelModel):
    slug: str
    title: str
    description: str | None = None
    dataset_slug: str
    expression: str
    format: Literal['number', 'money', 'percent', 'string', 'date'] = 'number'
    unit: str | None = None
    status: Literal['new', 'ok', 'error'] = 'new'
    error: str | None = None
    created_at: str
    updated_at: str


class MetricCreate(CamelModel):
    slug: str
    title: str
    description: str | None = None
    dataset_slug: str
    expression: str
    format: Literal['number', 'money', 'percent', 'string', 'date'] = 'number'
    unit: str | None = None


class MetricPatch(CamelModel):
    title: str | None = None
    description: str | None = None
    expression: str | None = None
    format: Literal['number', 'money', 'percent', 'string', 'date'] | None = None
    unit: str | None = None


class DimensionMeta(CamelModel):
    slug: str
    title: str
    description: str | None = None
    dataset_slug: str
    field: str
    type: Literal['string', 'date', 'number'] = 'string'
    created_at: str
    updated_at: str


class DimensionCreate(CamelModel):
    slug: str
    title: str
    description: str | None = None
    dataset_slug: str
    field: str
    type: Literal['string', 'date', 'number'] = 'string'


class DimensionPatch(CamelModel):
    title: str | None = None
    description: str | None = None
    field: str | None = None
    type: Literal['string', 'date', 'number'] | None = None


class LinkMeta(CamelModel):
    id: str
    title: str | None = None
    left_slug: str
    right_slug: str
    left_field: str
    right_field: str
    kind: Literal['inner', 'left'] = 'inner'
    created_at: str


class LinkCreate(CamelModel):
    title: str | None = None
    left_slug: str
    right_slug: str
    left_field: str
    right_field: str
    kind: Literal['inner', 'left'] = 'inner'
