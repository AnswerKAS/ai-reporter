"""Декларация отчёта: что показать, а не как посчитать.

Отчёт-конструктор хранится как этот документ. Как считать — знает
семантический слой (метрики и разрезы), как выполнить — построитель запросов.
Отсюда и главное свойство: отчёт можно версионировать, диффать и править
руками, потому что это данные, а не код.
"""

from typing import Literal

from pydantic import field_validator, model_validator

from .report import CamelModel

GRAINS = Literal['day', 'week', 'month', 'quarter', 'year']

# Потолок группировки. Пять разрезов — это уже таблица, которую читают
# глазами по строкам; дальше растёт число групп, а не понимание.
MAX_GROUP_BY = 5
# В графике второй разрез разворачивается в серии, третьему места нет:
# линию на каждую пару значений всё равно не прочитать.
MAX_CHART_BY = 2


# Сколько секций встаёт в один ряд: 1 — во всю ширину, 2 — половина.
# Не задано — ширина по виду секции: график половинный, карточки и таблица
# во всю ширину (у таблицы колонки, и половина превращает их в переносы).
PER_ROW_DEFAULT = {'chart': 2, 'kpi': 1, 'table': 1}


class SectionDefinition(CamelModel):
    type: Literal['kpi', 'chart', 'table']
    title: str | None = None
    # только для type='chart'
    kind: Literal['bar', 'line', 'area', 'pie', 'combo'] | None = None
    per_row: Literal[1, 2] | None = None
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

    @property
    def row_width(self) -> int:
        """Сколько таких секций помещается в ряд (1 — во всю ширину)."""
        return self.per_row or PER_ROW_DEFAULT.get(self.type, 1)

    @model_validator(mode='after')
    def _check_group_by(self):
        """Разрезы: без дублей и в пределах, которые секция способна показать."""
        seen: list[str] = []
        for slug in self.by:
            if slug not in seen:
                seen.append(slug)
        if self.type == 'kpi':
            # карточка показывает одно число: разрез ей показать негде
            seen = []
        limit = MAX_CHART_BY if self.type == 'chart' else MAX_GROUP_BY
        if len(seen) > limit:
            what = 'графике' if self.type == 'chart' else 'секции'
            raise ValueError(
                f'в {what} допустимо не более {limit} разрезов группировки, выбрано {len(seen)}'
            )
        self.by = seen
        return self


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
    """Фильтр отчёта.

    `daterange` — период «с — по» по разрезу-дате: читателю отчётности нужен
    интервал, а список всех дат в выпадающем списке бесполезен. Значения
    приходят двумя ключами: `<разрез>__from` и `<разрез>__to`, пустая
    граница означает «без ограничения».
    """

    dimension: str
    label: str | None = None
    kind: Literal['select', 'text', 'number', 'daterange'] = 'select'


class ReportDefinition(CamelModel):
    """Отчёт целиком.

    `drilldown` включает детализацию: читатель открывает сырые строки
    источника — и кнопкой по датасету, и щелчком по карточке, точке графика
    или строке таблицы. Это доступ к данным без агрегата, поэтому включает
    его автор отчёта осознанно, а не система по умолчанию.
    """

    drilldown: bool = False
    sections: list[SectionDefinition]
    filters: list[FilterDefinition] = []
    fields: list[ReportField] = []
    computed: list[ComputedField] = []
