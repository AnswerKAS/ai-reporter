from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra='allow',
    )


def _stringify_params(v: Any) -> Any:
    """LLM-скрипты кладут в params числа (id форм и т.п.) — приводим к строкам."""
    if isinstance(v, dict):
        return {k: str(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else x for k, x in v.items()}
    return v


class NumberFormat(str, Enum):
    STRING = 'string'
    NUMBER = 'number'
    MONEY = 'money'
    PERCENT = 'percent'
    DATE = 'date'


class KpiItem(CamelModel):
    label: str
    value: str | int | float
    format: NumberFormat | None = None
    delta: float | None = None
    delta_good_when_up: bool | None = None
    hint: str | None = None


class KpiSection(CamelModel):
    type: Literal['kpi']
    items: list[KpiItem]


class ChartPoint(CamelModel):
    pass


class ChartSeries(CamelModel):
    key: str
    name: str | None = None
    color: str | None = None
    type: Literal['bar', 'line'] | None = None


class ChartSection(CamelModel):
    type: Literal['chart']
    kind: Literal['bar', 'line', 'area', 'pie', 'combo']
    title: str | None = None
    data: list[ChartPoint]
    x_key: str | None = None
    series: list[ChartSeries]
    detail: 'ChartSectionDetail | None' = None


class TableColumn(CamelModel):
    key: str
    header: str
    format: NumberFormat | None = None


class ChartSectionDetail(CamelModel):
    title: str | None = None
    columns: list[TableColumn] = []
    rows_by: dict[str, list[dict[str, Any]]] = {}


class TableSection(CamelModel):
    type: Literal['table']
    title: str | None = None
    columns: list[TableColumn]
    rows: list[dict[str, Any]]


class MarkdownSection(CamelModel):
    type: Literal['markdown']
    content: str


ReportSection = Annotated[
    Union[MarkdownSection, KpiSection, ChartSection, TableSection],
    Field(discriminator='type'),
]


class ReportFilter(CamelModel):
    key: str
    label: str
    kind: Literal['select', 'number', 'text'] = 'select'
    options: list[str] = []
    default: str | int | None = None


class Report(CamelModel):
    id: str
    slug: str
    title: str
    description: str | None = None
    skill: str | None = None
    created_at: str
    updated_at: str
    params: dict[str, str] | None = None
    _stringify = field_validator('params', mode='before')(_stringify_params)
    filters: list[ReportFilter] | None = None
    sections: list[ReportSection]


class ReportMeta(CamelModel):
    id: str
    slug: str
    title: str
    description: str | None = None
    skill: str | None = None
    status: str
    error: str | None = None
    created_at: str
    updated_at: str
    params: dict[str, str] | None = None
    filter_values: dict[str, str] | None = None


class ReportPatch(CamelModel):
    slug: str | None = None
    title: str | None = None
    description: str | None = None
    skill: str
    params: dict[str, str] | None = None
    mode: Literal['auto', 'demo', 'llm'] = 'auto'


class ReportUpdate(CamelModel):
    """Правка опубликованного отчёта: название/описание — любой с доступом,
    скилл и режим сборки — только админ (все поля опциональны)."""

    title: str | None = None
    description: str | None = None
    skill: str | None = None
    mode: Literal['auto', 'demo', 'llm'] | None = None


class FiltersPatch(CamelModel):
    values: dict[str, str]


class RecompilePatch(CamelModel):
    mode: Literal['auto', 'demo', 'llm'] = 'llm'