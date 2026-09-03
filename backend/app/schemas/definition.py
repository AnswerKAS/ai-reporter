"""Декларация отчёта: что показать, а не как посчитать.

Отчёт-конструктор хранится как этот документ. Как считать — знает
семантический слой (метрики и разрезы), как выполнить — построитель запросов.
Отсюда и главное свойство: отчёт можно версионировать, диффать и править
руками, потому что это данные, а не код.
"""

from typing import Literal

from pydantic import field_validator

from .report import CamelModel

GRAINS = Literal['day', 'week', 'month', 'quarter', 'year']


class SectionDefinition(CamelModel):
    type: Literal['kpi', 'chart', 'table']
    title: str | None = None
    # только для type='chart'
    kind: Literal['bar', 'line', 'area', 'pie', 'combo'] | None = None
    metrics: list[str]
    by: list[str] = []
    grain: GRAINS | None = None
    order_by: str | None = None
    order_dir: Literal['asc', 'desc'] = 'desc'
    limit: int | None = None

    @field_validator('order_dir', mode='before')
    @classmethod
    def _order_dir_default(cls, value):
        """null от генератора декларации — это «не указано», а не ошибка."""
        return value or 'desc'

    @field_validator('metrics', 'by', mode='before')
    @classmethod
    def _list_default(cls, value):
        return value or []


class ReportField(CamelModel):
    """Поле, заведённое автором отчёта прямо из колонки датасета.

    Нужно, когда в общем словаре поля ещё нет, а отчёт нужен сейчас:
    заводить показатель на всех — право админа, а взять колонку себе в
    отчёт может любой. Пользователь выбирает колонку из схемы и действие
    из списка — произвольного SQL здесь нет и быть не может, имя колонки
    сверяется со схемой датасета в построителе.

    Живёт внутри отчёта: на общий словарь не влияет, поэтому «Выручка»
    для всех остальных не меняет смысл.
    """

    key: str
    title: str
    dataset_slug: str
    field: str
    role: Literal['metric', 'dimension'] = 'metric'
    agg: Literal['sum', 'count', 'count_distinct', 'avg', 'min', 'max'] | None = None
    type: Literal['string', 'date', 'number'] = 'string'
    format: Literal['number', 'money', 'percent'] = 'number'


class ComputedField(CamelModel):
    """Поле, собранное пользователем из уже выбранных показателей.

    SQL здесь не пишут: выбираются два показателя и действие, выражение
    собирает построитель. Поэтому «своё поле» физически не может обратиться
    к чему-то за пределами словаря — правило «SQL только у админов»
    остаётся в силе. Живёт внутри отчёта и в общий словарь не попадает:
    это частная выкладка автора, а не общее определение.
    """

    key: str
    title: str
    left: str
    op: Literal['+', '-', '*', '/']
    right: str
    format: Literal['number', 'money', 'percent'] = 'number'


class FilterDefinition(CamelModel):
    dimension: str
    label: str | None = None
    kind: Literal['select', 'text', 'number'] = 'select'


class ReportDefinition(CamelModel):
    sections: list[SectionDefinition]
    filters: list[FilterDefinition] = []
    fields: list[ReportField] = []
    computed: list[ComputedField] = []
