from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra='allow',
    )


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


class ChartSection(CamelModel):
    type: Literal['chart']
    kind: Literal['bar', 'line', 'area', 'pie']
    title: str | None = None
    data: list[ChartPoint]
    x_key: str | None = None
    series: list[ChartSeries]


class TableColumn(CamelModel):
    key: str
    header: str
    format: NumberFormat | None = None


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


class FiltersPatch(CamelModel):
    values: dict[str, str]


# --- auth / admin -------------------------------------------------------

class UserPublic(CamelModel):
    id: str
    username: str
    role: Literal['admin', 'user']
    created_at: str


class LoginPatch(CamelModel):
    username: str
    password: str


class UserPatch(CamelModel):
    username: str
    password: str
    role: Literal['admin', 'user'] = 'user'


class PasswordPatch(CamelModel):
    password: str


class GroupPatch(CamelModel):
    name: str


class MemberPatch(CamelModel):
    user_id: str


class AccessPatch(CamelModel):
    report_slug: str
    user_id: str | None = None
    group_id: str | None = None


class RecompilePatch(CamelModel):
    mode: Literal['auto', 'demo', 'llm'] = 'llm'