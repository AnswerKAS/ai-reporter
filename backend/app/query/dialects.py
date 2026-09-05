"""Различия SQL-диалектов источников: цитирование, даты, параметры.

Интерфейс намеренно узкий — сюда же встанет локальный движок (CSV и
кросс-источниковые джойны), когда до него дойдут руки.
"""

from ..datasets.base import DatasetError

GRAINS = ('day', 'week', 'month', 'quarter', 'year')


class Dialect:
    """База: SQL-92, от неё отличаются диалекты источников."""

    name = 'sql'

    def quote(self, ident: str) -> str:
        return '"' + ident.replace('"', '') + '"'

    def date_trunc(self, expr: str, grain: str) -> str:
        raise NotImplementedError

    def placeholder(self, name: str, type_: str = 'string') -> str:
        raise NotImplementedError

    def date_bound(self, name: str, *, next_day: bool = False) -> str:
        """Граница периода как дата.

        Верхняя граница берётся следующим днём и сравнивается строго: колонка
        может быть меткой времени, и `<= '2026-03-31'` отрезало бы весь
        последний день, кроме полуночи.
        """
        raise NotImplementedError

    def join_settings(self) -> str:
        """Хвост запроса, нужный источнику для корректного FULL JOIN."""
        return ''

    def limit_offset(self, limit: int, offset: int = 0) -> str:
        """Ограничение выдачи — без ведущего разделителя: его ставит вызывающий.

        В одном месте (список значений фильтра) клауза приклеена пробелом, во
        всех остальных — переводом строки, и разделитель внутри метода сделал
        бы одно из двух мест неверным.
        """
        sql = f'LIMIT {int(limit)}'
        return f'{sql}\nOFFSET {int(offset)}' if offset else sql

    def table_alias(self, expr: str, alias: str) -> str:
        """Таблица или подзапрос с алиасом: не везде перед алиасом пишется AS."""
        return f'{expr} AS {alias}'


class ClickHouseDialect(Dialect):
    name = 'clickhouse'

    _TRUNC = {
        'day': 'toStartOfDay',
        'week': 'toStartOfWeek',
        'month': 'toStartOfMonth',
        'quarter': 'toStartOfQuarter',
        'year': 'toStartOfYear',
    }
    _PARAM_TYPES = {'string': 'String', 'number': 'Float64', 'date': 'Date'}

    def join_settings(self) -> str:
        # без join_use_nulls FULL JOIN подставляет нули вместо NULL, и
        # coalesce по разрезу склеивает несуществующие строки
        return '\nSETTINGS join_use_nulls = 1'

    def quote(self, ident: str) -> str:
        return '`' + ident.replace('`', '') + '`'

    def date_trunc(self, expr: str, grain: str) -> str:
        fn = self._TRUNC.get(grain)
        if fn is None:
            raise DatasetError(f'неизвестная гранулярность даты: {grain}')
        # toDate: колонка может быть DateTime, а на графике нужна дата
        return f'toDate({fn}({expr}))'

    def placeholder(self, name: str, type_: str = 'string') -> str:
        return '{%s:%s}' % (name, self._PARAM_TYPES.get(type_, 'String'))

    def date_bound(self, name: str, *, next_day: bool = False) -> str:
        param = self.placeholder(name, 'date')
        return f'({param} + 1)' if next_day else param


class PostgresDialect(Dialect):
    name = 'postgres'

    def date_trunc(self, expr: str, grain: str) -> str:
        if grain not in GRAINS:
            raise DatasetError(f'неизвестная гранулярность даты: {grain}')
        return f"date_trunc('{grain}', {expr})::date"

    def placeholder(self, name: str, type_: str = 'string') -> str:
        return f'%({name})s'

    def date_bound(self, name: str, *, next_day: bool = False) -> str:
        param = f'%({name})s::date'
        return f'({param} + 1)' if next_day else param


class OracleDialect(Dialect):
    """Oracle 12.2+ (пагинация OFFSET/FETCH — с 12.1, длинные имена — с 12.2)."""

    name = 'oracle'

    # TRUNC(d, 'IW') — понедельник ISO-недели, как date_trunc('week') в PostgreSQL
    _TRUNC = {'day': 'DD', 'week': 'IW', 'month': 'MM', 'quarter': 'Q', 'year': 'YYYY'}

    def date_trunc(self, expr: str, grain: str) -> str:
        fmt = self._TRUNC.get(grain)
        if fmt is None:
            raise DatasetError(f'неизвестная гранулярность даты: {grain}')
        # TRUNC отдаёт DATE с нулевым временем: колонка может быть TIMESTAMP,
        # а на графике нужна дата
        return f"TRUNC({expr}, '{fmt}')"

    def placeholder(self, name: str, type_: str = 'string') -> str:
        # именованная привязка python-oracledb; тип задаёт значение, а не текст
        return f':{name}'

    def date_bound(self, name: str, *, next_day: bool = False) -> str:
        # значение приезжает строкой 'YYYY-MM-DD'; арифметика дат Oracle — в сутках
        param = f"TO_DATE(:{name}, 'YYYY-MM-DD')"
        return f'({param} + 1)' if next_day else param

    def limit_offset(self, limit: int, offset: int = 0) -> str:
        # OFFSET строго перед FETCH — обратный порядок Oracle не принимает
        head = f'OFFSET {int(offset)} ROWS\n' if offset else ''
        return f'{head}FETCH FIRST {int(limit)} ROWS ONLY'

    def table_alias(self, expr: str, alias: str) -> str:
        # AS перед алиасом таблицы в Oracle — синтаксическая ошибка
        return f'{expr} {alias}'


_BY_SOURCE = {
    'clickhouse': ClickHouseDialect,
    'postgres': PostgresDialect,
    'oracle': OracleDialect,
}


def for_source(source: str) -> Dialect:
    cls = _BY_SOURCE.get(source)
    if cls is None:
        raise DatasetError(
            f'источник {source} пока не поддерживается конструктором '
            '(нужен локальный движок запросов)'
        )
    return cls()
